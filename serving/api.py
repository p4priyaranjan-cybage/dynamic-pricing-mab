"""FastAPI serving layer - API-first design so the Streamlit dashboard (and
any future real front-end) never touches the DB or bandit engine directly.

Endpoints:
  GET  /properties                          - list properties (for pickers)
  POST /score                                - score a live decision, logs it (pending_approval or auto_published)
  POST /simulate                             - Scenario Simulator: identical scoring, NEVER persisted (dry_run)
  POST /recommendations                      - on-demand recommendations across a date range (dry-run by default), optional context_overrides
  GET  /rate-calendar                        - latest non-superseded decision per (property/room_type/rate_plan/stay_date)
  GET  /approval-queue                       - pending_approval decisions
  POST /approval-queue/{decision_id}/approve
  POST /approval-queue/{decision_id}/reject
  POST /approval-queue/{decision_id}/override
  GET  /storefront/{property_id}             - currently-live (approved/auto_published) prices only - for a demo OTA/brand-site frontend
  GET  /metrics                              - arm distribution, override rate, confidence, approval stats (JSON, for the Streamlit Monitoring tab)
  GET  /metrics/prometheus                   - Prometheus text-exposition format (HTTP + business metrics, for Grafana)
"""
from __future__ import annotations

import datetime as dt
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

from bandit_engine.config_loader import resolve_arm_ladder_for_cluster, resolve_guardrails_for_tenant
from bandit_engine.policy import BackboneModel, EnsemblePolicy, PropertyModel
from bandit_engine.reference_rate import ReferenceRateInputs, compute_reference_rate
from context_generator.chains import PropertySpec
from context_generator.context_builder import build_context
from db.models import Decision, Property, RatePlan, RoomType
from db.session import get_session, init_db
from feedback.decision_logger import log_decision, supersede_prior_decisions
from guardrails.constraints import GuardrailContext, filter_arms, requires_approval
from monitoring import dashboard_metrics
from publisher.mock_channel import MockChannelPublisher
from serving.schemas import ApprovalAction, RateCalendarRow, RecommendationRequest, ScoreRequest, ScoreResponse

app = FastAPI(title="Dynamic Pricing MAB - Serving API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Prometheus - HTTP-level metrics (request count/latency by path+status) are
# automatic via Instrumentator; the business-level metrics below capture
# one data point per DECISION (not per HTTP request), which is what "log
# every interaction" in Grafana really needs - request counts alone don't
# tell you which arm/confidence/approval-outcome each interaction produced.
Instrumentator().instrument(app).expose(app, endpoint="/metrics/prometheus", include_in_schema=True)

DECISIONS_TOTAL = Counter(
    "pricing_decisions_total", "Pricing decisions made, by kind/status/arm", ["kind", "status", "arm_label"]
)
CONFIDENCE_SCORE = Histogram(
    "pricing_confidence_score", "Confidence score of pricing decisions",
    buckets=(0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
APPROVAL_ACTIONS_TOTAL = Counter(
    "pricing_approval_actions_total", "Approval-queue actions taken", ["action"]
)
PUBLISHER_CALLS_TOTAL = Counter(
    "pricing_publisher_calls_total", "Mock/real channel publisher calls", ["channel_ref"]
)

# Single in-process mock publisher instance - swap for channel_manager_adapter.py
# in production. Called whenever a decision transitions to a live/servable
# state (auto-published on /score, or approved/overridden from the Approval
# Queue) - see _publish_if_live below. Kept as a simple in-memory log for
# the POC; `GET /storefront/{property_id}` reads live state from the DB
# (not from this log), so restarting the API process doesn't lose visibility.
_publisher = MockChannelPublisher()

# Context fields a caller (e.g. the Scenario Simulator's "what-if" panel) is
# allowed to manually override for sensitivity testing - deliberately
# excludes identity/derived fields (property_id, room_type, los_bucket, ...)
# that must stay in sync with the actual request, so a caller can't spoof
# them into an inconsistent state.
OVERRIDABLE_CONTEXT_KEYS = {
    "occupancy_pct",
    "adr_trend_pct",
    "pace_vs_stly_pct",
    "pickup_last_7d",
    "remaining_inventory_pct",
    "comp_set_avg_rate",
    "our_rate_vs_compset_index",
    "compset_rate_trend_pct",
    "compset_dispersion",
    "event_flag",
    "event_intensity",
    "segment",
}


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _load_property_spec(session, property_id: str) -> PropertySpec:
    prop = session.get(Property, property_id)
    if prop is None:
        raise HTTPException(404, f"Unknown property_id: {property_id}")
    room_types = [
        {"code": rt.code, "multiplier": rt.multiplier}
        for rt in session.query(RoomType).filter(RoomType.property_id == property_id).all()
    ]
    rate_plans = [
        {"code": rp.code, "offset_multiplier": rp.offset_multiplier, "bandit_managed": rp.bandit_managed}
        for rp in session.query(RatePlan).filter(RatePlan.property_id == property_id).all()
    ]
    return PropertySpec(
        property_id=prop.property_id,
        name=prop.name,
        tenant_id=prop.tenant_id,
        chain=prop.chain,
        brand=prop.brand,
        region=prop.region,
        market_tier=prop.market_tier,
        cluster_id=prop.cluster_id,
        base_bar=prop.base_bar,
        room_types=room_types,
        rate_plans=rate_plans,
    )


def _to_calendar_row(r: Decision) -> RateCalendarRow:
    """Shared Decision -> RateCalendarRow mapping used by /rate-calendar,
    /approval-queue, and /storefront so the three views can't drift."""
    price = r.override_price if r.override_price is not None else r.published_price
    return RateCalendarRow(
        decision_id=r.decision_id,
        property_id=r.property_id,
        room_type=r.room_type,
        rate_plan=r.rate_plan,
        los_bucket=r.los_bucket,
        stay_date=r.stay_date.date(),
        reference_rate=r.reference_rate,
        published_price=price,
        arm_label=r.arm_label,
        arm_offset_pct=r.arm_offset_pct,
        confidence_score=r.confidence_score,
        confidence_label="High" if r.confidence_score > 0.7 else ("Medium" if r.confidence_score >= 0.4 else "Low"),
        status=r.status,
        decision_ts=r.decision_ts,
        context=json.loads(r.context_json) if r.context_json else {},
    )


def _publish_if_live(row: Decision) -> None:
    """Calls the mock publisher when a decision is in a live/servable state
    (auto_published, or approved - including overridden). No-op for
    pending_approval/rejected. Best-effort only - the POC mock publisher
    can't fail, but a real channel-manager adapter's errors shouldn't block
    the decision itself from being persisted, so this is deliberately
    called AFTER the DB write/commit in every caller."""
    if row.status not in ("auto_published", "approved"):
        return
    price = row.override_price if row.override_price is not None else row.published_price
    result = _publisher.publish(row.property_id, row.room_type, row.rate_plan, row.stay_date.date(), price)
    for channel_ref in result.get("channel_refs", []):
        PUBLISHER_CALLS_TOTAL.labels(channel_ref=channel_ref).inc()


@app.get("/properties")
def list_properties():
    session = get_session()
    try:
        rows = session.query(Property).all()
        return [
            {
                "property_id": p.property_id,
                "name": p.name,
                "tenant_id": p.tenant_id,
                "chain": p.chain,
                "brand": p.brand,
                "region": p.region,
                "cluster_id": p.cluster_id,
                "market_tier": p.market_tier,
                "base_bar": p.base_bar,
            }
            for p in rows
        ]
    finally:
        session.close()


@app.get("/properties/{property_id}/config")
def property_config(property_id: str):
    """Room-type/rate-plan codes for one property - lets the dashboard offer
    dropdowns instead of asking users to type exact config codes from
    memory. Only bandit-managed rate plans are returned (e.g. a fixed
    corporate-negotiated plan isn't something the Scenario Simulator can
    meaningfully price)."""
    session = get_session()
    try:
        spec = _load_property_spec(session, property_id)
        return {
            "room_types": [rt["code"] for rt in spec.room_types],
            "rate_plans": [rp["code"] for rp in spec.rate_plans if rp.get("bandit_managed", True)],
        }
    finally:
        session.close()


def _score(req: ScoreRequest) -> tuple[ScoreResponse, dict | None]:
    session = get_session()
    try:
        spec = _load_property_spec(session, req.property_id)
        as_of_date = req.as_of_date or dt.date.today()
        import random

        rng = random.Random(f"{req.property_id}:{req.room_type}:{req.rate_plan}:{req.stay_date}")
        context = build_context(spec, req.room_type, req.rate_plan, req.stay_date, as_of_date, rng, los_nights=req.los_nights)
        reference_rate = context.pop("_reference_rate")

        if req.context_overrides:
            invalid_keys = set(req.context_overrides) - OVERRIDABLE_CONTEXT_KEYS
            if invalid_keys:
                raise HTTPException(400, f"context_overrides contains non-overridable keys: {sorted(invalid_keys)}")
            context.update(req.context_overrides)

        ladder = resolve_arm_ladder_for_cluster(spec.cluster_id)
        guardrails = resolve_guardrails_for_tenant(spec.tenant_id)

        changes_today = (
            session.query(Decision)
            .filter(
                Decision.property_id == req.property_id,
                Decision.is_historical.is_(False),
                Decision.is_dry_run.is_(False),
                Decision.decision_ts >= dt.datetime.combine(dt.date.today(), dt.time.min),
                Decision.arm_offset_pct != 0.0,
            )
            .count()
        )
        gctx = GuardrailContext(
            reference_rate=reference_rate,
            comp_set_avg_rate=context.get("comp_set_avg_rate"),
            changes_today=changes_today,
            rules=guardrails,
        )
        allowed_arms, excluded_arms = filter_arms(ladder, gctx)

        backbone = BackboneModel.load_or_create(spec.cluster_id, spec.tenant_id)
        prop_model = PropertyModel.load_or_create(req.property_id)
        tenant_cfg_weights = guardrails.get("confidence_weights", {}) or {
            "w_sample": 0.4,
            "w_agreement": 0.35,
            "w_margin": 0.25,
        }
        policy = EnsemblePolicy(
            prop_model, backbone,
            blend_smoothing_k=guardrails.get("ensemble", {}).get("blend_smoothing_k", 20.0),
            confidence_weights=tenant_cfg_weights,
        )
        decision = policy.decide(context, allowed_arms, explore=not req.dry_run)

        price = round(reference_rate * (1 + decision.chosen.offset_pct), 2)
        approval_needed = requires_approval(decision.chosen.offset_pct, decision.confidence, guardrails)

        CONFIDENCE_SCORE.observe(decision.confidence)
        DECISIONS_TOTAL.labels(
            kind="dry_run" if req.dry_run else "live",
            status="requires_approval" if approval_needed else "auto_published",
            arm_label=decision.chosen.label,
        ).inc()

        response = ScoreResponse(
            property_id=req.property_id,
            room_type=req.room_type,
            rate_plan=req.rate_plan,
            stay_date=req.stay_date,
            reference_rate=round(reference_rate, 2),
            chosen_arm_label=decision.chosen.label,
            chosen_arm_offset_pct=decision.chosen.offset_pct,
            published_price=price,
            confidence_score=decision.confidence,
            confidence_label=decision.confidence_label,
            confidence_breakdown=decision.confidence_breakdown,
            requires_approval=approval_needed,
            excluded_arms=[{"arm": e.arm, "reason": e.reason} for e in excluded_arms],
            all_arms=[{"index": a.index, "label": a.label, "offset_pct": a.offset_pct, "probability": a.probability} for a in decision.all_arms],
            context=context,
        )
        extra = {
            "spec": spec, "context": context, "decision": decision,
            "reference_rate": reference_rate, "price": price, "approval_needed": approval_needed,
        }
        return response, extra
    finally:
        session.close()


@app.post("/simulate", response_model=ScoreResponse)
def simulate(req: ScoreRequest):
    """Scenario Simulator endpoint - side-effect-free: never writes a
    Decision row, never affects training. Forces dry_run=True regardless of
    the request body."""
    req = req.model_copy(update={"dry_run": True})
    response, _ = _score(req)
    return response


@app.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest):
    if req.dry_run:
        return simulate(req)
    response, extra = _score(req)
    status = "pending_approval" if extra["approval_needed"] else "auto_published"
    decision_id = log_decision(
        property_id=req.property_id,
        tenant_id=extra["spec"].tenant_id,
        cluster_id=extra["spec"].cluster_id,
        room_type=req.room_type,
        rate_plan=req.rate_plan,
        los_bucket=extra["context"]["los_bucket"],
        stay_date=req.stay_date,
        context=extra["context"],
        decision=extra["decision"],
        reference_rate=extra["reference_rate"],
        published_price=extra["price"],
        status=status,
        is_dry_run=False,
    )
    supersede_prior_decisions(req.property_id, req.room_type, req.rate_plan, req.stay_date, exclude_decision_id=decision_id)
    response.decision_id = decision_id
    if status == "auto_published":
        session = get_session()
        try:
            row = session.get(Decision, decision_id)
            _publish_if_live(row)
        finally:
            session.close()
    return response


@app.post("/recommendations", response_model=list[ScoreResponse])
def recommendations(req: RecommendationRequest):
    """On-demand recommendations across a date range (daily/weekly/monthly -
    just pass the corresponding start_date/end_date), reusing the exact
    same explainability payload as /score for each day (confidence_breakdown,
    all_arms, excluded_arms). Dry-run (side-effect-free, like /simulate) by
    default - pass persist=true to actually log each day as a real decision
    (equivalent to calling /score once per day) instead of just previewing.
    `context_overrides` (same allowed keys as /score/simulate - see
    OVERRIDABLE_CONTEXT_KEYS) is applied identically to every day in the
    range, e.g. to preview "what if occupancy were X% all week". POST (not
    GET) specifically because context_overrides is a nested dict, which
    doesn't map cleanly onto query params.
    """
    if req.end_date < req.start_date:
        raise HTTPException(400, "end_date must be >= start_date")
    if (req.end_date - req.start_date).days > 90:
        raise HTTPException(400, "date range too large (max 90 days) - call in smaller batches")

    results = []
    d = req.start_date
    while d <= req.end_date:
        score_req = ScoreRequest(
            property_id=req.property_id, room_type=req.room_type, rate_plan=req.rate_plan,
            stay_date=d, los_nights=req.los_nights, dry_run=not req.persist,
            context_overrides=req.context_overrides,
        )
        results.append(score(score_req) if req.persist else simulate(score_req))
        d += dt.timedelta(days=1)
    return results


@app.get("/rate-calendar", response_model=list[RateCalendarRow])
def rate_calendar(
    property_id: str | None = None,
    room_type: str | None = None,
    rate_plan: str | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
):
    session = get_session()
    try:
        q = session.query(Decision).filter(
            Decision.is_historical.is_(False),
            Decision.is_dry_run.is_(False),
            Decision.superseded_at.is_(None),
        )
        if property_id:
            q = q.filter(Decision.property_id == property_id)
        if room_type:
            q = q.filter(Decision.room_type == room_type)
        if rate_plan:
            q = q.filter(Decision.rate_plan == rate_plan)
        if start_date:
            q = q.filter(Decision.stay_date >= dt.datetime.combine(start_date, dt.time.min))
        if end_date:
            q = q.filter(Decision.stay_date <= dt.datetime.combine(end_date, dt.time.min))
        rows = q.order_by(Decision.stay_date).all()
        return [_to_calendar_row(r) for r in rows]
    finally:
        session.close()


@app.get("/approval-queue", response_model=list[RateCalendarRow])
def approval_queue(property_id: str | None = None):
    session = get_session()
    try:
        q = session.query(Decision).filter(Decision.status == "pending_approval")
        if property_id:
            q = q.filter(Decision.property_id == property_id)
        rows = q.order_by(Decision.decision_ts.desc()).all()
        return [_to_calendar_row(r) for r in rows]
    finally:
        session.close()


@app.get("/storefront/{property_id}", response_model=list[RateCalendarRow])
def storefront(property_id: str):
    """Read-only view of what a guest would currently see live for this
    property - only approved/auto_published, non-superseded decisions
    (excludes pending_approval/rejected, which were never actually shown to
    anyone). Intended for a future 'dummy OTA/brand site' demo frontend to
    poll and show a price updating live right after it's approved in the
    dashboard/Approval Queue."""
    session = get_session()
    try:
        q = session.query(Decision).filter(
            Decision.property_id == property_id,
            Decision.is_historical.is_(False),
            Decision.is_dry_run.is_(False),
            Decision.superseded_at.is_(None),
            Decision.status.in_(("approved", "auto_published")),
        )
        rows = q.order_by(Decision.stay_date).all()
        return [_to_calendar_row(r) for r in rows]
    finally:
        session.close()


def _update_decision_status(decision_id: str, status: str, approved_by: str | None = None, override_price: float | None = None) -> dict:
    session = get_session()
    try:
        row = session.get(Decision, decision_id)
        if row is None:
            raise HTTPException(404, f"Unknown decision_id: {decision_id}")
        row.status = status
        if approved_by:
            row.approved_by = approved_by
        if override_price is not None:
            row.override_price = override_price
        session.commit()
        _publish_if_live(row)
        return {"decision_id": decision_id, "status": status}
    finally:
        session.close()


@app.post("/approval-queue/{decision_id}/approve")
def approve(decision_id: str, action: ApprovalAction):
    result = _update_decision_status(decision_id, "approved", approved_by=action.approved_by)
    APPROVAL_ACTIONS_TOTAL.labels(action="approve").inc()
    return result


@app.post("/approval-queue/{decision_id}/reject")
def reject(decision_id: str, action: ApprovalAction):
    result = _update_decision_status(decision_id, "rejected", approved_by=action.approved_by)
    APPROVAL_ACTIONS_TOTAL.labels(action="reject").inc()
    return result


@app.post("/approval-queue/{decision_id}/override")
def override(decision_id: str, action: ApprovalAction):
    if action.override_price is None:
        raise HTTPException(400, "override_price is required for override action")
    result = _update_decision_status(decision_id, "approved", approved_by=action.approved_by, override_price=action.override_price)
    APPROVAL_ACTIONS_TOTAL.labels(action="override").inc()
    return result


@app.get("/metrics")
def metrics(cluster_id: str | None = None, tenant_id: str | None = None):
    return {
        "arm_distribution": dashboard_metrics.arm_distribution(cluster_id, tenant_id),
        "override_rate": dashboard_metrics.override_rate(cluster_id),
        "approval_stats": dashboard_metrics.approval_stats(cluster_id),
        "average_confidence": dashboard_metrics.average_confidence(cluster_id),
    }
