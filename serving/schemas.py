"""Pydantic request/response schemas for serving/api.py."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class RateCalendarRow(BaseModel):
    decision_id: str
    property_id: str
    room_type: str
    rate_plan: str
    los_bucket: str
    stay_date: dt.date
    reference_rate: float
    published_price: float
    arm_label: str
    arm_offset_pct: float
    confidence_score: float
    confidence_label: str
    status: str
    decision_ts: dt.datetime
    context: dict = {}


class ApprovalAction(BaseModel):
    approved_by: str
    override_price: float | None = None


class RecommendationRequest(BaseModel):
    property_id: str
    room_type: str
    rate_plan: str
    start_date: dt.date
    end_date: dt.date
    los_nights: int = 2
    persist: bool = False
    context_overrides: dict | None = None


class ScoreRequest(BaseModel):
    property_id: str
    room_type: str
    rate_plan: str
    stay_date: dt.date
    as_of_date: dt.date | None = None
    los_nights: int = 2
    dry_run: bool = False
    context_overrides: dict | None = None


class ScoreResponse(BaseModel):
    property_id: str
    room_type: str
    rate_plan: str
    stay_date: dt.date
    reference_rate: float
    chosen_arm_label: str
    chosen_arm_offset_pct: float
    published_price: float
    confidence_score: float
    confidence_label: str
    confidence_breakdown: dict
    requires_approval: bool
    excluded_arms: list[dict]
    all_arms: list[dict]
    decision_id: str | None = None
    context: dict = {}
