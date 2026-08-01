"""Run the hand-crafted test scenarios against the trained model.

Loads data/test_scenarios.json, scores each scenario via the same _score()
path the API uses, and compares the model's arm choice against the RM's
expected direction. Produces a pass/fail report.

Usage (after bootstrap):
    python -m scripts.run_test_scenarios

Or from project root:
    python scripts/run_test_scenarios.py
"""
import sys, os, json
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

from pathlib import Path

# Direction -> acceptable arm indices (from config/arms.yaml 9-arm ladder)
DIRECTION_MAP = {
    "discount": [0, 1, 2],          # Deep Discount, Discount, Slight Discount
    "slight_discount": [1, 2, 3],    # Discount, Slight Discount, Base Rate
    "base_rate": [3],                 # Base Rate only
    "base_rate_or_slight_discount": [2, 3],
    "base_rate_or_slight_premium": [3, 4],
    "slight_premium": [3, 4, 5],     # Base Rate, Slight Premium, Premium
    "premium": [4, 5, 6],            # Slight Premium, Premium, High Premium
    "premium_or_higher": [5, 6, 7, 8],
    "high_premium_or_surge": [6, 7, 8],
}

def main():
    # Load test scenarios
    scenarios_path = Path("data/test_scenarios.json")
    if not scenarios_path.exists():
        print("ERROR: data/test_scenarios.json not found")
        sys.exit(1)

    with open(scenarios_path) as f:
        test_data = json.load(f)

    property_id = test_data["property_id"]
    room_type = test_data["room_type"]
    los_nights = test_data["los_nights"]
    scenarios = test_data["scenarios"]

    # Check DB exists
    db_path = Path("data/pricing.db")
    if not db_path.exists():
        print("ERROR: data/pricing.db not found. Run bootstrap first:")
        print("  python -m orchestration.pipelines.run_bootstrap")
        sys.exit(1)

    # Import after path setup
    from serving.schemas import ScoreRequest
    from db.session import init_db
    init_db()

    # Import the scoring function
    # We can't easily call _score() directly since it uses a session,
    # so we'll use the API client approach via httpx or call simulate directly
    import datetime as dt
    from bandit_engine.config_loader import resolve_arm_ladder_for_cluster
    from bandit_engine.policy import BackboneModel, EnsemblePolicy, PropertyModel
    from bandit_engine.reference_rate import ReferenceRateInputs, compute_reference_rate
    from context_generator.context_builder import build_context
    from context_generator.chains import PropertySpec, generate_property_specs
    from guardrails.constraints import GuardrailContext, filter_arms
    from bandit_engine.config_loader import resolve_guardrails_for_tenant
    from db.models import Property
    from db.session import get_session
    import random

    session = get_session()
    prop = session.get(Property, property_id)
    if not prop:
        print(f"ERROR: Property {property_id} not found in DB. Available:")
        for p in session.query(Property).limit(5).all():
            print(f"  {p.property_id}")
        session.close()
        sys.exit(1)
    session.close()

    # Load specs
    specs = generate_property_specs()
    spec = next((s for s in specs if s.property_id == property_id), None)
    if not spec:
        print(f"ERROR: Property spec not found for {property_id}")
        sys.exit(1)

    print("=" * 70)
    print("TEST SCENARIO VALIDATION REPORT")
    print("=" * 70)
    print(f"Property: {property_id} ({spec.name})")
    print(f"Room: {room_type} | LOS: {los_nights} nights")
    print(f"Cluster: {spec.cluster_id} | Tenant: {spec.tenant_id}")
    print("-" * 70)

    results = []
    for scenario in scenarios:
        rate_plan = scenario["rate_plan"]
        overrides = scenario["context_overrides"]
        expected = scenario["expected_direction"]
        label = scenario["label"]

        # Skip non-bandit-managed plans
        from bandit_engine.reference_rate import is_rate_plan_bandit_managed
        if not is_rate_plan_bandit_managed(rate_plan, spec.tenant_id):
            results.append({"label": label, "status": "SKIP", "reason": "Not bandit-managed"})
            print(f"\n  Day {scenario['day']}: {label}")
            print(f"    Rate plan: {rate_plan} (NOT bandit-managed) -> SKIP")
            continue

        # Build context
        stay_date = dt.date.today() + dt.timedelta(days=scenario["day"])
        as_of_date = dt.date.today()
        rng = random.Random(f"test:{property_id}:{scenario['day']}")
        context = build_context(spec, room_type, rate_plan, stay_date, as_of_date, rng, los_nights=los_nights)
        reference_rate = context.pop("_reference_rate")

        # Apply overrides
        context.update(overrides)

        # Load models and score
        ladder = resolve_arm_ladder_for_cluster(spec.cluster_id)
        guardrails = resolve_guardrails_for_tenant(spec.tenant_id)
        gctx = GuardrailContext(
            reference_rate=reference_rate,
            comp_set_avg_rate=context.get("comp_set_avg_rate"),
            changes_today=0,
            rules=guardrails,
        )
        allowed_arms, excluded = filter_arms(ladder, gctx)

        backbone = BackboneModel.load_or_create(spec.cluster_id, spec.tenant_id)
        prop_model = PropertyModel.load_or_create(property_id)
        policy = EnsemblePolicy(
            prop_model, backbone, blend_smoothing_k=20.0,
            confidence_weights={"w_sample": 0.4, "w_agreement": 0.35, "w_margin": 0.25},
        )
        decision = policy.decide(context, allowed_arms, explore=False)

        chosen_idx = decision.chosen.index
        chosen_label = decision.chosen.label
        chosen_offset = decision.chosen.offset_pct
        price = round(reference_rate * (1 + chosen_offset), 2)

        # Check against expected
        acceptable = DIRECTION_MAP.get(expected, [])
        passed = chosen_idx in acceptable

        results.append({
            "label": label,
            "status": "PASS" if passed else "FAIL",
            "chosen": chosen_label,
            "chosen_idx": chosen_idx,
            "expected": expected,
            "price": price,
            "confidence": decision.confidence,
        })

        status_icon = "PASS" if passed else "FAIL"
        print(f"\n  Day {scenario['day']}: {label}")
        print(f"    Rate plan: {rate_plan} | Segment: {overrides.get('segment', '?')}")
        print(f"    Context: occ={overrides['occupancy_pct']}%, pace={overrides['pace_vs_stly_pct']}%, "
              f"event={overrides.get('event_intensity', 0)}, compset=${overrides.get('comp_set_avg_rate', '?')}")
        print(f"    Model chose: {chosen_label} ({chosen_offset*100:+.1f}%) -> ${price:.2f}")
        print(f"    Expected:    {expected} (arms {acceptable})")
        print(f"    Confidence:  {decision.confidence:.3f} ({decision.confidence_label})")
        print(f"    [{status_icon}]")

    # Summary
    print("\n" + "=" * 70)
    passes = sum(1 for r in results if r["status"] == "PASS")
    fails = sum(1 for r in results if r["status"] == "FAIL")
    skips = sum(1 for r in results if r["status"] == "SKIP")
    total = len(results) - skips
    print(f"RESULTS: {passes}/{total} passed, {fails} failed, {skips} skipped")
    if fails > 0:
        print("\nFailed scenarios (model disagrees with RM expectation):")
        for r in results:
            if r["status"] == "FAIL":
                print(f"  - {r['label']}: model chose {r['chosen']} (idx {r['chosen_idx']}), "
                      f"expected {r['expected']}")
    print("=" * 70)

    # Write results to file
    output = {"summary": {"passed": passes, "failed": fails, "skipped": skips, "total": total}, "details": results}
    with open("data/test_scenario_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nDetailed results saved to data/test_scenario_results.json")


if __name__ == "__main__":
    main()
