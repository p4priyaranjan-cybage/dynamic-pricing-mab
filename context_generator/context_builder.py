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

    # Seasonal wave (slow, +/-15 occupancy points across the year) + weekend bump.
    seasonal = 15 * math.sin(2 * math.pi * (day_of_year / 365.0))
    weekend_bump = 12 if is_weekend else 0
    base_occ = 55 + seasonal + weekend_bump + rng.uniform(-8, 8)
    occupancy_pct = max(5.0, min(99.0, base_occ))

    # ~6% chance of a local demand event on any given date (property-level rng).
    event_flag = rng.random() < 0.06
    event_intensity = round(rng.uniform(0.3, 1.0), 2) if event_flag else 0.0
    if event_flag:
        occupancy_pct = min(99.0, occupancy_pct + 20 * event_intensity)

    pace_vs_stly_pct = round(rng.uniform(-15, 15) + (10 * event_intensity), 2)
    pickup_last_7d = round(max(0.0, rng.uniform(0, 25) + 15 * event_intensity), 2)
    remaining_inventory_pct = round(max(1.0, 100.0 - occupancy_pct + rng.uniform(-5, 5)), 2)
    adr_trend_pct = round(rng.uniform(-6, 6) + 8 * event_intensity, 2)

    segment_pool = _SEGMENTS_WEEKEND if is_weekend else _SEGMENTS_WEEKDAY
    segment = rng.choice(segment_pool)

    los_bucket = _los_bucket(los_nights)
    lead_time_days = max(0, (stay_date - as_of_date).days)

    reference_rate = compute_reference_rate(
        ReferenceRateInputs(base_bar=spec.base_bar, room_type=room_type, rate_plan=rate_plan, los_bucket=los_bucket),
        tenant_id=spec.tenant_id,
    )

    # Simulate a small (5-8 hotel) comp set around our reference rate.
    n_comp = rng.randint(5, 8)
    comp_rates = [reference_rate * rng.uniform(0.85, 1.15) for _ in range(n_comp)]
    comp_set_avg_rate = round(sum(comp_rates) / len(comp_rates), 2)
    comp_mean = comp_set_avg_rate
    comp_std = (sum((r - comp_mean) ** 2 for r in comp_rates) / len(comp_rates)) ** 0.5
    compset_dispersion = round(comp_std / comp_mean, 4) if comp_mean else 0.0
    our_rate_vs_compset_index = round(reference_rate / comp_set_avg_rate, 4) if comp_set_avg_rate else 1.0
    rank = 1 + sum(1 for r in comp_rates if r > reference_rate)
    compset_rate_trend_pct = round(rng.uniform(-5, 5), 2)

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
