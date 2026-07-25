"""Fleet bootstrap orchestrator.

Trains one BackboneModel per (cluster_id, tenant_id) present in the DB, and
one PropertyModel per property, using the reward-model-based offline
pretraining examples from offline_eval.build_augmented_training_examples*.

Per the reliability plan (docs/ARCHITECTURE.md "Reliability plan" Phase
2.4), each property's bootstrap reuses the SAME cluster-level reward model
fit for its backbone - a single property's own ~150-400 historical rows are
far too few to reliably fit a price-elasticity regression on their own,
whereas pooling within a cluster gives it enough data to work with. Only
the historical CONTEXT rows are property-specific; the imputation model
itself is shared.

Run as: python -m bandit_engine.training.train
"""
from __future__ import annotations

import json

from bandit_engine.config_loader import resolve_arm_ladder_for_cluster
from bandit_engine.policy import BackboneModel, PropertyModel
from bandit_engine.training.offline_eval import (
    build_augmented_training_examples_from_rows,
    get_reward_model_for_group,
    query_historical_rows,
)
from db.models import Property
from db.session import get_session

BACKBONE_HISTORY_CAP = 3000  # historical rows sampled per (cluster,tenant) before x9-arm expansion
PROPERTY_HISTORY_CAP = 600  # historical rows sampled per property before x9-arm expansion


def bootstrap_backbones() -> tuple[list[dict], dict]:
    """Returns (summary, reward_model_cache) - the cache is reused by
    bootstrap_properties() so each property's bootstrap shares its
    cluster's reward model rather than re-fitting on its own sparse data."""
    session = get_session()
    try:
        properties = session.query(Property).all()
        pairs = sorted({(p.cluster_id, p.tenant_id) for p in properties})
    finally:
        session.close()

    summary = []
    reward_model_cache: dict[tuple[str, str], tuple] = {}
    for cluster_id, tenant_id in pairs:
        ladder = resolve_arm_ladder_for_cluster(cluster_id)
        reward_model, rows = get_reward_model_for_group(
            cluster_id=cluster_id, tenant_id=tenant_id, cap=BACKBONE_HISTORY_CAP
        )
        reward_model_cache[(cluster_id, tenant_id)] = (reward_model, ladder)
        examples = build_augmented_training_examples_from_rows(rows, ladder, reward_model)
        backbone = BackboneModel(cluster_id, tenant_id)
        backbone.learn_batch(examples)
        backbone.save()
        summary.append(
            {
                "cluster_id": cluster_id,
                "tenant_id": tenant_id,
                "n_historical_rows": len(rows),
                "n_examples": len(examples),
                "reward_model_auc": round(reward_model.auc, 4) if reward_model and reward_model.auc is not None else None,
                "reward_model_reliable": reward_model.reliable if reward_model else False,
            }
        )
    return summary, reward_model_cache


def bootstrap_properties(reward_model_cache: dict | None = None) -> list[dict]:
    session = get_session()
    try:
        properties = session.query(Property).all()
        prop_list = [(p.property_id, p.cluster_id, p.tenant_id) for p in properties]
    finally:
        session.close()

    reward_model_cache = reward_model_cache or {}
    summary = []
    for property_id, cluster_id, tenant_id in prop_list:
        key = (cluster_id, tenant_id)
        if key in reward_model_cache:
            reward_model, ladder = reward_model_cache[key]
        else:
            ladder = resolve_arm_ladder_for_cluster(cluster_id)
            reward_model, _ = get_reward_model_for_group(cluster_id=cluster_id, tenant_id=tenant_id, cap=BACKBONE_HISTORY_CAP)
            reward_model_cache[key] = (reward_model, ladder)

        prop_rows = query_historical_rows(property_id=property_id, cap=PROPERTY_HISTORY_CAP)
        examples = build_augmented_training_examples_from_rows(prop_rows, ladder, reward_model)
        model = PropertyModel(property_id)
        for ex in examples:
            # count_as_observation=False: this is bootstrap pretraining, not
            # earned real-world trust - see PropertyModel.learn docstring.
            # n_observations (and therefore the ensemble's credibility
            # weight toward this property vs. its shared backbone) should
            # only grow from real interactions (EnsemblePolicy.record_feedback
            # / feedback/reward_reconciliation.py), so a freshly-bootstrapped
            # property still leans on the pooled backbone until it has.
            model.learn(
                ex["context"], ex["arms"], ex["chosen_pos"], ex["propensity"], ex["reward"],
                count_as_observation=False,
            )
        model.save()
        summary.append({"property_id": property_id, "n_historical_rows": len(prop_rows), "n_examples": len(examples)})
    return summary


def bootstrap_all() -> dict:
    backbones, reward_model_cache = bootstrap_backbones()
    properties = bootstrap_properties(reward_model_cache)
    return {"backbones": backbones, "properties": properties}


if __name__ == "__main__":
    result = bootstrap_all()
    print(json.dumps(result, indent=2))
