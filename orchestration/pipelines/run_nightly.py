"""Nightly pipeline (POC substitute for a scheduled Airflow DAG): reconciles
delayed true rewards for decisions whose stay_date has passed, then
retrains each (cluster, tenant) backbone on the freshest historical +
reconciled data. Run daily:

    python -m orchestration.pipelines.run_nightly
"""
from __future__ import annotations

import json

from bandit_engine.training.train import bootstrap_backbones
from feedback.reward_reconciliation import reconcile_pending_decisions


def main() -> dict:
    reconcile_summary = reconcile_pending_decisions()
    backbone_summary, _reward_model_cache = bootstrap_backbones()
    return {"reconciliation": reconcile_summary, "backbones_retrained": backbone_summary}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
