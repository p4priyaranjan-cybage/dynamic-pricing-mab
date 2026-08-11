"""Regression tests for the nightly pipeline's handling of real feedback.

Two bugs are guarded here:

1. The nightly retrain used to rebuild every PropertyModel from scratch via
   `bootstrap_properties()`, saving `n_observations = 0`. That discarded the
   online learning applied moments earlier by
   feedback/reward_reconciliation.py and reset the ensemble credibility weight
   `w = n / (n + k)` to zero every night, so no property ever graduated to
   self-reliance. Guarded by `property_model_exists` + `only_missing=True`.

2. The backbone retrain only ever read `is_historical=True` rows, so
   reconciled REAL outcomes never influenced the pooled model. Guarded by
   `build_examples_from_reconciled_rows`.
"""
import json

import pytest

from db.models import Decision
from bandit_engine.policy import PropertyModel
from bandit_engine.training.offline_eval import (
    MIN_LOGGED_PROPENSITY,
    build_examples_from_reconciled_rows,
)

LADDER = [
    {"index": 0, "label": "Deep Discount", "offset_pct": -0.225},
    {"index": 3, "label": "Base Rate", "offset_pct": 0.0},
    {"index": 5, "label": "Premium", "offset_pct": 0.15},
]

CONTEXT = {
    "occupancy_pct": 72.0,
    "pace_vs_stly_pct": 5.0,
    "event_intensity": 0.0,
    "event_flag": False,
    "our_rate_vs_compset_index": 1.0,
    "pickup_last_7d": 8.0,
    "segment": "transient",
}


def _reconciled_row(arm_index: int, true_reward: float, propensity: float = 0.4) -> Decision:
    return Decision(
        context_json=json.dumps(CONTEXT),
        arm_index=arm_index,
        arm_offset_pct=0.0,
        propensity=propensity,
        true_reward=true_reward,
        reference_rate=200.0,
        rate_plan="bar_best_available",
    )


# --------------------------------------------------------------------------- #
# Bug 2: reconciled real outcomes must become usable training examples
# --------------------------------------------------------------------------- #

def test_empty_input_yields_no_examples():
    assert build_examples_from_reconciled_rows([], LADDER) == []


def test_reconciled_row_maps_arm_index_to_ladder_position():
    # arm_index 5 sits at position 2 in LADDER (indices are 0, 3, 5)
    rows = [_reconciled_row(arm_index=5, true_reward=212.5)]
    examples = build_examples_from_reconciled_rows(rows, LADDER)

    assert len(examples) == 1
    assert examples[0]["chosen_pos"] == 2
    assert LADDER[examples[0]["chosen_pos"]]["index"] == 5


def test_reconciled_example_uses_logged_true_reward_verbatim():
    """No oracle, no imputation - the realized reward is the training signal."""
    rows = [_reconciled_row(arm_index=3, true_reward=187.25)]
    examples = build_examples_from_reconciled_rows(rows, LADDER)
    assert examples[0]["reward"] == pytest.approx(187.25)


def test_zero_reward_is_kept_as_a_real_signal_not_dropped():
    """A price that produced no booking is a genuine lesson, not missing data."""
    rows = [_reconciled_row(arm_index=3, true_reward=0.0)]
    examples = build_examples_from_reconciled_rows(rows, LADDER)
    assert len(examples) == 1
    assert examples[0]["reward"] == 0.0


def test_tiny_logged_propensity_is_clamped_to_bound_importance_weight():
    """VW applies an effective weight of 1/propensity. An unclamped near-zero
    propensity would let one lucky exploration row dominate the whole batch."""
    rows = [_reconciled_row(arm_index=3, true_reward=200.0, propensity=1e-6)]
    examples = build_examples_from_reconciled_rows(rows, LADDER)
    assert examples[0]["propensity"] == pytest.approx(MIN_LOGGED_PROPENSITY)
    assert 1.0 / examples[0]["propensity"] <= 20.0 + 1e-9


def test_healthy_propensity_is_left_untouched():
    rows = [_reconciled_row(arm_index=3, true_reward=200.0, propensity=0.4)]
    examples = build_examples_from_reconciled_rows(rows, LADDER)
    assert examples[0]["propensity"] == pytest.approx(0.4)


def test_row_whose_arm_is_absent_from_the_ladder_is_skipped():
    """If the arm ladder changed since the decision was logged, attributing the
    reward to a different arm would be worse than dropping the row."""
    rows = [_reconciled_row(arm_index=99, true_reward=200.0)]
    assert build_examples_from_reconciled_rows(rows, LADDER) == []


def test_malformed_context_json_is_skipped_rather_than_raising():
    row = _reconciled_row(arm_index=3, true_reward=200.0)
    row.context_json = "{not valid json"
    assert build_examples_from_reconciled_rows([row], LADDER) == []


def test_examples_carry_the_shape_learn_batch_expects():
    rows = [_reconciled_row(arm_index=3, true_reward=150.0)]
    example = build_examples_from_reconciled_rows(rows, LADDER)[0]
    assert set(example) == {"context", "arms", "chosen_pos", "propensity", "reward"}
    assert example["arms"] is LADDER
    assert example["context"]["segment"] == "transient"


# --------------------------------------------------------------------------- #
# Bug 1: nightly must not reset a property's earned trust
# --------------------------------------------------------------------------- #

@pytest.fixture
def isolated_model_dir(tmp_path, monkeypatch):
    """Point every MODEL_DIR reference at a temp dir.

    `train.py` does `from bandit_engine.policy import MODEL_DIR`, binding its
    own name, so both modules must be patched.
    """
    import bandit_engine.policy as policy_mod
    import bandit_engine.training.train as train_mod

    monkeypatch.setattr(policy_mod, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(train_mod, "MODEL_DIR", tmp_path)
    return tmp_path


def test_property_model_exists_is_false_before_any_save(isolated_model_dir):
    from bandit_engine.training.train import property_model_exists
    assert property_model_exists("never_seen_property") is False


def test_property_model_exists_becomes_true_after_save(isolated_model_dir):
    from bandit_engine.training.train import property_model_exists

    model = PropertyModel("prop_a")
    model.save()

    assert property_model_exists("prop_a") is True


def test_saved_observation_count_survives_a_reload(isolated_model_dir):
    """This is the value the nightly rebuild used to destroy. If it does not
    round-trip, the credibility weight w = n/(n+k) cannot accumulate."""
    model = PropertyModel("prop_b")
    for _ in range(7):
        model.learn(CONTEXT, LADDER, chosen_pos=1, propensity=0.4, reward=180.0)
    assert model.n_observations == 7
    model.save()

    reloaded = PropertyModel.load_or_create("prop_b")
    assert reloaded.n_observations == 7


def test_bootstrap_pretraining_does_not_inflate_earned_trust(isolated_model_dir):
    """Pretraining updates weights but must leave n_observations at zero, so a
    freshly bootstrapped property still defers to its cluster backbone."""
    model = PropertyModel("prop_c")
    for _ in range(30):
        model.learn(
            CONTEXT, LADDER, chosen_pos=1, propensity=0.33, reward=150.0,
            count_as_observation=False,
        )
    assert model.n_observations == 0


def test_a_fresh_model_would_wipe_earned_trust(isolated_model_dir):
    """Demonstrates the original bug directly: constructing PropertyModel(id)
    instead of load_or_create(id) and saving resets the counter to zero.
    `bootstrap_properties(only_missing=True)` exists to prevent the nightly
    pipeline from taking this path for an established property."""
    earned = PropertyModel("prop_d")
    for _ in range(12):
        earned.learn(CONTEXT, LADDER, chosen_pos=1, propensity=0.4, reward=200.0)
    earned.save()
    assert PropertyModel.load_or_create("prop_d").n_observations == 12

    # The old nightly behaviour, reproduced:
    PropertyModel("prop_d").save()
    assert PropertyModel.load_or_create("prop_d").n_observations == 0
