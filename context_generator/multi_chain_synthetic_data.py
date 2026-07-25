"""Main POC data-generation entrypoint.

Creates ~15 properties per chain (2 chain archetypes, per config/tenants/)
and ~180 days of historical (context, arm, reward) rows per
property/room_type/bandit-managed-rate-plan, simulated via the static
"old rule-based" baseline policy (always Arm 3 - Base Rate, 0% offset,
propensity 1.0). This intentionally reproduces the real-world "near-zero
exploration in historical logs" problem discussed in the design, which is
why bandit_engine/training/offline_eval.py uses a fitted reward model
(doubly-robust style) rather than naive importance-sampling to pretrain.

Run as: python -m context_generator.multi_chain_synthetic_data
"""
from __future__ import annotations

import datetime as dt
import json
import random
import uuid

from bandit_engine.config_loader import resolve_arm_ladder_for_cluster
from bandit_engine.reference_rate import compute_reference_rate, ReferenceRateInputs, is_rate_plan_bandit_managed
from context_generator.chains import PropertySpec, generate_property_specs
from context_generator.context_builder import build_context
from context_generator.demand_model import compute_rewards, simulate_outcome
from db.models import Property, RatePlan, RoomType, Decision
from db.session import get_session, init_db

HISTORY_DAYS = 365  # a full seasonal cycle - context_builder's occupancy
# sinusoid has a 365-day period, so anything shorter (the original 180)
# never shows the reward model a full high/low season contrast, starving
# it of exactly the kind of signal a richer model (see fit_reward_model)
# needs to differentiate contexts. See docs/ARCHITECTURE.md "Reliability
# plan".
BASE_ARM_INDEX = 3  # "Base Rate", 0% offset - the static historical baseline
SEED = 42


def _seed_properties(session, specs: list[PropertySpec]) -> None:
    for spec in specs:
        if session.get(Property, spec.property_id):
            continue
        session.add(
            Property(
                property_id=spec.property_id,
                name=spec.name,
                tenant_id=spec.tenant_id,
                chain=spec.chain,
                brand=spec.brand,
                region=spec.region,
                market_tier=spec.market_tier,
                cluster_id=spec.cluster_id,
                base_bar=spec.base_bar,
            )
        )
        for rt in spec.room_types:
            session.add(RoomType(property_id=spec.property_id, code=rt["code"], multiplier=rt["multiplier"]))
        for rp in spec.rate_plans:
            session.add(
                RatePlan(
                    property_id=spec.property_id,
                    code=rp["code"],
                    offset_multiplier=rp["offset_multiplier"],
                    bandit_managed=rp.get("bandit_managed", True),
                )
            )
    session.commit()


PILOT_EXPLORATION_PROB = 0.15  # fraction of historical rows drawn from a
# small full-ladder "pilot test" rather than the near-deterministic RM
# heuristic - see docs/ARCHITECTURE.md "Reliability plan" for rationale:
# without SOME real (non-extrapolated) signal at the extreme arms, any
# offline reward model can only ever guess what happens beyond the ~1-tier
# range the deterministic heuristic ever explores. A small pilot-test
# fraction is realistic (real RM teams do occasionally run test cells) and
# is the cheapest, most direct fix for that blind spot. Raised from an
# initial 0.05 to 0.15 (2026-07-25): at 0.05, each of the 7 non-adjacent
# ladder arms only ever got ~0.05/9 =~0.56% of rows (uniformly scattered
# across the ENTIRE context space, since the pilot branch ignores context)
# - only ~3-17 rows per extreme arm at property/cluster scope respectively,
# nowhere near enough to detect real context x price interactions, which
# was the root cause of the reward model collapsing to a single dominant
# arm regardless of context (confirmed: the oracle's own optimal arm was
# spread across 8 of 9 ladder arms for the same contexts where the trained
# bandit picked one arm 150/150 times). 0.15 gives ~1.67% of rows per
# extreme arm - roughly 3x the density - while still being a small minority
# of historical rows overall (85% still follow the realistic near-
# deterministic heuristic).


def _heuristic_policy_index(ladder: list[dict], context: dict) -> int:
    """The deterministic (given context) index the OLD rule-based RM
    heuristic would pick, absent any pilot-test exploration."""
    if context["pace_vs_stly_pct"] < -8 or context["occupancy_pct"] < 40:
        candidate_idx = BASE_ARM_INDEX - 1  # Slight Discount
    elif context["occupancy_pct"] > 80 or context["event_flag"]:
        candidate_idx = BASE_ARM_INDEX + 1  # Slight Premium
    else:
        candidate_idx = BASE_ARM_INDEX
    if not any(a["index"] == candidate_idx for a in ladder):
        candidate_idx = BASE_ARM_INDEX
    return candidate_idx


def _base_policy_prob(ladder: list[dict], index: int, context: dict) -> float:
    """P(index | base heuristic policy, NOT pilot branch) - 0.85 on the
    static Base Rate, 0.15 on whichever single adjacent tier the heuristic
    deterministically nudges to for this context, 0 otherwise."""
    if index == BASE_ARM_INDEX:
        base = 0.85
        return base + 0.15 if _heuristic_policy_index(ladder, context) == BASE_ARM_INDEX else base
    if index == _heuristic_policy_index(ladder, context):
        return 0.15
    return 0.0


def _pick_historical_arm(ladder: list[dict], context: dict, rng: random.Random) -> tuple[dict, float]:
    """The OLD rule-based baseline, now a two-branch mixture policy:

      - (1 - PILOT_EXPLORATION_PROB): the original near-deterministic RM
        heuristic (~85% static Base Rate, ~15% one-tier nudge based on
        obvious pace/occupancy/event signals).
      - PILOT_EXPLORATION_PROB: a uniformly random arm from the FULL
        ladder, simulating a small historical test cell/pilot - this is
        what gives the offline reward model real (non-extrapolated)
        signal at the extreme tiers.

    Returns (arm, propensity) where propensity is the EXACT marginal
    probability of the chosen arm under this mixture (accounting for both
    branches, since the pilot branch can independently land on any arm
    including the ones the heuristic branch would also pick) - required
    for correct importance weighting / doubly-robust offline evaluation
    (bandit_engine/training/offline_eval.py)."""
    n_arms = len(ladder)
    base_arm = next(a for a in ladder if a["index"] == BASE_ARM_INDEX)

    if rng.random() < PILOT_EXPLORATION_PROB:
        arm = rng.choice(ladder)
    elif rng.random() > 0.15:
        arm = base_arm
    else:
        candidate_idx = _heuristic_policy_index(ladder, context)
        arm = next((a for a in ladder if a["index"] == candidate_idx), base_arm)

    marginal_propensity = PILOT_EXPLORATION_PROB * (1.0 / n_arms) + (1 - PILOT_EXPLORATION_PROB) * _base_policy_prob(
        ladder, arm["index"], context
    )
    return arm, marginal_propensity


def _generate_history_for_property(session, spec: PropertySpec, today: dt.date, rng: random.Random) -> int:
    ladder = resolve_arm_ladder_for_cluster(spec.cluster_id)
    rows_written = 0

    managed_rate_plans = [rp["code"] for rp in spec.rate_plans if is_rate_plan_bandit_managed(rp["code"], spec.tenant_id)]

    for days_ago in range(HISTORY_DAYS, 0, -1):
        stay_date = today - dt.timedelta(days=days_ago)
        as_of_date = stay_date - dt.timedelta(days=rng.randint(3, 45))
        los_nights = rng.choice([1, 1, 2, 2, 3, 5, 7, 10])

        for room_type_cfg in spec.room_types:
            room_type = room_type_cfg["code"]
            for rate_plan in managed_rate_plans:
                context = build_context(spec, room_type, rate_plan, stay_date, as_of_date, rng, los_nights=los_nights)
                reference_rate = context.pop("_reference_rate")
                arm, propensity = _pick_historical_arm(ladder, context, rng)
                price = round(reference_rate * (1 + arm["offset_pct"]), 2)

                outcome = simulate_outcome(context, arm["offset_pct"], rate_plan, rng)
                channel = "direct" if rng.random() < 0.6 else "ota_mock"
                proxy_reward, true_reward = compute_rewards(price, outcome, channel)

                decision = Decision(
                    decision_id=str(uuid.uuid4()),
                    property_id=spec.property_id,
                    tenant_id=spec.tenant_id,
                    cluster_id=spec.cluster_id,
                    room_type=room_type,
                    rate_plan=rate_plan,
                    los_bucket=context["los_bucket"],
                    stay_date=dt.datetime.combine(stay_date, dt.time.min),
                    decision_ts=dt.datetime.combine(as_of_date, dt.time.min),
                    context_json=json.dumps(context),
                    arm_index=arm["index"],
                    arm_label=arm["label"],
                    arm_offset_pct=arm["offset_pct"],
                    reference_rate=reference_rate,
                    published_price=price,
                    propensity=propensity,
                    status="historical",
                    is_historical=True,
                    proxy_reward=proxy_reward,
                    true_reward=true_reward,
                    reconciled_at=dt.datetime.combine(stay_date + dt.timedelta(days=2), dt.time.min),
                )
                session.add(decision)
                rows_written += 1
        if rows_written % 500 == 0:
            session.commit()
    session.commit()
    return rows_written


def generate_all(today: dt.date | None = None, seed: int = SEED) -> dict:
    init_db()
    today = today or dt.date.today()
    session = get_session()
    try:
        specs = generate_property_specs(seed=seed)
        _seed_properties(session, specs)

        total_rows = 0
        per_property_rows = {}
        for spec in specs:
            rng = random.Random(f"{seed}:{spec.property_id}")
            n = _generate_history_for_property(session, spec, today, rng)
            per_property_rows[spec.property_id] = n
            total_rows += n

        return {
            "properties": len(specs),
            "historical_decision_rows": total_rows,
            "history_days": HISTORY_DAYS,
        }
    finally:
        session.close()


if __name__ == "__main__":
    summary = generate_all()
    print(json.dumps(summary, indent=2))
