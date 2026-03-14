from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


HomepageEventName = Literal["home_search_submitted", "home_filters_opened"]


class AnalyticsEventIn(BaseModel):
    session_id: UUID
    device_id: str | None = None
    user_email: str | None = None
    event_name: HomepageEventName
    screen: str = "home"
    duration_ms: int | None = None
    props_json: dict = Field(default_factory=dict)


class AnalyticsEventOut(BaseModel):
    ok: bool = True


# ── Schedule import funnel ────────────────────────────────────────────────────

ScheduleImportMethod = Literal["ics", "pdf", "google", "manual"]

# Each method defines ordered steps. step_number starts at 1.
# Step names are intentionally human-readable for reporting.
SCHEDULE_IMPORT_STEPS: dict[str, list[str]] = {
    "ics": [
        "started",
        "file_selected",
        "parsed",
        "confirmed",
        "completed",
    ],
    "pdf": [
        "started",
        "file_selected",
        "parsed",
        "confirmed",
        "completed",
    ],
    "google": [
        "started",
        "auth_initiated",
        "auth_granted",
        "calendar_selected",
        "completed",
    ],
    "manual": [
        "started",
        "first_class_added",
        "confirmed",
        "completed",
    ],
}


class ScheduleImportStepIn(BaseModel):
    """Emitted by the mobile client at each step of the schedule import flow."""

    session_id: UUID
    device_id: str | None = None
    user_email: str | None = None
    method: ScheduleImportMethod
    step: str  # one of SCHEDULE_IMPORT_STEPS[method]
    step_number: int  # 1-based position in the funnel
    props_json: dict = Field(default_factory=dict)


class ScheduleImportStepOut(BaseModel):
    ok: bool = True


# ── Funnel report ─────────────────────────────────────────────────────────────

class FunnelStepStat(BaseModel):
    step_number: int
    step: str
    users_reached: int
    dropoff_from_prev_pct: float | None  # None for step 1


class MethodFunnelOut(BaseModel):
    method: str
    total_started: int
    total_completed: int
    completion_rate_pct: float
    steps: list[FunnelStepStat]


class ScheduleImportFunnelOut(BaseModel):
    """
    Answers: 'What is the most common way users upload/import their schedule,
    and which method has the highest drop-off by step?'
    """

    most_common_method: str | None
    highest_dropoff_method: str | None  # method with worst step-to-step drop-off
    methods: list[MethodFunnelOut]
