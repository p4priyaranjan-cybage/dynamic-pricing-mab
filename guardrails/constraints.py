"""Config-driven guardrail/constraint engine.

Pre-decision ACTION MASKING: given the full (cluster-scaled) arm ladder and
the current context, filter out arms that would violate any active rule
BEFORE the bandit even sees them - so exploration never wastes probability
mass on infeasible actions. New constraints are added as a small function in
RULE_REGISTRY (or, for pure threshold rules, just a new key in
config/guardrails.yaml) - never require changing the bandit engine itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class GuardrailContext:
    reference_rate: float
    comp_set_avg_rate: Optional[float]
    changes_today: int
    rules: dict
    confidence: Optional[float] = None


@dataclass
class ExcludedArm:
    arm: dict
    reason: str


def rule_price_bounds(arm: dict, ctx: GuardrailContext) -> Optional[str]:
    bounds = ctx.rules.get("price_bounds", {})
    lo = bounds.get("min_offset_pct")
    hi = bounds.get("max_offset_pct")
    if lo is not None and arm["offset_pct"] < lo:
        return f"offset {arm['offset_pct']:.3f} below min_offset_pct {lo}"
    if hi is not None and arm["offset_pct"] > hi:
        return f"offset {arm['offset_pct']:.3f} above max_offset_pct {hi}"
    return None


def rule_competitive_positioning(arm: dict, ctx: GuardrailContext) -> Optional[str]:
    cp = ctx.rules.get("competitive_positioning", {})
    if not cp.get("enabled") or not ctx.comp_set_avg_rate:
        return None
    price = ctx.reference_rate * (1 + arm["offset_pct"])
    index = price / ctx.comp_set_avg_rate
    lo, hi = cp.get("min_index_vs_compset"), cp.get("max_index_vs_compset")
    if lo is not None and index < lo:
        return f"price/compset index {index:.2f} below floor {lo}"
    if hi is not None and index > hi:
        return f"price/compset index {index:.2f} above ceiling {hi}"
    return None


def rule_change_frequency(arm: dict, ctx: GuardrailContext) -> Optional[str]:
    """Throttles PUBLISHING, not recommendation-compute (see
    docs/ARCHITECTURE.md "Recommended Rate Calendar" cadence design). The
    bandit can be re-scored freely; this only blocks a NEW price from being
    pushed if the daily change budget is already exhausted. Arm 3 (Base /
    0% offset, i.e. "no change") is never blocked by this rule."""
    cf = ctx.rules.get("change_frequency", {})
    max_changes = cf.get("max_changes_per_day")
    if max_changes is None or arm["offset_pct"] == 0.0:
        return None
    if ctx.changes_today >= max_changes:
        return f"change-frequency budget exhausted ({ctx.changes_today}/{max_changes} today)"
    return None


def rule_rate_parity(arm: dict, ctx: GuardrailContext) -> Optional[str]:
    """Rate parity is satisfied by construction in this POC: exactly one
    price is computed per (property, room_type, rate_plan, LOS, stay_date)
    cell and reused for every channel (see publisher/base.py) - there is no
    per-channel differentiation that could violate parity, so this rule is
    a documented no-op placeholder for where a real multi-channel system
    would need to actively re-check parity post-publish (Phase 9)."""
    return None


RULE_REGISTRY: list[Callable[[dict, GuardrailContext], Optional[str]]] = [
    rule_price_bounds,
    rule_competitive_positioning,
    rule_change_frequency,
    rule_rate_parity,
]


def filter_arms(arms: list[dict], ctx: GuardrailContext) -> tuple[list[dict], list[ExcludedArm]]:
    allowed, excluded = [], []
    for arm in arms:
        reason = None
        for rule in RULE_REGISTRY:
            reason = rule(arm, ctx)
            if reason:
                break
        if reason:
            excluded.append(ExcludedArm(arm=arm, reason=reason))
        else:
            allowed.append(arm)
    # Always guarantee at least the Base Rate (0% offset) survives, so the
    # system never has zero feasible actions.
    if not allowed:
        base = next((a for a in arms if a["offset_pct"] == 0.0), arms[len(arms) // 2])
        allowed = [base]
        excluded = [e for e in excluded if e.arm is not base]
    return allowed, excluded


def requires_approval(price_delta_pct: float, confidence: float, rules: dict) -> bool:
    """Enhancement discussed in the plan: route to mandatory approval if the
    price delta is large OR confidence is low - not delta-only."""
    approval_cfg = rules.get("approval", {})
    delta_threshold = approval_cfg.get("auto_publish_delta_threshold_pct", 0.03)
    min_confidence = approval_cfg.get("require_approval_if_confidence_below", 0.4)
    if abs(price_delta_pct) > delta_threshold:
        return True
    if confidence < min_confidence:
        return True
    return False
