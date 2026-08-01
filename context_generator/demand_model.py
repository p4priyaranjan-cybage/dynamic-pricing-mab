"""Ground-truth price-elasticity demand simulator ("reality" for the POC).

Given a context + a chosen arm's %-offset, simulates whether a booking
occurs and, if so, whether it is later cancelled - this is what supplies
both the fast proxy reward (booked same-day signal) and the delayed true
reward (booked AND not cancelled, net of channel commission) used
throughout the plan's two-stage reward design.
"""
from __future__ import annotations

import math
import random

SEGMENT_ELASTICITY = {
    "transient": 1.0,
    "leisure": 1.25,
    "corporate": 0.55,
    "group": 0.80,
}

# Rate-plan-specific elasticity modifier: government/senior guests booking
# on discounted plans are less price-sensitive to further discounting (already
# getting a deal) but more sensitive to premiums (will switch to another hotel).
RATE_PLAN_ELASTICITY_MODIFIER = {
    "bar_best_available": 1.0,
    "government_military": 0.7,   # less elastic overall (captive demand, per-diem budget)
    "senior": 0.85,               # slightly less elastic (loyalty, routine)
    "special_offer": 1.15,        # more elastic (deal-seekers compare aggressively)
    "corporate_negotiated": 0.4,  # very inelastic (contractual, not price-shopping)
}

BASE_LOGIT = -0.55


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def booking_probability(context: dict, offset_pct: float, rate_plan: str = "bar_best_available") -> float:
    demand = 0.0
    demand += 0.022 * (context["occupancy_pct"] - 60.0)
    demand += 0.014 * context["pace_vs_stly_pct"]
    demand += 1.1 * context["event_intensity"]
    demand += 0.5 if context["event_flag"] else 0.0
    demand -= 0.6 * max(0.0, context["our_rate_vs_compset_index"] - 1.0)
    demand += 0.01 * context["pickup_last_7d"]

    # Elasticity is segment × rate-plan specific
    segment_elast = SEGMENT_ELASTICITY.get(context["segment"], 1.0)
    plan_modifier = RATE_PLAN_ELASTICITY_MODIFIER.get(rate_plan, 1.0)
    elasticity = 2.4 * segment_elast * plan_modifier

    logit = BASE_LOGIT + demand - elasticity * offset_pct
    return _sigmoid(logit)


def cancellation_probability(context: dict, rate_plan: str) -> float:
    base = 0.12
    if rate_plan == "advance_purchase_30":
        base = 0.03
    if context["segment"] == "group":
        base += 0.05
    return min(0.6, base)


def simulate_outcome(context: dict, offset_pct: float, rate_plan: str, rng: random.Random) -> dict:
    p_book = booking_probability(context, offset_pct, rate_plan)
    booked = rng.random() < p_book
    cancelled = False
    if booked:
        cancelled = rng.random() < cancellation_probability(context, rate_plan)
    return {"booked": booked, "cancelled": cancelled, "p_book": round(p_book, 4)}


# Rough OTA-vs-direct commission assumption used when reconciling true
# reward "net of channel commission" (docs/ARCHITECTURE.md).
CHANNEL_COMMISSION_PCT = {
    "direct": 0.0,
    "ota_mock": 0.15,
}


def compute_rewards(price: float, outcome: dict, channel: str = "direct") -> tuple[float, float]:
    """Returns (proxy_reward, true_reward).

    proxy_reward: fast, same-day signal (1.0 if booked, else 0.0) - noisy but
    immediate, drives the property model's online learning loop.
    true_reward: delayed, realized revenue net of cancellations AND channel
    commission - drives the backbone's gated batch retrain.
    """
    proxy_reward = 1.0 if outcome["booked"] else 0.0
    if outcome["booked"] and not outcome["cancelled"]:
        commission = CHANNEL_COMMISSION_PCT.get(channel, 0.0)
        true_reward = price * (1 - commission)
    else:
        true_reward = 0.0
    return proxy_reward, true_reward
