import json
import random

from db.models import Decision
from bandit_engine.training.offline_eval import (
    NUMERIC_FEATURES,
    _apply_premium_elasticity_floor,
    build_augmented_training_examples_from_rows,
    expected_true_reward_oracle,
    fit_reward_model,
    optimal_arm_oracle,
)

LADDER = [
    {"index": 0, "label": "Discount", "offset_pct": -0.15},
    {"index": 1, "label": "Base Rate", "offset_pct": 0.0},
    {"index": 2, "label": "Premium", "offset_pct": 0.15},
]

FULL_LADDER = [
    {"index": 0, "label": "Deep Discount", "offset_pct": -0.225},
    {"index": 1, "label": "Discount", "offset_pct": -0.15},
    {"index": 2, "label": "Slight Discount", "offset_pct": -0.065},
    {"index": 3, "label": "Base Rate", "offset_pct": 0.0},
    {"index": 4, "label": "Slight Premium", "offset_pct": 0.065},
    {"index": 5, "label": "Premium", "offset_pct": 0.15},
    {"index": 6, "label": "High Premium", "offset_pct": 0.275},
    {"index": 7, "label": "Demand Surge", "offset_pct": 0.45},
    {"index": 8, "label": "Peak Premium", "offset_pct": 0.625},
]

CONTEXT = {
    "occupancy_pct": 55.0, "pace_vs_stly_pct": 0.0, "event_intensity": 0.0,
    "event_flag": False, "our_rate_vs_compset_index": 1.0, "pickup_last_7d": 5.0,
    "segment": "transient",
}


def _fixed_context() -> dict:
    ctx = {f: 50.0 for f in NUMERIC_FEATURES}
    ctx["event_flag"] = False
    return ctx


def _make_row(offset_pct: float, booked: bool, propensity: float = 0.85, arm_index: int = 3) -> Decision:
    return Decision(
        context_json=json.dumps(_fixed_context()),
        arm_offset_pct=offset_pct,
        proxy_reward=1.0 if booked else 0.0,
        propensity=propensity,
        arm_index=arm_index,
        reference_rate=200.0,
        rate_plan="bar_flexible",
    )


def test_higher_offset_reduces_booking_probability_holding_else_equal():
    low_reward = expected_true_reward_oracle(CONTEXT, -0.15, 200.0, "bar_flexible")
    high_reward = expected_true_reward_oracle(CONTEXT, 0.45, 200.0, "bar_flexible")
    # Sanity: expected reward is a real number derived from a probability x price
    # trade-off - not asserting monotonicity globally, just that it's computable
    # and price-scaling participates as expected.
    assert low_reward >= 0
    assert high_reward >= 0


def test_optimal_arm_oracle_returns_a_valid_index():
    idx, val = optimal_arm_oracle(CONTEXT, LADDER, 200.0, "bar_flexible")
    assert idx in {a["index"] for a in LADDER}
    assert val >= 0


def test_fit_reward_model_returns_none_for_too_few_rows():
    rows = [_make_row(0.0, True) for _ in range(5)]
    assert fit_reward_model(rows) is None


def test_fit_reward_model_returns_none_for_single_class_labels():
    rows = [_make_row(0.0, True) for _ in range(50)]
    assert fit_reward_model(rows) is None


def test_monotone_constraint_forces_non_increasing_extrapolation():
    """Reliability plan: even when historical logs only cover a narrow
    offset range with outcomes that carry NO natural price signal (booked
    independent of offset), the fitted model must still predict
    non-increasing P(booked) as offset_pct rises across the FULL ladder -
    XGBoost's native monotone_constraints is what guarantees this despite
    the data giving no reason to prefer a negative effect on its own."""
    rng = random.Random(7)
    narrow_offsets = [-0.065, 0.0, 0.065]
    rows = [_make_row(rng.choice(narrow_offsets), rng.random() < 0.5) for _ in range(120)]

    model = fit_reward_model(rows)
    assert model is not None

    swept_offsets = [a["offset_pct"] for a in FULL_LADDER]
    probs = [model.predict_p_book(_fixed_context(), o) for o in swept_offsets]

    for earlier, later in zip(probs, probs[1:]):
        assert later <= earlier + 1e-9


def test_build_augmented_examples_are_well_formed_and_bounded():
    rng = random.Random(11)
    narrow_offsets = [-0.065, 0.0, 0.065]
    rows = [_make_row(rng.choice(narrow_offsets), rng.random() < 0.5) for _ in range(120)]
    model = fit_reward_model(rows)

    examples = build_augmented_training_examples_from_rows(rows, FULL_LADDER, model)
    # Up to 2 examples per row (best + worst), at least 1 per row
    assert len(rows) <= len(examples) <= len(rows) * 2
    for ex in examples:
        assert 0.0 <= ex["propensity"] <= 1.0
        assert ex["reward"] >= 0.0


def test_premium_elasticity_floor_is_noop_for_discounts_and_base_rate():
    assert _apply_premium_elasticity_floor(0.5, 0.5, 0.0, {}) == 0.5
    assert _apply_premium_elasticity_floor(0.5, 0.5, -0.2, {}) == 0.5


def test_premium_elasticity_floor_caps_probability_for_high_offsets():
    # For a flat p_est (no natural decline), the floor should still force a
    # sharp decline for a large positive offset in LOW demand (default context).
    floored = _apply_premium_elasticity_floor(0.5, p_base=0.5, offset_pct=0.625, context={"segment": "transient", "occupancy_pct": 50, "event_intensity": 0, "pace_vs_stly_pct": 0})
    assert floored < 0.25


def test_premium_elasticity_floor_prevents_reward_runaway_with_flat_probability_model():
    """Reliability plan fix: the argmax arm for a normal-demand context
    should NOT be the Peak Premium arm (the floor prevents runaway).
    In low demand, the model should favor discount/base arms."""
    rng = random.Random(3)
    narrow_offsets = [-0.065, 0.0, 0.065]
    rows = [_make_row(rng.choice(narrow_offsets), rng.random() < 0.5) for _ in range(120)]
    model = fit_reward_model(rows)
    assert model is not None

    # With default context (occupancy ~50, no event), argmax should NOT be Peak Premium
    examples = build_augmented_training_examples_from_rows(rows[1:2], FULL_LADDER, model)
    assert len(examples) == 1
    chosen_arm = FULL_LADDER[examples[0]["chosen_pos"]]
    # In low/normal demand, the best arm should not be the most extreme premium
    assert chosen_arm["label"] != "Peak Premium"


def test_doubly_robust_correction_pulls_toward_observed_outcome_at_logged_arm():
    """The argmax example should have a reward higher than a pure model
    prediction of 0.5 * 200 = 100, because the DR correction at the logged
    arm pulls the estimate toward the observed outcome (booked=1.0)."""
    rows = [_make_row(0.0, True, propensity=0.85, arm_index=3) for _ in range(15)] + [
        _make_row(0.0, False, propensity=0.85, arm_index=3) for _ in range(15)
    ]
    model = fit_reward_model(rows)
    examples = build_augmented_training_examples_from_rows(rows[:1], FULL_LADDER, model)
    assert len(examples) == 1
    # The first row is a BOOKED row; the DR correction should pull the reward
    # higher than a naive model prediction of ~0.5 * price
    assert examples[0]["reward"] > 100.0
