"""One-time fleet bootstrap pipeline (POC substitute for an Airflow DAG -
see docs/ARCHITECTURE.md "Orchestration" section for the production
mapping). Run once after generating synthetic history:

    python -m orchestration.pipelines.run_bootstrap
"""
from __future__ import annotations

import json

from context_generator.multi_chain_synthetic_data import generate_all
from bandit_engine.training.train import bootstrap_all


def main() -> dict:
    gen_summary = generate_all()
    train_summary = bootstrap_all()
    return {"data_generation": gen_summary, "training": train_summary}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
