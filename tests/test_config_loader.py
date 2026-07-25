from bandit_engine.config_loader import (
    deep_merge,
    list_tenant_ids,
    load_tenant_config,
    resolve_arm_ladder_for_cluster,
    resolve_guardrails_for_tenant,
)


def test_deep_merge_child_wins():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    override = {"a": 2, "nested": {"y": 99}}
    result = deep_merge(base, override)
    assert result == {"a": 2, "nested": {"x": 1, "y": 99}}


def test_list_tenant_ids_excludes_defaults():
    ids = list_tenant_ids()
    assert "_defaults" not in ids
    assert "marriott" in ids
    assert "hyatt" in ids


def test_tenant_config_resolves_extends():
    cfg = load_tenant_config("marriott")
    assert "room_types" in cfg
    assert "rate_plans" in cfg
    assert cfg["chain"] == "Marriott"


def test_resolve_guardrails_for_tenant_has_price_bounds():
    rules = resolve_guardrails_for_tenant("marriott")
    assert "price_bounds" in rules


def test_resolve_arm_ladder_returns_nine_arms():
    ladder = resolve_arm_ladder_for_cluster("nyc_midscale_urban")
    assert len(ladder) == 9
    offsets = [a["offset_pct"] for a in ladder]
    assert offsets == sorted(offsets)
