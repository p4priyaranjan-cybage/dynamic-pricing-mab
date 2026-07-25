"""SQLAlchemy ORM models.

Schema notes:
  - `schema_version` on Property/DailyContext/Decision follows the
    version-skew tolerance design (docs/ARCHITECTURE.md): additive-only
    changes within a major version, consumers dispatch on this field.
  - The "Recommended Rate Calendar" is NOT a separate materialized table in
    this POC - it's a query over Decision (latest non-superseded row per
    property/room_type/rate_plan/stay_date). See serving/api.py
    `rate_calendar` endpoint. A production system would likely materialize
    it for performance at scale.
  - Decision doubles as both the live decision log AND the synthetic
    historical bootstrap data (`is_historical=True`), since both share the
    same (context, arm, reward) shape - see context_generator/
    multi_chain_synthetic_data.py.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


class Property(Base):
    __tablename__ = "properties"

    property_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    chain: Mapped[str] = mapped_column(String(64))
    brand: Mapped[str] = mapped_column(String(64))
    region: Mapped[str] = mapped_column(String(32), index=True)
    market_tier: Mapped[str] = mapped_column(String(32))
    cluster_id: Mapped[str] = mapped_column(String(64), index=True)
    base_bar: Mapped[float] = mapped_column(Float, default=180.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class RoomType(Base):
    __tablename__ = "room_types"
    __table_args__ = (UniqueConstraint("property_id", "code", name="uq_room_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    property_id: Mapped[str] = mapped_column(String(64), ForeignKey("properties.property_id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    multiplier: Mapped[float] = mapped_column(Float)


class RatePlan(Base):
    __tablename__ = "rate_plans"
    __table_args__ = (UniqueConstraint("property_id", "code", name="uq_rate_plan"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    property_id: Mapped[str] = mapped_column(String(64), ForeignKey("properties.property_id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    offset_multiplier: Mapped[float] = mapped_column(Float)
    bandit_managed: Mapped[bool] = mapped_column(Boolean, default=True)


class DailyContext(Base):
    """DEPRECATED / unused: superseded by Decision.context_json, which stores
    the full context for every decision (historical bootstrap rows included,
    via is_historical=True) so there is a single authoritative context
    record per decision rather than two overlapping tables. Kept only as a
    placeholder class in case a future feature-store-style cache of raw
    generated contexts (independent of any decision) is needed."""

    __tablename__ = "daily_contexts_unused"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class Decision(Base):
    """Decision log entry (also used for synthetic historical bootstrap rows).

    `propensity` is mandatory (importance-weight correction for any
    off-policy learning/evaluation - see docs/ARCHITECTURE.md).
    """

    __tablename__ = "decisions"

    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    property_id: Mapped[str] = mapped_column(String(64), ForeignKey("properties.property_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    cluster_id: Mapped[str] = mapped_column(String(64), index=True)

    room_type: Mapped[str] = mapped_column(String(32))
    rate_plan: Mapped[str] = mapped_column(String(32))
    los_bucket: Mapped[str] = mapped_column(String(8))
    stay_date: Mapped[dt.date] = mapped_column(DateTime, index=True)
    decision_ts: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)

    context_json: Mapped[str] = mapped_column(Text)

    arm_index: Mapped[int] = mapped_column(Integer)
    arm_label: Mapped[str] = mapped_column(String(32))
    arm_offset_pct: Mapped[float] = mapped_column(Float)
    reference_rate: Mapped[float] = mapped_column(Float)
    published_price: Mapped[float] = mapped_column(Float)
    propensity: Mapped[float] = mapped_column(Float)

    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")

    # pending_approval | auto_published | approved | rejected | historical
    status: Mapped[str] = mapped_column(String(20), default="pending_approval")
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    is_historical: Mapped[bool] = mapped_column(Boolean, default=False)

    # Price "validity window" - lets bookings attribute to whichever price
    # was actually live at booking time (docs/ARCHITECTURE.md recommendation
    # cadence design).
    superseded_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    override_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Two-stage reward (fast proxy now, delayed true reward reconciled later)
    proxy_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    true_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    reconciled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, default=1)
