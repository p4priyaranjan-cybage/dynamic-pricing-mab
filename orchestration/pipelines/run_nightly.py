"""Nightly pipeline (POC substitute for a scheduled Airflow DAG): reconciles
delayed true rewards for decisions whose stay_date has passed, then retrains
each (cluster, tenant) backbone on the synthetic historical dataset PLUS the
reconciled real outcomes accumulated since the last run, with a QUALITY GATE
that blocks deployment of a retrained model if it fails backtest acceptance.

Run daily:
    python -m orchestration.pipelines.run_nightly

What each step touches:
  - Step 1 reconcile: updates each affected PropertyModel online with the
    realized `true_reward` and increments its `n_observations`.
  - Step 2 retrain: rebuilds BACKBONE models only. Property models are passed
    `only_missing=True` so established ones keep the weights and observation
    count Step 1 just earned; only newly onboarded properties get pretrained.
  - Step 3 gate: runs `run_backtest_suite` on a sample of properties.
      * `reliably_beats_baseline` True  -> promote (already saved as 'current').
      * False -> roll BACKBONES back to their previous version. Property models
        are NOT rolled back: the gate did not evaluate them, and reverting
        would discard genuine reconciled learning from Step 1.

See docs/ARCHITECTURE.md section 9 for the reward design and the history of
the two bugs this ordering now guards against.

See docs/ARCHITECTURE.md "Model Versioning" and docs/ARCHITECTURE_REVIEW.md
"Gap 3: No Automated Model-Quality Gate" for the design rationale.
"""
from __future__ import annotations

import json
import logging
import random

from bandit_engine.training.train import bootstrap_backbones, bootstrap_properties
from bandit_engine.training.offline_eval import run_backtest_suite
from db.models import Property
from db.session import get_session
from feedback.reward_reconciliation import reconcile_pending_decisions
from model_registry.versioning import rollback, sorted_versions

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Quality gate config
BACKTEST_SAMPLE_SIZE = 6  # number of properties to backtest (subset for speed)
BACKTEST_N_ROUNDS = 150
QUALITY_GATE_ENABLED = True  # set False to skip the gate (e.g. during initial bootstrap)


def _get_property_ids() -> list[str]:
    session = get_session()
    try:
        return [p.property_id for p in session.query(Property).all()]
    finally:
        session.close()


def _sample_properties_for_backtest(property_ids: list[str], n: int, seed: int = 99) -> list[str]:
    """Sample a representative subset of properties for the quality gate.
    Uses a fixed seed so backtest results are reproducible across runs."""
    if len(property_ids) <= n:
        return property_ids
    rng = random.Random(seed)
    return rng.sample(property_ids, n)


def _rollback_all_models(property_ids: list[str], cluster_tenant_pairs: list[tuple[str, str]]) -> dict:
    """Rollback the retrained BACKBONE models to their previous version.

    Property models are intentionally preserved - see the comment at the
    property loop below. `property_ids` is still accepted so the caller's
    contract is unchanged, and is reported as `properties_preserved`.
    """
    from pathlib import Path
    MODEL_BASE = Path(__file__).resolve().parent.parent.parent / "model_registry" / "artifacts"

    rolled_back = {
        "backbones": [],
        "properties": [],
        "properties_preserved": len(property_ids),
    }

    for cluster_id, tenant_id in cluster_tenant_pairs:
        base_dir = MODEL_BASE / "backbone" / f"{tenant_id}__{cluster_id}"
        result = rollback(base_dir)
        if result:
            rolled_back["backbones"].append(f"{tenant_id}__{cluster_id} -> {result}")
            logger.info(f"Rolled back backbone {tenant_id}__{cluster_id} to {result}")

    # Property models are deliberately NOT rolled back. The quality gate
    # evaluates the retrained BACKBONES; property models were not retrained by
    # this run (see Step 2, only_missing=True) - their latest version is the
    # one Step 1 saved after applying genuine reconciled rewards. Reverting it
    # because a backbone backtest failed would silently discard real
    # real-world learning that the gate never actually tested.
    logger.info(
        f"Rollback complete: {len(rolled_back['backbones'])} backbones. "
        f"Property models left intact (they carry reconciled online learning)."
    )
    return rolled_back


def main() -> dict:
    # Step 1: Reconcile delayed true rewards
    logger.info("Step 1/3: Reconciling pending decisions...")
    reconcile_summary = reconcile_pending_decisions()
    logger.info(f"Reconciled {reconcile_summary.get('reconciled', 0)} decisions")

    # Step 2: Retrain backbones (new versioned artifacts are created)
    logger.info("Step 2/3: Retraining backbone models...")
    backbone_summary, reward_model_cache = bootstrap_backbones()
    logger.info(f"Retrained {len(backbone_summary)} backbone models")

    # Property models: pretrain ONLY the ones that don't have an artifact yet
    # (newly onboarded properties). Established properties are deliberately
    # left alone - they were just updated online by Step 1, and rebuilding
    # them here would construct fresh PropertyModel instances with
    # n_observations = 0, wiping that learning and resetting the ensemble
    # credibility weight w = n/(n+k) to zero every single night.
    property_summary = bootstrap_properties(reward_model_cache, only_missing=True)
    n_new = sum(1 for p in property_summary if p.get("action") == "pretrained")
    n_kept = sum(1 for p in property_summary if p.get("action") == "skipped_existing")
    logger.info(f"Property models: {n_new} newly pretrained, {n_kept} preserved with online learning")

    # Step 3: Quality gate
    if not QUALITY_GATE_ENABLED:
        logger.warning("Quality gate DISABLED - new models promoted without validation")
        return {
            "reconciliation": reconcile_summary,
            "backbones_retrained": backbone_summary,
            "properties_retrained": property_summary,
            "quality_gate": "disabled",
        }

    logger.info("Step 3/3: Running quality gate (backtest suite)...")
    all_property_ids = _get_property_ids()
    sample_ids = _sample_properties_for_backtest(all_property_ids, BACKTEST_SAMPLE_SIZE)
    logger.info(f"Backtesting {len(sample_ids)} properties: {sample_ids}")

    suite_result = run_backtest_suite(sample_ids, n_rounds=BACKTEST_N_ROUNDS)

    gate_result = {
        "reliably_beats_baseline": suite_result.reliably_beats_baseline,
        "mean_reward_diff": round(suite_result.mean_reward_diff, 2),
        "ci": [round(suite_result.ci_low, 2), round(suite_result.ci_high, 2)],
        "n_wins": suite_result.n_wins,
        "n_properties_tested": suite_result.n_properties,
    }

    if suite_result.reliably_beats_baseline:
        logger.info(
            f"QUALITY GATE PASSED: mean diff = {suite_result.mean_reward_diff:.1f}, "
            f"CI = [{suite_result.ci_low:.1f}, {suite_result.ci_high:.1f}], "
            f"wins = {suite_result.n_wins}/{suite_result.n_properties}"
        )
        return {
            "reconciliation": reconcile_summary,
            "backbones_retrained": backbone_summary,
            "properties_retrained": property_summary,
            "quality_gate": {**gate_result, "action": "promoted"},
        }
    else:
        logger.warning(
            f"QUALITY GATE FAILED: mean diff = {suite_result.mean_reward_diff:.1f}, "
            f"CI = [{suite_result.ci_low:.1f}, {suite_result.ci_high:.1f}], "
            f"wins = {suite_result.n_wins}/{suite_result.n_properties}. "
            f"Rolling back to previous model versions."
        )
        # Rollback
        session = get_session()
        try:
            properties = session.query(Property).all()
            cluster_tenant_pairs = sorted({(p.cluster_id, p.tenant_id) for p in properties})
            prop_ids = [p.property_id for p in properties]
        finally:
            session.close()

        rollback_result = _rollback_all_models(prop_ids, cluster_tenant_pairs)

        return {
            "reconciliation": reconcile_summary,
            "backbones_retrained": backbone_summary,
            "properties_retrained": property_summary,
            "quality_gate": {**gate_result, "action": "rolled_back", "rollback_details": rollback_result},
        }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
