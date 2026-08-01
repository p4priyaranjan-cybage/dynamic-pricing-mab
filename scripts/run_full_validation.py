"""Full validation: bootstrap (generate data + train) then run backtest suite."""
import sys, os, time, traceback
os.chdir(r"C:\hackathon\dynamic-pricing-MAB")
sys.path.insert(0, r"C:\hackathon\dynamic-pricing-MAB")

OUTFILE = r"C:\hackathon\dynamic-pricing-MAB\validation_full_result.txt"
output = []

def save():
    with open(OUTFILE, "w") as f:
        f.write("\n".join(output))

try:
    output.append("Starting imports...")
    save()
    
    from orchestration.pipelines.run_bootstrap import main as bootstrap_main
    output.append("Imports OK")
    save()

    # Step 1: Bootstrap
    output.append("")
    output.append("=" * 60)
    output.append("STEP 1: BOOTSTRAP (data generation + model training)")
    output.append("=" * 60)
    save()
    
    t0 = time.time()
    result = bootstrap_main()
    elapsed = time.time() - t0
    output.append(f"  Completed in {elapsed:.1f}s")
    output.append(f"  Properties: {result['data_generation']['properties']}")
    output.append(f"  Historical rows: {result['data_generation']['historical_decision_rows']}")
    output.append(f"  Backbones trained: {len(result['training']['backbones'])}")
    for bb in result['training']['backbones']:
        output.append(f"    {bb['cluster_id']}|{bb['tenant_id']}: "
                      f"AUC={bb.get('reward_model_auc')}, reliable={bb.get('reward_model_reliable')}, "
                      f"rows={bb['n_historical_rows']}, examples={bb['n_examples']}")
    save()

    # Step 2: Backtest
    output.append("")
    output.append("=" * 60)
    output.append("STEP 2: BACKTEST SUITE")
    output.append("=" * 60)
    save()
    
    from bandit_engine.training.offline_eval import run_backtest_suite
    from db.models import Property
    from db.session import get_session
    import random

    session = get_session()
    all_ids = [p.property_id for p in session.query(Property).all()]
    session.close()

    rng = random.Random(99)
    sample_ids = rng.sample(all_ids, min(6, len(all_ids)))
    output.append(f"  Testing {len(sample_ids)} properties: {sample_ids}")
    save()

    t0 = time.time()
    suite = run_backtest_suite(sample_ids, n_rounds=150)
    elapsed = time.time() - t0
    output.append(f"  Completed in {elapsed:.1f}s")
    output.append(f"  Mean diff: {suite.mean_reward_diff:.1f}")
    output.append(f"  CI: [{suite.ci_low:.1f}, {suite.ci_high:.1f}]")
    output.append(f"  Wins: {suite.n_wins}/{suite.n_properties}")
    output.append(f"  reliably_beats_baseline: {suite.reliably_beats_baseline}")
    output.append("")
    for p in suite.per_property:
        output.append(f"    {p['property_id']}: diff={p['diff']:.1f} {'WIN' if p['bandit_wins'] else 'LOSS'}")
    save()

    # Step 3: Versioning check
    output.append("")
    output.append("=" * 60)
    output.append("STEP 3: MODEL VERSIONING")
    output.append("=" * 60)
    from pathlib import Path
    from model_registry.versioning import sorted_versions, get_current_version_dir
    backbone_dir = Path(r"C:\hackathon\dynamic-pricing-MAB\model_registry\artifacts\backbone")
    if backbone_dir.exists():
        for d in sorted(backbone_dir.iterdir()):
            if d.is_dir():
                versions = sorted_versions(d)
                current = get_current_version_dir(d)
                cname = current.name if current and current != d else "legacy"
                output.append(f"  {d.name}: {len(versions)} version(s), current={cname}")
    save()

    output.append("")
    output.append("VALIDATION COMPLETE")
    save()

except Exception as e:
    output.append(f"\nERROR: {e}")
    output.append(traceback.format_exc())
    save()
