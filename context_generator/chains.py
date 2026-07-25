"""Expands config/tenants/*.yaml into concrete synthetic property instances.

The YAML config defines the org TEMPLATE (chain -> brand -> region ->
property_count); this module instantiates the actual property_id/name/
base_bar values so onboarding stays config-driven (add a region block, not
one hand-written property per hotel).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from bandit_engine.config_loader import list_tenant_ids, load_tenant_config

# (min, max) nightly BAR by market tier, used to seed each property's base rate.
_BASE_BAR_RANGE = {
    "luxury": (260.0, 420.0),
    "midscale": (140.0, 220.0),
}


@dataclass
class PropertySpec:
    property_id: str
    name: str
    tenant_id: str
    chain: str
    brand: str
    region: str
    market_tier: str
    cluster_id: str
    base_bar: float
    room_types: list[dict]
    rate_plans: list[dict]


def generate_property_specs(seed: int = 42) -> list[PropertySpec]:
    rng = random.Random(seed)
    specs: list[PropertySpec] = []
    for tenant_id in list_tenant_ids():
        cfg = load_tenant_config(tenant_id)
        chain = cfg["chain"]
        for brand in cfg["brands"]:
            brand_id = brand["id"]
            market_tier = brand["market_tier"]
            bar_lo, bar_hi = _BASE_BAR_RANGE.get(market_tier, (150.0, 250.0))
            for region_cfg in brand["regions"]:
                region = region_cfg["region"]
                cluster_id = region_cfg["cluster_id"]
                count = region_cfg["property_count"]
                for i in range(1, count + 1):
                    property_id = f"{tenant_id}_{brand_id}_{region.lower()}_{i:02d}"
                    name = f"{chain} {brand_id.replace('_', ' ').title()} {region} {i}"
                    base_bar = round(rng.uniform(bar_lo, bar_hi), 2)
                    specs.append(
                        PropertySpec(
                            property_id=property_id,
                            name=name,
                            tenant_id=tenant_id,
                            chain=chain,
                            brand=brand_id,
                            region=region,
                            market_tier=market_tier,
                            cluster_id=cluster_id,
                            base_bar=base_bar,
                            room_types=cfg["room_types"],
                            rate_plans=cfg["rate_plans"],
                        )
                    )
    return specs
