"""Reference rate composition.

ReferenceRate(property, room_type, rate_plan, LOS, date) =
    BAR(property, date) x RoomTypeMultiplier(room_type)
                        x RatePlanOffset(rate_plan)
                        x LOSCurve(LOS_bucket)

BAR itself is a SEPARATE component (existing RMS or a demand-forecast
model) - not the bandit. The bandit only learns the %-offset nudge applied
on top of this derived reference rate:

    Price = ReferenceRate x (1 + arm_offset_pct)

For the POC, BAR(property, date) is the property's static `base_bar` plus a
simple day-of-week/seasonality wobble (context_generator/demand_model.py
owns the "ground truth" demand response; this module only owns the price
derivation math, matching the plan's separation of concerns).
"""
from __future__ import annotations

from dataclasses import dataclass

from bandit_engine.config_loader import load_tenant_config


@dataclass
class ReferenceRateInputs:
    base_bar: float
    room_type: str
    rate_plan: str
    los_bucket: str


def _lookup(items: list[dict], code: str, key: str, default: float) -> float:
    for item in items:
        if item["code"] == code:
            return item[key]
    return default


def compute_reference_rate(inputs: ReferenceRateInputs, tenant_id: str) -> float:
    tenant_cfg = load_tenant_config(tenant_id)
    room_multiplier = _lookup(tenant_cfg["room_types"], inputs.room_type, "multiplier", 1.0)
    rate_plan_offset = _lookup(tenant_cfg["rate_plans"], inputs.rate_plan, "offset_multiplier", 1.0)
    los_multiplier = tenant_cfg["los_curve"].get(inputs.los_bucket, 1.0)
    return round(inputs.base_bar * room_multiplier * rate_plan_offset * los_multiplier, 2)


def is_rate_plan_bandit_managed(rate_plan: str, tenant_id: str) -> bool:
    """Contractual/fixed rate plans (corporate-negotiated, wholesale, per-diem)
    are excluded from the bandit's action space entirely."""
    tenant_cfg = load_tenant_config(tenant_id)
    for item in tenant_cfg["rate_plans"]:
        if item["code"] == rate_plan:
            return bool(item.get("bandit_managed", True))
    return True
