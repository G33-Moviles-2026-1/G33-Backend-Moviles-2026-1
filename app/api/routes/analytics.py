from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.analytics import (
    AnalyticsEventIn,
    AnalyticsEventOut,
    ScheduleImportFunnelOut,
    ScheduleImportStepIn,
    ScheduleImportStepOut,
)
from app.services.analytics_service import (
    get_schedule_import_funnel,
    track_homepage_event,
    track_schedule_import_step,
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
    return await track_homepage_event(db, payload)


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
