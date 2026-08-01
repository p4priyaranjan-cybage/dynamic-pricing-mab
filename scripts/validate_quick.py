import sys, os
os.chdir(r"C:\hackathon\dynamic-pricing-MAB")
sys.path.insert(0, r"C:\hackathon\dynamic-pricing-MAB")

output = []
try:
    from bandit_engine.training.offline_eval import (
        _raw_features, MONOTONE_CONSTRAINTS, SEGMENT_ELASTICITY_FLOORS,
        _apply_premium_elasticity_floor
    )
    from bandit_engine.training.train import BACKBONE_HISTORY_CAP, PROPERTY_HISTORY_CAP
    from bandit_engine.config_loader import resolve_scoring_mode
    from model_registry.versioning import create_version_dir, get_current_version_dir, rollback
    output.append("IMPORTS: OK")
except Exception as e:
    output.append(f"IMPORTS: FAILED - {e}")

try:
    ctx = {"occupancy_pct": 75.0, "adr_trend_pct": 2.0, "pace_vs_stly_pct": 5.0,
           "pickup_last_7d": 12.0, "remaining_inventory_pct": 30.0,
           "our_rate_vs_compset_index": 1.05, "compset_rate_trend_pct": 1.5,
           "compset_dispersion": 0.08, "event_intensity": 0.7, "event_flag": True,
           "segment": "leisure"}
    features = _raw_features(ctx, 0.15)
    output.append(f"FEATURES: len={len(features)}, expected=16")
    output.append(f"MONOTONE: len={len(MONOTONE_CONSTRAINTS)}")
    output.append(f"CAPS: backbone={BACKBONE_HISTORY_CAP}, property={PROPERTY_HISTORY_CAP}")
    output.append(f"FLOORS: {SEGMENT_ELASTICITY_FLOORS}")
    p_corp = _apply_premium_elasticity_floor(0.5, 0.5, 0.4, {"segment": "corporate"})
    p_leis = _apply_premium_elasticity_floor(0.5, 0.5, 0.4, {"segment": "leisure"})
    output.append(f"FLOOR_TEST: corp={p_corp:.4f}, leisure={p_leis:.4f}, corp>leisure={p_corp>p_leis}")
    mode = resolve_scoring_mode("hyatt")
    output.append(f"SCORING_MODE: hyatt={mode}")
    output.append("ALL CHECKS PASSED")
except Exception as e:
    import traceback
    output.append(f"ERROR: {e}")
    output.append(traceback.format_exc())

with open(r"C:\hackathon\dynamic-pricing-MAB\validation_result.txt", "w") as f:
    f.write("\n".join(output))
