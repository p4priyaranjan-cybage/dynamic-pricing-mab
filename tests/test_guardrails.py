from guardrails.constraints import GuardrailContext, filter_arms, requires_approval

LADDER = [
    {"index": 0, "label": "Deep Discount", "offset_pct": -0.225},
    {"index": 3, "label": "Base Rate", "offset_pct": 0.0},
    {"index": 8, "label": "Peak Premium", "offset_pct": 0.625},
]


def test_price_bounds_excludes_out_of_range_arms():
    ctx = GuardrailContext(
        reference_rate=200.0, comp_set_avg_rate=None, changes_today=0,
        rules={"price_bounds": {"min_offset_pct": -0.2, "max_offset_pct": 0.5}},
    )
    allowed, excluded = filter_arms(LADDER, ctx)
    allowed_indices = {a["index"] for a in allowed}
    assert 0 not in allowed_indices  # -0.225 below -0.2
    assert 3 in allowed_indices


def test_never_returns_zero_feasible_arms():
    ctx = GuardrailContext(
        reference_rate=200.0, comp_set_avg_rate=100.0, changes_today=0,
        rules={"competitive_positioning": {"enabled": True, "min_index_vs_compset": 0.1, "max_index_vs_compset": 0.2}},
    )
    allowed, _ = filter_arms(LADDER, ctx)
    assert len(allowed) >= 1


def test_requires_approval_on_large_delta_or_low_confidence():
    rules = {"approval": {"auto_publish_delta_threshold_pct": 0.05, "require_approval_if_confidence_below": 0.5}}
    assert requires_approval(price_delta_pct=0.10, confidence=0.9, rules=rules) is True
    assert requires_approval(price_delta_pct=0.01, confidence=0.2, rules=rules) is True
    assert requires_approval(price_delta_pct=0.01, confidence=0.9, rules=rules) is False
