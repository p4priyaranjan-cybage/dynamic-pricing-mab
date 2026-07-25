"""Reward reconciliation job - joins decisions with (simulated) realized
outcomes and computes true_reward net of channel commission, then feeds the
online-learning fast loop (PropertyModel) with the newly reconciled reward.

For this POC, "realized outcomes" are simulated via context_generator.
demand_model (acting as the stand-in for a real PMS/booking-engine
webhook feed) - the module boundary is deliberately the same one a real
integration would replace (see docs/ARCHITECTURE.md Phase 9 notes).
"""
from __future__ import annotations

import datetime as dt
import json
import random

from bandit_engine.config_loader import resolve_arm_ladder_for_cluster
from bandit_engine.policy import PropertyModel
from context_generator.demand_model import compute_rewards, simulate_outcome
from db.models import Decision
from db.session import get_session


def reconcile_pending_decisions(as_of: dt.date | None = None, seed: int = 7) -> dict:
    """Finds live (non-historical, non-dry-run) decisions whose stay_date has
    passed and that have not yet been reconciled, simulates the realized
    outcome, computes true_reward, persists it, and feeds the property's
    fast online-learning loop with the reward (see PropertyModel.learn -
    the ONLY path that mutates a property's own weights).

    Only decisions with status "approved" or "auto_published" are
    reconciled - i.e. ones that were actually live/servable to a guest.
    "rejected" and still-"pending_approval" decisions are left alone
    (reconciled_at stays None): a rejected recommendation was never shown
    to anyone, and one that's still awaiting review by the time its stay
    date passes has no legitimate outcome to attribute to the model
    either. Previously this filtered ONLY on is_historical/is_dry_run/
    reconciled_at/stay_date - silently reconciling rejected and pending
    decisions exactly like approved ones, which fed the bandit outcomes
    for prices that were never actually served."""
    as_of = as_of or dt.date.today()
    rng = random.Random(seed)
    session = get_session()
    reconciled = 0
    try:
        rows = (
            session.query(Decision)
            .filter(
                Decision.is_historical.is_(False),
                Decision.is_dry_run.is_(False),
                Decision.reconciled_at.is_(None),
                Decision.stay_date <= dt.datetime.combine(as_of, dt.time.min),
                Decision.status.in_(("approved", "auto_published")),
            )
            .all()
        )
        # Cache one PropertyModel per property_id to avoid reloading repeatedly.
        models: dict[str, PropertyModel] = {}
        ladders: dict[str, list[dict]] = {}

        for row in rows:
            context = json.loads(row.context_json)

            # If a human overrode the price (approval_queue "override"
            # action), the guest actually saw override_price, not the
            # bandit's original published_price/arm_offset_pct - simulate
            # the outcome (and compute the reward) against what was truly
            # shown, not what the bandit originally proposed. The learning
            # update below still credits the bandit's ORIGINALLY CHOSEN arm
            # (row.arm_index) - the override is real-world feedback about
            # the consequences of that choice at a human-adjusted price,
            # not a claim that the bandit itself picked a different arm.
            if row.override_price is not None:
                effective_price = row.override_price
                effective_offset = (row.override_price / row.reference_rate) - 1.0
            else:
                effective_price = row.published_price
                effective_offset = row.arm_offset_pct

            outcome = simulate_outcome(context, effective_offset, row.rate_plan, rng)
            channel = "direct" if rng.random() < 0.6 else "ota_mock"
            proxy_reward, true_reward = compute_rewards(effective_price, outcome, channel)

            row.proxy_reward = proxy_reward
            row.true_reward = true_reward
            row.reconciled_at = dt.datetime.utcnow()

            if row.property_id not in models:
                models[row.property_id] = PropertyModel.load_or_create(row.property_id)
                ladders[row.property_id] = resolve_arm_ladder_for_cluster(row.cluster_id)
            model = models[row.property_id]
            ladder = ladders[row.property_id]
            chosen_pos = next(i for i, a in enumerate(ladder) if a["index"] == row.arm_index)
            model.learn(context, ladder, chosen_pos, row.propensity, true_reward)

            reconciled += 1

        session.commit()
        for model in models.values():
            model.save()
        return {"reconciled": reconciled, "properties_updated": len(models)}
    finally:
        session.close()
