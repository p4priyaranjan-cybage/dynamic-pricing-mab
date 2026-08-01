"""Config loading with the `extends` deep-merge override mechanism.

Resolution order used throughout the plan: Property > Region > Brand >
Chain > Global defaults (child wins on conflict). This module implements
the generic deep-merge primitive plus convenience loaders for the specific
config files under config/.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` on top of `base`. `override` wins on conflicts."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_tenant_config(tenant_id: str) -> dict:
    """Load a tenant config file, resolving its `extends` chain (deep-merged)."""
    path = CONFIG_DIR / "tenants" / f"{tenant_id}.yaml"
    config = _load_yaml(path)
    extends = config.pop("extends", None)
    if extends:
        parent = _load_yaml(CONFIG_DIR / "tenants" / f"{extends}.yaml")
        config = deep_merge(parent, config)
    return config


def list_tenant_ids() -> list[str]:
    tenants_dir = CONFIG_DIR / "tenants"
    return sorted(
        p.stem for p in tenants_dir.glob("*.yaml") if not p.stem.startswith("_")
    )


def load_arms_config() -> dict:
    return _load_yaml(CONFIG_DIR / "arms.yaml")


def load_clusters_config() -> dict:
    return _load_yaml(CONFIG_DIR / "clusters.yaml")


def load_context_schema() -> dict:
    return _load_yaml(CONFIG_DIR / "context_schema.yaml")


def load_global_guardrails() -> dict:
    return _load_yaml(CONFIG_DIR / "guardrails.yaml")


def resolve_guardrails_for_tenant(tenant_id: str) -> dict:
    """Global guardrails deep-merged with the tenant's `guardrails` overrides."""
    global_rules = load_global_guardrails()
    tenant_config = load_tenant_config(tenant_id)
    tenant_overrides = tenant_config.get("guardrails", {}) or {}
    return deep_merge(global_rules, tenant_overrides)


def resolve_arm_ladder_for_cluster(cluster_id: str) -> list[dict]:
    """Default ladder scaled by the cluster's elasticity_spread factor."""
    arms_cfg = load_arms_config()
    clusters_cfg = load_clusters_config()
    ladder = copy.deepcopy(arms_cfg["default_ladder"])

    spread = 1.0
    for cluster in clusters_cfg.get("clusters", []):
        if cluster["id"] == cluster_id:
            spread = cluster.get("elasticity_spread", 1.0)
            break
    override = arms_cfg.get("cluster_overrides", {}).get(cluster_id)
    if override:
        spread = override.get("elasticity_spread", spread)

    if spread != 1.0:
        for arm in ladder:
            arm["offset_pct"] = round(arm["offset_pct"] * spread, 4)
    return ladder


def resolve_scoring_mode(tenant_id: str) -> str:
    """Resolve the scoring mode for a tenant: 'bandit', 'baseline', or 'shadow'.

    - 'bandit': normal MAB scoring (default)
    - 'baseline': kill-switch/fallback - always return Base Rate arm
    - 'shadow': score both bandit and baseline, log both, publish baseline only

    Can be overridden per-tenant in config/tenants/*.yaml. This is the
    one-click escape hatch for revenue managers - see docs/ARCHITECTURE.md
    "Kill-Switch / Fallback Mode".
    """
    tenant_config = load_tenant_config(tenant_id)
    mode = tenant_config.get("scoring_mode", "bandit")
    if mode not in ("bandit", "baseline", "shadow"):
        return "bandit"
    return mode
