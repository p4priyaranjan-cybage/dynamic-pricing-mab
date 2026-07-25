from bandit_engine.reference_rate import ReferenceRateInputs, compute_reference_rate, is_rate_plan_bandit_managed


def test_reference_rate_scales_with_room_type_multiplier():
    base_inputs = ReferenceRateInputs(base_bar=200.0, room_type="standard", rate_plan="bar_flexible", los_bucket="1")
    deluxe_inputs = ReferenceRateInputs(base_bar=200.0, room_type="deluxe", rate_plan="bar_flexible", los_bucket="1")
    base_rate = compute_reference_rate(base_inputs, tenant_id="marriott")
    deluxe_rate = compute_reference_rate(deluxe_inputs, tenant_id="marriott")
    assert deluxe_rate > base_rate


def test_reference_rate_decreases_with_longer_los():
    short = ReferenceRateInputs(base_bar=200.0, room_type="standard", rate_plan="bar_flexible", los_bucket="1")
    long = ReferenceRateInputs(base_bar=200.0, room_type="standard", rate_plan="bar_flexible", los_bucket="9+")
    assert compute_reference_rate(long, tenant_id="marriott") <= compute_reference_rate(short, tenant_id="marriott")


def test_corporate_negotiated_not_bandit_managed():
    assert is_rate_plan_bandit_managed("corporate_negotiated", "marriott") is False
    assert is_rate_plan_bandit_managed("bar_flexible", "marriott") is True
