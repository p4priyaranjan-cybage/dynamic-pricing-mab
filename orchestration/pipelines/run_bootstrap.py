"""One-time fleet bootstrap pipeline (POC substitute for an Airflow DAG -
see docs/ARCHITECTURE.md "Orchestration" section for the production
mapping). Run once after generating synthetic history:

    python -m orchestration.pipelines.run_bootstrap

Idempotent: skips data generation + training if the DB already has
properties (i.e., a previous bootstrap already ran on this volume).
"""
from __future__ import annotations

import json
import os

from db.session import init_db, get_session
from db.models import Decision, Property


def _bootstrap_state() -> dict:
    """Inspect the DB to decide whether a bootstrap is still needed.

    Checks BOTH properties and historical rows, not just properties.
    `_seed_properties()` commits Property rows before history generation
    begins, so a run interrupted midway leaves properties present with
    partial history - a properties-only check would then skip forever and
    leave the fleet permanently under-trained.
    """
    init_db()
    session = get_session()
    try:
        n_properties = session.query(Property).count()
        n_historical = session.query(Decision).filter(Decision.is_historical.is_(True)).count()
    finally:
        session.close()
    return {
        "properties": n_properties,
        "historical_rows": n_historical,
        # A complete bootstrap always writes history for every property it
        # seeded. Requiring a plausible minimum per property catches the
        # interrupted-run case without hardcoding the exact expected total.
        "complete": n_properties > 0 and n_historical >= n_properties * 100,
    }


def main() -> dict:
    force = os.environ.get("FORCE_BOOTSTRAP", "").lower() in ("1", "true", "yes")
    state = _bootstrap_state()

    if state["complete"] and not force:
        print(
            f"Bootstrap already complete: {state['properties']} properties, "
            f"{state['historical_rows']} historical rows. Skipping regeneration "
            f"and retraining. Set FORCE_BOOTSTRAP=1 to override."
        )
        return {"status": "skipped", **state}

    if state["properties"] > 0 and not state["complete"]:
        print(
            f"WARNING: partial bootstrap detected ({state['properties']} properties "
            f"but only {state['historical_rows']} historical rows) - a previous run "
            f"was likely interrupted. Completing it now."
        )
    if force:
        print("FORCE_BOOTSTRAP set - regenerating and retraining regardless of existing data.")

    from context_generator.multi_chain_synthetic_data import generate_all
    from bandit_engine.training.train import bootstrap_all

    gen_summary = generate_all()
    train_summary = bootstrap_all()
    return {"status": "completed", "data_generation": gen_summary, "training": train_summary}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
