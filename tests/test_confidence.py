import random

from bandit_engine.policy import BackboneModel, EnsemblePolicy, PropertyModel

LADDER = [
    {"index": 0, "label": "Discount", "offset_pct": -0.1},
    {"index": 1, "label": "Base Rate", "offset_pct": 0.0},
    {"index": 2, "label": "Premium", "offset_pct": 0.1},
]

CONTEXT = {
    "occupancy_pct": 55.0, "adr_trend_pct": 0.0, "pace_vs_stly_pct": 0.0,
    "pickup_last_7d": 5.0, "remaining_inventory_pct": 40.0,
    "our_rate_vs_compset_index": 1.0, "compset_rate_trend_pct": 0.0,
    "compset_dispersion": 0.05, "event_intensity": 0.0, "event_flag": False,
    "segment": "transient",
}


def _fresh_policy():
    backbone = BackboneModel("test_cluster", "test_tenant", n_members=2)
    prop_model = PropertyModel("test_property")
    return EnsemblePolicy(
        prop_model, backbone, blend_smoothing_k=20.0,
        confidence_weights={"w_sample": 0.4, "w_agreement": 0.35, "w_margin": 0.25},
    )


def test_confidence_is_bounded_and_labeled():
    policy = _fresh_policy()
    decision = policy.decide(CONTEXT, LADDER, seed=1)
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.confidence_label in ("Low", "Medium", "High")


def test_confidence_sample_component_increases_with_more_property_observations():
    policy = _fresh_policy()
    d1 = policy.decide(CONTEXT, LADDER, seed=1)
    for _ in range(50):
        policy.record_feedback(CONTEXT, LADDER, chosen_pos=1, propensity=0.5, reward=1.0)
    d2 = policy.decide(CONTEXT, LADDER, seed=1)
    assert d2.confidence_breakdown["sample"] > d1.confidence_breakdown["sample"]


def test_blend_weight_zero_k_means_full_property_independence():
    backbone = BackboneModel("test_cluster", "test_tenant", n_members=2)
    prop_model = PropertyModel("test_property_2")
    policy = EnsemblePolicy(prop_model, backbone, blend_smoothing_k=0.0001,
                             confidence_weights={"w_sample": 0.4, "w_agreement": 0.35, "w_margin": 0.25})
    policy.record_feedback(CONTEXT, LADDER, chosen_pos=1, propensity=0.5, reward=1.0)
    decision = policy.decide(CONTEXT, LADDER, seed=1)
    assert decision.blend_weight > 0.99
