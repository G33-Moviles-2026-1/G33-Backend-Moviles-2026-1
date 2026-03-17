from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.schedule import (
    FreeRoomsForDayOut,
    ManualScheduleIn,
    ManualScheduleOut,
    ScheduleClassesOut,
    ScheduleDeleteClassOut,
    ScheduleDeleteOccurrenceOut,
    ScheduleDeleteOut,
    ScheduleUploadOut,
    WeeklyScheduleOut,
)
from app.services.schedule_service import (
    delete_schedule_class,
    delete_schedule_occurrence,
    delete_user_schedule,
    get_free_rooms_for_day,
    get_weekly_schedule,
    list_schedule_classes,
    upload_ics_schedule,
    upload_manual_schedule,
)

router = APIRouter(prefix="/schedule", tags=["schedule"])

_MAX_ICS_BYTES = 2 * 1024 * 1024  # 2 MB


def _parse_query_date(value: str | None) -> date:
    if value is None:
        return date.today()

    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError:
        pass

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="date must be in DD-MM-YYYY format",
    )


# ── Upload ICS ───────────────────────────────────────────────────────────────

@router.post(
    "/upload/ics",
    response_model=ScheduleUploadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a university schedule in ICS format",
)
async def upload_ics(
    user_email: str = Form(..., description="Authenticated user e-mail"),
    file: UploadFile = File(..., description="ICS calendar file"),
    db: AsyncSession = Depends(get_db),
) -> ScheduleUploadOut:
    if file.content_type not in (
        "text/calendar",
        "application/ics",
        "application/octet-stream",
        # Some clients send the generic binary type
    ):
        # Soft check — don't reject since MIME can vary by OS
        pass

    raw = await file.read(_MAX_ICS_BYTES + 1)
    if len(raw) > _MAX_ICS_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="ICS file exceeds the 2 MB limit.",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty.",
        )

    return await upload_ics_schedule(db, user_email=user_email, ics_bytes=raw)


# ── Manual entry ─────────────────────────────────────────────────────────────

@router.post(
    "/upload/manual",
    response_model=ManualScheduleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a schedule by manually entering classes",
)
async def upload_manual(
    payload: ManualScheduleIn,
    db: AsyncSession = Depends(get_db),
) -> ManualScheduleOut:
    if not payload.classes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="classes list must not be empty.",
        )
    return await upload_manual_schedule(
        db,
        user_email=payload.user_email,
        classes_in=payload.classes,
    )


# ── Weekly calendar view ─────────────────────────────────────────────────────

@router.get(
    "/week",
    response_model=WeeklyScheduleOut,
    summary="Get the user's classes for the week containing 'date'",
)
async def get_week(
    user_email: str,
    date: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> WeeklyScheduleOut:
    reference = _parse_query_date(date)
    return await get_weekly_schedule(
        db,
        user_email=user_email,
        reference_date=reference,
    )


# ── Free-room discovery ──────────────────────────────────────────────────────

@router.get(
    "/free-rooms",
    response_model=FreeRoomsForDayOut,
    summary="Get rooms available during the user's free time on a given date",
)
async def get_free_rooms(
    user_email: str,
    date: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> FreeRoomsForDayOut:
    target = _parse_query_date(date)
    return await get_free_rooms_for_day(db, user_email=user_email, target_date=target)


@router.delete(
    "",
    response_model=ScheduleDeleteOut,
    summary="Delete the user's full schedule",
)
async def delete_schedule(
    user_email: str,
    db: AsyncSession = Depends(get_db),
) -> ScheduleDeleteOut:
    return await delete_user_schedule(db, user_email=user_email)


@router.delete(
    "/class/{class_id}",
    response_model=ScheduleDeleteClassOut,
    summary="Delete a full class from the user's schedule",
)
async def delete_class(
    class_id: UUID,
    user_email: str,
    db: AsyncSession = Depends(get_db),
) -> ScheduleDeleteClassOut:
    return await delete_schedule_class(
        db,
        user_email=user_email,
        class_id=class_id,
    )


@router.delete(
    "/class/{class_id}/occurrence",
    response_model=ScheduleDeleteOccurrenceOut,
    summary="Delete one class occurrence by date (DD-MM-YYYY)",
)
async def delete_occurrence(
    class_id: UUID,
    user_email: str,
    date: str,
    db: AsyncSession = Depends(get_db),
) -> ScheduleDeleteOccurrenceOut:
    target = _parse_query_date(date)
    return await delete_schedule_occurrence(
        db,
        user_email=user_email,
        class_id=class_id,
        target_date=target,
    )


@router.get(
    "/classes",
    response_model=ScheduleClassesOut,
    summary="List base classes in the user's schedule",
)
async def get_schedule_classes(
    user_email: str,
    db: AsyncSession = Depends(get_db),
) -> ScheduleClassesOut:
    return await list_schedule_classes(db, user_email=user_email)
