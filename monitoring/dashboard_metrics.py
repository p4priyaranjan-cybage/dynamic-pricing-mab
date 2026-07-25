"""Aggregate metrics for the Monitoring dashboard tab: arm distribution,
override rate, guardrail-violation rate, and a simple Market Parity Index
(MPI) style fair-share indicator across properties within a cluster."""
from __future__ import annotations

from collections import Counter

from db.models import Decision
from db.session import get_session


def arm_distribution(cluster_id: str | None = None, tenant_id: str | None = None) -> dict:
    session = get_session()
    try:
        q = session.query(Decision).filter(Decision.is_historical.is_(False), Decision.is_dry_run.is_(False))
        if cluster_id:
            q = q.filter(Decision.cluster_id == cluster_id)
        if tenant_id:
            q = q.filter(Decision.tenant_id == tenant_id)
        rows = q.all()
        counts = Counter(r.arm_label for r in rows)
        total = sum(counts.values()) or 1
        return {label: round(n / total, 4) for label, n in counts.items()}
    finally:
        session.close()


def override_rate(cluster_id: str | None = None) -> float:
    session = get_session()
    try:
        q = session.query(Decision).filter(Decision.is_historical.is_(False), Decision.is_dry_run.is_(False))
        if cluster_id:
            q = q.filter(Decision.cluster_id == cluster_id)
        rows = q.all()
        if not rows:
            return 0.0
        overridden = sum(1 for r in rows if r.override_price is not None)
        return round(overridden / len(rows), 4)
    finally:
        session.close()


def approval_stats(cluster_id: str | None = None) -> dict:
    session = get_session()
    try:
        q = session.query(Decision).filter(Decision.is_historical.is_(False), Decision.is_dry_run.is_(False))
        if cluster_id:
            q = q.filter(Decision.cluster_id == cluster_id)
        rows = q.all()
        counts = Counter(r.status for r in rows)
        return dict(counts)
    finally:
        session.close()


def average_confidence(cluster_id: str | None = None) -> float:
    session = get_session()
    try:
        q = session.query(Decision).filter(Decision.is_historical.is_(False), Decision.is_dry_run.is_(False))
        if cluster_id:
            q = q.filter(Decision.cluster_id == cluster_id)
        rows = q.all()
        if not rows:
            return 0.0
        return round(sum(r.confidence_score for r in rows) / len(rows), 4)
    finally:
        session.close()
