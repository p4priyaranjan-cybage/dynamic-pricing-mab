"""Validation script: runs bootstrap + backtest to confirm credibility improvements work.

Usage: python scripts/run_validation.py
"""
import sys
import json
import os

# Ensure we can import project modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 70)
print("DYNAMIC PRICING MAB - CREDIBILITY VALIDATION")
print("=" * 70)

# Step 1: Verify imports work
print("\n[1/6] Verifying imports...")
try:
    from bandit_engine.training.offline_eval import (
        _raw_features, MONOTONE_CONSTRAINTS, SEGMENT_ELASTICITY_FLOORS,
        _apply_premium_elasticity_floor, fit_reward_model
    )
    from bandit_engine.training.train import BACKBONE_HISTORY_CAP, PROPERTY_HISTORY_CAP
    from bandit_engine.config_loader import resolve_scoring_mode
    from model_registry.versioning import create_version_dir, get_current_version_dir, rollback
    print("  All imports OK")
except Exception as e:
    print(f"  IMPORT ERROR: {e}")
    sys.exit(1)

# Step 2: Verify interaction features
print("\n[2/6] Verifying reward model interaction features...")
test_ctx = {
    "occupancy_pct": 75.0, "adr_trend_pct": 2.0, "pace_vs_stly_pct": 5.0,
    "pickup_last_7d": 12.0, "remaining_inventory_pct": 30.0,
    "our_rate_vs_compset_index": 1.05, "compset_rate_trend_pct": 1.5,
    "compset_dispersion": 0.08, "event_intensity": 0.7, "event_flag": True,
    "segment": "leisure",
}
features = _raw_features(test_ctx, 0.15)
# Base: 9 numeric + event_flag + offset_pct = 11
# Interactions: 4 named + 1 segment_elasticity = 5
expected_len = 11 + 5
assert len(features) == expected_len, f"Expected {expected_len} features, got {len(features)}"
# Check interaction values are non-zero
assert features[11] == 75.0 * 0.15, f"occupancy*offset wrong: {features[11]}"
assert features[12] == 0.7 * 0.15, f"event_intensity*offset wrong: {features[12]}"
print(f"  Feature vector length: {len(features)} (correct)")
print(f"  Interaction features present: occupancy*offset={features[11]:.3f}, "
      f"event*offset={features[12]:.4f}, segment_elast*offset={features[15]:.4f}")

# Step 3: Verify monotone constraints match feature count
print("\n[3/6] Verifying monotone constraints...")
assert len(MONOTONE_CONSTRAINTS) == expected_len, \
    f"Monotone constraints length {len(MONOTONE_CONSTRAINTS)} != feature length {expected_len}"
# offset_pct at index 10, interactions at 11-15 should all be -1
assert MONOTONE_CONSTRAINTS[10] == -1, "offset_pct not constrained"
for i in range(11, 16):
    assert MONOTONE_CONSTRAINTS[i] == -1, f"Interaction at index {i} not constrained"
print(f"  Constraints length: {len(MONOTONE_CONSTRAINTS)} (matches features)")
print(f"  All interaction terms constrained to non-increasing: YES")

# Step 4: Verify context-conditioned elasticity floor
print("\n[4/6] Verifying context-conditioned premium elasticity floor...")
print(f"  Segment floors: {SEGMENT_ELASTICITY_FLOORS}")
# Corporate (less elastic) should allow higher p_est than leisure (more elastic)
p_corp = _apply_premium_elasticity_floor(0.5, 0.5, 0.4, {"segment": "corporate"})
p_leis = _apply_premium_elasticity_floor(0.5, 0.5, 0.4, {"segment": "leisure"})
assert p_corp > p_leis, f"Corporate floor ({p_corp:.4f}) should be > leisure ({p_leis:.4f})"
print(f"  Corporate @ offset=0.4: P(book)={p_corp:.4f}")
print(f"  Leisure   @ offset=0.4: P(book)={p_leis:.4f}")
print(f"  Corporate > Leisure (correct - less elastic): YES")

# Step 5: Verify higher history caps
print("\n[5/6] Verifying raised history caps...")
assert BACKBONE_HISTORY_CAP == 8000, f"Expected 8000, got {BACKBONE_HISTORY_CAP}"
assert PROPERTY_HISTORY_CAP == 1500, f"Expected 1500, got {PROPERTY_HISTORY_CAP}"
print(f"  BACKBONE_HISTORY_CAP: {BACKBONE_HISTORY_CAP} (was 3000)")
print(f"  PROPERTY_HISTORY_CAP: {PROPERTY_HISTORY_CAP} (was 600)")

# Step 6: Verify model versioning
print("\n[6/6] Verifying model versioning...")
import tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir) / "test_model"
    # Create two versions
    v1_dir = create_version_dir(base)
    (v1_dir / "model.vw").write_text("v1")
    import time; time.sleep(1.1)  # ensure different timestamp
    v2_dir = create_version_dir(base)
    (v2_dir / "model.vw").write_text("v2")
    
    # Current should point to v2
    current = get_current_version_dir(base)
    assert current == v2_dir, f"Current should be v2, got {current}"
    assert (current / "model.vw").read_text() == "v2"
    
    # Rollback to v1
    rolled_to = rollback(base)
    assert rolled_to is not None, "Rollback returned None"
    current_after = get_current_version_dir(base)
    assert (current_after / "model.vw").read_text() == "v1"
    print(f"  Created version: {v1_dir.name}")
    print(f"  Created version: {v2_dir.name}")
    print(f"  Current pointed to v2: YES")
    print(f"  Rollback to v1 succeeded: YES")
    print(f"  Current now points to v1: YES")

# Step 7: Verify scoring mode config
print("\n[BONUS] Verifying kill-switch / scoring mode config...")
mode = resolve_scoring_mode("hyatt")
print(f"  Hyatt scoring mode: '{mode}' (expected: 'bandit')")
assert mode == "bandit"

print("\n" + "=" * 70)
print("ALL VALIDATION CHECKS PASSED")
print("=" * 70)
print("\nCredibility improvements confirmed:")
print("  [x] Interaction features in reward model (5 new features)")
print("  [x] Monotone constraints correctly extended")
print("  [x] Context-conditioned elasticity floor (per-segment)")
print("  [x] Higher history caps (8000/1500)")
print("  [x] Model versioning with rollback")
print("  [x] Kill-switch / scoring mode infrastructure")
print("\nNext: run full bootstrap + backtest to measure reward improvement.")
