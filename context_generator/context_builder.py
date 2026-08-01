"""Builds a single plausible context dict for (property, room_type, rate_plan,
stay_date, as_of_date) - the synthetic stand-in for real BI feeds (occupancy,
ADR, pace/pickup, comp-set, events, segment/LOS). Deterministic given a
seeded RNG so historical bootstrap data is reproducible.

Matches config/context_schema.yaml field-for-field so this can be swapped
for a real ETL later (Phase 9) without touching bandit_engine/guardrails/
serving/dashboard code.
"""
from __future__ import annotations

import datetime as dt
import math
import random

from bandit_engine.reference_rate import ReferenceRateInputs, compute_reference_rate
from context_generator.chains import PropertySpec

_DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_SEGMENTS_WEEKDAY = ["corporate", "transient", "corporate", "group"]
_SEGMENTS_WEEKEND = ["leisure", "transient", "leisure", "group"]


def _select_segment(rate_plan: str, is_weekend: bool, rng: random.Random) -> str:
    """Rate-plan-aware segment selection — more realistic than pure random.
    Government/military travelers are mostly transient or group.
    Senior rate is mostly leisure. Corporate plan is obviously corporate.
    BAR/special offer follow the old day-of-week distribution."""
    plan_segments = {
        "government_military": ["transient", "transient", "group", "transient"],
        "senior": ["leisure", "leisure", "leisure", "transient"],
        "corporate_negotiated": ["corporate", "corporate", "corporate", "group"],
        "special_offer": ["leisure", "transient", "leisure", "transient"],
    }
    if rate_plan in plan_segments:
        return rng.choice(plan_segments[rate_plan])
    # Default: day-of-week based
    return rng.choice(_SEGMENTS_WEEKEND if is_weekend else _SEGMENTS_WEEKDAY)


def _los_bucket(nights: int) -> str:
    if nights <= 1:
        return "1"
    if nights == 2:
        return "2"
    if nights <= 5:
        return "3-5"
    if nights <= 8:
        return "6-8"
    return "9+"


def build_context(
    spec: PropertySpec,
    room_type: str,
    rate_plan: str,
    stay_date: dt.date,
    as_of_date: dt.date,
    rng: random.Random,
    los_nights: int = 2,
) -> dict:
    dow_idx = stay_date.weekday()
    is_weekend = dow_idx in (4, 5)  # Fri, Sat treated as the "weekend" leisure peak
    day_of_year = stay_date.timetuple().tm_yday

    # --- Improved: correlated demand signals ---
    # Base occupancy: seasonal (summer peak, winter trough) + weekend lift
    seasonal = 15 * math.sin(2 * math.pi * ((day_of_year - 80) / 365.0))  # peak ~June
    weekend_bump = 14 if is_weekend else 0
    # Market tier matters: luxury has lower base but higher peaks
    tier_base = 50 if spec.market_tier == "luxury" else 58
    base_occ = tier_base + seasonal + weekend_bump + rng.uniform(-6, 6)
    occupancy_pct = max(5.0, min(99.0, base_occ))

    # Events: ~6% chance, but cluster around holidays/weekends more
    event_boost = 0.04 if is_weekend else 0.0
    event_flag = rng.random() < (0.06 + event_boost)
    event_intensity = round(rng.uniform(0.3, 1.0), 2) if event_flag else 0.0
    if event_flag:
        occupancy_pct = min(99.0, occupancy_pct + 22 * event_intensity)

    # Pace correlates with occupancy (high occ = ahead of pace, realistic)
    pace_base = (occupancy_pct - 55) * 0.4 + rng.uniform(-8, 8)
    pace_vs_stly_pct = round(pace_base + (12 * event_intensity), 2)

    # Pickup correlates with pace and events
    pickup_base = max(0, (pace_vs_stly_pct + 5) * 0.8 + rng.uniform(0, 12))
    pickup_last_7d = round(pickup_base + 18 * event_intensity, 2)

    remaining_inventory_pct = round(max(1.0, 100.0 - occupancy_pct + rng.uniform(-3, 3)), 2)

    # ADR trend correlates with demand strength
    adr_trend_pct = round((occupancy_pct - 55) * 0.08 + rng.uniform(-3, 3) + 6 * event_intensity, 2)

    # Segment: rate-plan-aware selection (more realistic)
    segment = _select_segment(rate_plan, is_weekend, rng)

    los_bucket = _los_bucket(los_nights)
    lead_time_days = max(0, (stay_date - as_of_date).days)

    reference_rate = compute_reference_rate(
        ReferenceRateInputs(base_bar=spec.base_bar, room_type=room_type, rate_plan=rate_plan, los_bucket=los_bucket),
        tenant_id=spec.tenant_id,
    )

    # Comp set: reacts to the same market conditions (correlated, not independent)
    n_comp = rng.randint(5, 8)
    market_pressure = 1.0 + (occupancy_pct - 55) * 0.003 + event_intensity * 0.08
    comp_rates = [reference_rate * market_pressure * rng.uniform(0.88, 1.12) for _ in range(n_comp)]
    comp_set_avg_rate = round(sum(comp_rates) / len(comp_rates), 2)
    comp_mean = comp_set_avg_rate
    comp_std = (sum((r - comp_mean) ** 2 for r in comp_rates) / len(comp_rates)) ** 0.5
    compset_dispersion = round(comp_std / comp_mean, 4) if comp_mean else 0.0
    our_rate_vs_compset_index = round(reference_rate / comp_set_avg_rate, 4) if comp_set_avg_rate else 1.0
    rank = 1 + sum(1 for r in comp_rates if r > reference_rate)
    # Comp trend correlates with our ADR trend (same market forces)
    compset_rate_trend_pct = round(adr_trend_pct * rng.uniform(0.5, 1.2) + rng.uniform(-2, 2), 2)

    return {
        "occupancy_pct": round(occupancy_pct, 2),
        "adr_trend_pct": adr_trend_pct,
        "pace_vs_stly_pct": pace_vs_stly_pct,
        "pickup_last_7d": pickup_last_7d,
        "remaining_inventory_pct": remaining_inventory_pct,
        "comp_set_avg_rate": comp_set_avg_rate,
        "our_rate_vs_compset_index": our_rate_vs_compset_index,
        "compset_rate_trend_pct": compset_rate_trend_pct,
        "compset_rank": rank,
        "compset_dispersion": compset_dispersion,
        "event_flag": event_flag,
        "event_intensity": event_intensity,
        "segment": segment,
        "room_type": room_type,
        "rate_plan": rate_plan,
        "los_bucket": los_bucket,
        "day_of_week": _DOW[dow_idx],
        "lead_time_days": lead_time_days,
        "property_id": spec.property_id,
        "cluster_id": spec.cluster_id,
        "tenant_id": spec.tenant_id,
        "_reference_rate": reference_rate,  # convenience, stripped before feeding VW
    }
