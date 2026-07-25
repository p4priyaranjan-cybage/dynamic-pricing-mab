"""Append-only decision logging - thin wrapper around DB inserts so the
serving layer and pipelines don't need to construct Decision rows by hand."""
from __future__ import annotations

import datetime as dt
import json
import uuid

from bandit_engine.policy import DecisionResult
from db.models import Decision
from db.session import get_session


def log_decision(
    property_id: str,
    tenant_id: str,
    cluster_id: str,
    room_type: str,
    rate_plan: str,
    los_bucket: str,
    stay_date: dt.date,
    context: dict,
    decision: DecisionResult,
    reference_rate: float,
    published_price: float,
    status: str = "pending_approval",
    is_dry_run: bool = False,
) -> str:
    """Persists one live decision. Returns the new decision_id.

    `is_dry_run=True` (Scenario Simulator) must NEVER be counted as a real
    decision for training/metrics - callers filter on Decision.is_dry_run.
    """
    session = get_session()
    try:
        decision_id = str(uuid.uuid4())
        row = Decision(
            decision_id=decision_id,
            property_id=property_id,
            tenant_id=tenant_id,
            cluster_id=cluster_id,
            room_type=room_type,
            rate_plan=rate_plan,
            los_bucket=los_bucket,
            stay_date=dt.datetime.combine(stay_date, dt.time.min),
            decision_ts=dt.datetime.utcnow(),
            context_json=json.dumps(context),
            arm_index=decision.chosen.index,
            arm_label=decision.chosen.label,
            arm_offset_pct=decision.chosen.offset_pct,
            reference_rate=reference_rate,
            published_price=published_price,
            propensity=decision.propensity,
            confidence_score=decision.confidence,
            confidence_breakdown_json=json.dumps(decision.confidence_breakdown),
            status=status,
            is_dry_run=is_dry_run,
            is_historical=False,
        )
        session.add(row)
        session.commit()
        return decision_id
    finally:
        session.close()


def supersede_prior_decisions(
    property_id: str, room_type: str, rate_plan: str, stay_date: dt.date, exclude_decision_id: str | None = None
) -> None:
    """Marks any prior non-superseded live decision for the same
    (property, room_type, rate_plan, stay_date) as superseded, so the rate
    calendar query (serving/api.py) only ever returns the latest one.

    `exclude_decision_id` should always be passed as the decision_id just
    returned by `log_decision` for this same cell - without it, the
    just-inserted row itself matches every filter below (same cell,
    is_historical=False, is_dry_run=False, superseded_at=None yet) and
    would immediately mark ITSELF as superseded, making /rate-calendar and
    /storefront silently return nothing for every decision ever made."""
    session = get_session()
    try:
        q = session.query(Decision).filter(
            Decision.property_id == property_id,
            Decision.room_type == room_type,
            Decision.rate_plan == rate_plan,
            Decision.stay_date == dt.datetime.combine(stay_date, dt.time.min),
            Decision.is_historical.is_(False),
            Decision.is_dry_run.is_(False),
            Decision.superseded_at.is_(None),
        )
        if exclude_decision_id is not None:
            q = q.filter(Decision.decision_id != exclude_decision_id)
        rows = q.all()
        now = dt.datetime.utcnow()
        for row in rows:
            row.superseded_at = now
        session.commit()
    finally:
        session.close()
