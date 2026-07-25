"""Thin HTTP client wrapping the FastAPI serving layer - the dashboard never
touches the DB or bandit engine directly (API-first design, see
docs/ARCHITECTURE.md)."""
from __future__ import annotations

import os

import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")


def get_properties() -> list[dict]:
    return httpx.get(f"{API_BASE_URL}/properties", timeout=30).json()


def get_property_config(property_id: str) -> dict:
    return httpx.get(f"{API_BASE_URL}/properties/{property_id}/config", timeout=30).json()


def get_rate_calendar(**params) -> list[dict]:
    params = {k: v for k, v in params.items() if v not in (None, "")}
    return httpx.get(f"{API_BASE_URL}/rate-calendar", params=params, timeout=30).json()


def get_approval_queue(property_id: str | None = None) -> list[dict]:
    params = {"property_id": property_id} if property_id else {}
    return httpx.get(f"{API_BASE_URL}/approval-queue", params=params, timeout=30).json()


def approve_decision(decision_id: str, approved_by: str) -> dict:
    return httpx.post(f"{API_BASE_URL}/approval-queue/{decision_id}/approve", json={"approved_by": approved_by}, timeout=30).json()


def reject_decision(decision_id: str, approved_by: str) -> dict:
    return httpx.post(f"{API_BASE_URL}/approval-queue/{decision_id}/reject", json={"approved_by": approved_by}, timeout=30).json()


def override_decision(decision_id: str, approved_by: str, override_price: float) -> dict:
    return httpx.post(
        f"{API_BASE_URL}/approval-queue/{decision_id}/override",
        json={"approved_by": approved_by, "override_price": override_price},
        timeout=30,
    ).json()


def get_metrics(cluster_id: str | None = None, tenant_id: str | None = None) -> dict:
    params = {k: v for k, v in {"cluster_id": cluster_id, "tenant_id": tenant_id}.items() if v}
    return httpx.get(f"{API_BASE_URL}/metrics", params=params, timeout=30).json()


def get_recommendations(
    property_id: str,
    room_type: str,
    rate_plan: str,
    start_date: str,
    end_date: str,
    los_nights: int = 2,
    context_overrides: dict | None = None,
) -> list[dict]:
    """On-demand recommendations for a property across a date range (daily =
    1 day, weekly = 7 days, monthly = 30 days - caller computes start/end).
    Always a side-effect-free preview (persist=false) - same explainability
    payload per day as /score/simulate. `context_overrides` (same allowed
    keys as Scenario Simulator's what-if panel) is applied identically to
    every day in the range. POST (not GET) because context_overrides is a
    nested dict - longer ranges (e.g. monthly) score one day at a time
    server-side, so use a generous timeout."""
    payload = {
        "property_id": property_id,
        "room_type": room_type,
        "rate_plan": rate_plan,
        "start_date": start_date,
        "end_date": end_date,
        "los_nights": los_nights,
    }
    if context_overrides:
        payload["context_overrides"] = context_overrides
    resp = httpx.post(f"{API_BASE_URL}/recommendations", json=payload, timeout=90)
    resp.raise_for_status()
    return resp.json()


def score(
    property_id: str,
    room_type: str,
    rate_plan: str,
    stay_date: str,
    dry_run: bool = False,
    los_nights: int = 2,
    context_overrides: dict | None = None,
) -> dict:
    payload = {
        "property_id": property_id,
        "room_type": room_type,
        "rate_plan": rate_plan,
        "stay_date": stay_date,
        "dry_run": dry_run,
        "los_nights": los_nights,
    }
    if context_overrides:
        payload["context_overrides"] = context_overrides
    endpoint = "simulate" if dry_run else "score"
    resp = httpx.post(f"{API_BASE_URL}/{endpoint}", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()
