"""Thin filesystem-based model registry - wraps the paths that
BackboneModel/PropertyModel already save/load from (bandit_engine/policy.py
MODEL_DIR), just exposing a listing/inspection API for the dashboard and
API layer without duplicating VW load/save logic."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from bandit_engine.policy import MODEL_DIR


def list_backbones() -> list[dict]:
    root = MODEL_DIR / "backbone"
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        tenant_id, _, cluster_id = d.name.partition("__")
        members = sorted(d.glob("member_*.vw"))
        mtime = max((f.stat().st_mtime for f in members), default=None)
        out.append(
            {
                "tenant_id": tenant_id,
                "cluster_id": cluster_id,
                "n_members": len(members),
                "last_trained_at": dt.datetime.utcfromtimestamp(mtime).isoformat() if mtime else None,
            }
        )
    return out


def list_property_models() -> list[dict]:
    root = MODEL_DIR / "property"
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        model_file = d / "model.vw"
        if not model_file.exists():
            continue
        n_obs_file = d / "n_observations.txt"
        n_obs = int(n_obs_file.read_text().strip() or 0) if n_obs_file.exists() else 0
        out.append(
            {
                "property_id": d.name,
                "n_observations": n_obs,
                "last_trained_at": dt.datetime.utcfromtimestamp(model_file.stat().st_mtime).isoformat(),
            }
        )
    return out
