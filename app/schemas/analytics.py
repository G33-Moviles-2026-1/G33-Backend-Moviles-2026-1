from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from app.db.models import UtilityType


AnalyticsEventName = Literal[
    "home_search_submitted",
    "home_filters_opened",
    "booking_created",
    "open_screen_timestamp",
    "room_gap_search_submitted",
    "schedule_import_step",
    "favorite_submitted",
]


class AnalyticsEventIn(BaseModel):
    session_id: UUID
    device_id: str | None = None
    user_email: str | None = None
    event_name: AnalyticsEventName
    screen: str = "home"
    duration_ms: int | None = None
    props_json: dict = Field(default_factory=dict)


class AnalyticsEventOut(BaseModel):
    ok: bool = True


class AnalyticsEventOutRead(BaseModel):
    session_id: UUID
    device_id: str | None = None
    user_email: str | None = None
    event_name: str
    screen: str | None = None
    ts: datetime
    event_date: date | None = None
    duration_ms: int | None = None
    props_json: dict
    model_config = ConfigDict(from_attributes=True)


class AnalyticsEventsListResponse(BaseModel):
    total: int
    items: list[AnalyticsEventOutRead]

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
    timestamp: datetime | None = None
    props_json: dict = Field(default_factory=dict)


class ScheduleImportStepOut(BaseModel):
    ok: bool = True
# ── Room gap search event (BQ) ───────────────────────────────────────────────

class RoomGapSearchEventIn(BaseModel):
    """Emitted when a user submits a room gap search with utilities."""

    session_id: UUID
    device_id: str | None = None
    user_email: str | None = None
    date_value: date
    gap_start: time
    gap_end: time
    utilities: list[UtilityType] = Field(default_factory=list)
    props_json: dict = Field(default_factory=dict)


class RoomGapSearchEventOut(BaseModel):
    ok: bool = True

class UserScreenTimeReport(BaseModel):
    date: date 
    screen: str
    user_email: str
    total_seconds: float

class UserScreenTimeDistributionOut(BaseModel):
    results: list[UserScreenTimeReport]


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


class ScreenTimeReport(BaseModel):
    screen: str
    total_seconds: float


class ScreenTimeResponse(BaseModel):
    results: list[ScreenTimeReport]

class RecommendationWeightsOut(BaseModel):
    building_weight: float
    floor_weight: float
    capacity_weight: float
    utility_weight: float
    availability_weight: float


class BookingRoomRecommendationWeightsOut(BaseModel):
    building_weight: float
    floor_weight: float
    capacity_weight: float
    utility_weight: float
    availability_weight: float


class BookingRoomSpecAnalyticsOut(BaseModel):
    booking_created_date: date

    room_id: str
    building_code: str
    building_name: str | None = None
    room_number: str
    room_floor: int | None = None
    capacity: int
    reliability: float

    utilities: list[str] = Field(default_factory=list)
    utility_count: int = 0

    availability_window_count: int = 0
    total_weekly_available_minutes: int = 0


class BookingRoomSpecsAnalyticsResponse(BaseModel):
    total: int
    scoring_weights: BookingRoomRecommendationWeightsOut
    items: list[BookingRoomSpecAnalyticsOut]