from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


AnalyticsEventName = Literal[
    "home_search_submitted",
    "home_filters_opened",
    "booking_created",
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