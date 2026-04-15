from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from sqlalchemy import select
from app.db import models
from app.db.session import get_db
from app.schemas.analytics import UserScreenTimeDistributionOut
from app.services.analytics_service import get_user_screen_time_distribution
from datetime import date


from app.schemas.analytics import (
    AnalyticsEventIn,
    AnalyticsEventOut,
    RoomGapSearchEventIn,
    RoomGapSearchEventOut,
    ScheduleImportFunnelOut,
    ScheduleImportStepIn,
    ScheduleImportStepOut,
    AnalyticsEventOutRead,
    ScreenTimeResponse
)
from app.services.analytics_service import (
    get_schedule_import_funnel,
    track_room_gap_search_event,
    track_analytics_event,
    track_schedule_import_step,
    get_screen_time_stats
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post(
    "/events",
    response_model=AnalyticsEventOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_analytics_event(
    payload: AnalyticsEventIn,
    db: AsyncSession = Depends(get_db),
) -> AnalyticsEventOut:
    return await track_analytics_event(db, payload)


@router.get(
    "/events",
    response_model=List[AnalyticsEventOutRead],
    summary="List analytics events by event name",
)
async def list_analytics_events(
    event_name: str,
    db: AsyncSession = Depends(get_db),
) -> List[AnalyticsEventOutRead]:
    stmt = select(models.AnalyticsEvent).where(models.AnalyticsEvent.event_name == event_name)

    stmt = stmt.order_by(models.AnalyticsEvent.ts.desc())
    result = await db.execute(stmt)
    events = result.scalars().all()
    return [AnalyticsEventOutRead.model_validate(event) for event in events]


@router.post(
    "/room-gap-search",
    response_model=RoomGapSearchEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Track room gap search event",
    description=(
        "Emit this event when a user submits a room gap search with utilities. "
        "Used to answer the BQ about gap search behavior without returning room results."
    ),
)
async def record_room_gap_search_event(
    payload: RoomGapSearchEventIn,
    db: AsyncSession = Depends(get_db),
) -> RoomGapSearchEventOut:
    return await track_room_gap_search_event(db, payload)


# ── Schedule import funnel ────────────────────────────────────────────────────

@router.post(
    "/schedule-import-step",
    response_model=ScheduleImportStepOut,
    status_code=status.HTTP_201_CREATED,
    summary="Track a step in the schedule import funnel",
    description=(
        "Emit this event at each step of the schedule upload flow "
        "(ICS, PDF, Google Calendar sync, or manual entry). "
        "Used to answer: 'What is the most common import method and "
        "which has the highest drop-off by step?'"
    ),
)
async def record_schedule_import_step(
    payload: ScheduleImportStepIn,
    db: AsyncSession = Depends(get_db),
) -> ScheduleImportStepOut:
    return await track_schedule_import_step(db, payload)


@router.get(
    "/schedule-import-funnel",
    response_model=ScheduleImportFunnelOut,
    summary="Schedule import funnel report (BQ answer)",
    description=(
        "Returns the most common schedule import method and the method "
        "with the highest step-to-step drop-off, along with per-method "
        "funnel statistics."
    ),
)
async def schedule_import_funnel(
    db: AsyncSession = Depends(get_db),
) -> ScheduleImportFunnelOut:
    return await get_schedule_import_funnel(db)


@router.get(
    "/screen-timestamps",
    response_model=List[AnalyticsEventOutRead],
    summary="Get all screen opening timestamps",
)
async def get_screen_open_timestamps(
    db: AsyncSession = Depends(get_db)
):

    stmt = (
        select(models.AnalyticsEvent)
        .where(models.AnalyticsEvent.event_name == "open_screen_timestamp")
        .order_by(models.AnalyticsEvent.ts.desc())
    )

    result = await db.execute(stmt)
    events = result.scalars().all()

    return events


@router.get(
    "/screen-time-stats",
    response_model=ScreenTimeResponse,
    summary="Calculate total screen time per screen type",
)
async def screen_time_stats(
    db: AsyncSession = Depends(get_db)
):
    stats = await get_screen_time_stats(db)
    return {"results": stats}


@router.get(
    "/screen-time-distribution",
    response_model=UserScreenTimeDistributionOut,
    summary="Get screen time distribution per user for Power BI",
)
async def screen_time_distribution(
    db: AsyncSession = Depends(get_db)
):
    stats = await get_user_screen_time_distribution(db)
    return {"results": stats}
