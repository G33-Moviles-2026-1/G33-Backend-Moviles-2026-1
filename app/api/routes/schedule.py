from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.schemas.schedule import (
    FreeSlotsForDayOut,
    FreeRoomsForDayOut,
    GoogleCalendarAuthUrlOut,
    GoogleCalendarConnectionStatusOut,
    GoogleCalendarImportIn,
    GoogleCalendarListOut,
    GroupFreeSlotsOut,
    GroupFreeSlotsRequest,
    ManualScheduleIn,
    ManualScheduleOut,
    ScheduleClassesOut,
    ScheduleDeleteClassOut,
    ScheduleDeleteOccurrenceOut,
    ScheduleDeleteOut,
    ScheduleUploadOut,
    WeeklyScheduleOut,
    DayRoomRecommendationsOut,
)
from app.services.schedule_service import (
    complete_google_calendar_oauth,
    create_google_calendar_auth_url,
    delete_schedule_class,
    delete_schedule_occurrence,
    delete_user_schedule,
    get_best_group_free_slots,
    get_free_slots_for_day,
    get_free_rooms_for_day,
    get_google_calendar_connection_status,
    get_weekly_schedule,
    list_google_calendars,
    list_schedule_classes,
    upload_google_calendar_schedule,
    upload_ics_schedule,
    upload_manual_schedule,
)
from app.services.schedule_recommendation_service import get_room_recommendations_for_day

router = APIRouter(prefix="/schedule", tags=["schedule"])

_MAX_ICS_BYTES = 2 * 1024 * 1024  # 2 MB


def _require_active_user_email(request: Request) -> str:
    user_email = request.session.get("user_name")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="There is no active session",
        )
    return user_email


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
    request: Request,
    file: UploadFile = File(..., description="ICS calendar file"),
    db: AsyncSession = Depends(get_db),
) -> ScheduleUploadOut:
    user_email = _require_active_user_email(request)
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

@router.get(
    "/google/auth-url",
    response_model=GoogleCalendarAuthUrlOut,
    summary="Create a Google Calendar OAuth URL",
)
async def google_calendar_auth_url(
    request: Request,
) -> GoogleCalendarAuthUrlOut:
    user_email = _require_active_user_email(request)
    redirect_uri = settings.resolved_google_redirect_uri or str(
        request.url_for("google_calendar_callback")
    )

    return create_google_calendar_auth_url(
        user_email=user_email,
        redirect_uri=redirect_uri,
    )


@router.get(
    "/google/callback",
    response_class=HTMLResponse,
    summary="Google Calendar OAuth callback",
)
async def google_calendar_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        return HTMLResponse(
            "<h1>Google Calendar connection failed</h1>"
            "<p>You can close this tab and return to AndeSpace.</p>",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing Google authorization code.",
        )

    await complete_google_calendar_oauth(state=state, code=code)

    return HTMLResponse(
        "<h1>Google Calendar connected</h1>"
        "<p>You can close this tab and return to AndeSpace.</p>"
    )


@router.get(
    "/google/status",
    response_model=GoogleCalendarConnectionStatusOut,
    summary="Check Google Calendar OAuth status",
)
async def google_calendar_status(
    request: Request,
    state: str,
) -> GoogleCalendarConnectionStatusOut:
    user_email = _require_active_user_email(request)
    return get_google_calendar_connection_status(
        user_email=user_email,
        state=state,
    )


@router.get(
    "/google/calendars",
    response_model=GoogleCalendarListOut,
    summary="List Google calendars after OAuth",
)
async def google_calendars(
    request: Request,
    state: str,
) -> GoogleCalendarListOut:
    user_email = _require_active_user_email(request)
    return await list_google_calendars(user_email=user_email, state=state)


@router.post(
    "/upload/google",
    response_model=ScheduleUploadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Import selected Google calendars as a schedule",
)
async def upload_google(
    payload: GoogleCalendarImportIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ScheduleUploadOut:
    user_email = _require_active_user_email(request)
    return await upload_google_calendar_schedule(
        db,
        user_email=user_email,
        state=payload.state,
        calendar_ids=payload.calendar_ids,
    )


@router.post(
    "/upload/manual",
    response_model=ManualScheduleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a schedule by manually entering classes",
)
async def upload_manual(
    payload: ManualScheduleIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ManualScheduleOut:
    user_email = _require_active_user_email(request)
    if not payload.classes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="classes list must not be empty.",
        )
    return await upload_manual_schedule(
        db,
        user_email=user_email,
        classes_in=payload.classes,
    )


# ── Weekly calendar view ─────────────────────────────────────────────────────

@router.get(
    "/week",
    response_model=WeeklyScheduleOut,
    summary="Get the user's classes for the week containing 'date'",
)
async def get_week(
    request: Request,
    date: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> WeeklyScheduleOut:
    user_email = _require_active_user_email(request)
    reference = _parse_query_date(date)
    return await get_weekly_schedule(
        db,
        user_email=user_email,
        reference_date=reference,
    )


# ── Free-room discovery ──────────────────────────────────────────────────────

@router.get(
    "/free-slots",
    response_model=FreeSlotsForDayOut,
    summary="Get only free time slots for the user on a given date",
)
async def get_free_slots(
    request: Request,
    date: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> FreeSlotsForDayOut:
    user_email = _require_active_user_email(request)
    target = _parse_query_date(date)
    return await get_free_slots_for_day(db, user_email=user_email, target_date=target)


@router.post(
    "/friends/free-slots",
    response_model=GroupFreeSlotsOut,
    summary="Get the best shared free slots for selected friends",
)
async def get_group_free_slots(
    payload: GroupFreeSlotsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GroupFreeSlotsOut:
    user_email = _require_active_user_email(request)
    return await get_best_group_free_slots(
        db,
        user_email=user_email,
        payload=payload,
    )


@router.get(
    "/free-rooms",
    response_model=FreeRoomsForDayOut,
    summary="Get rooms available during the user's free time on a given date",
)
async def get_free_rooms(
    request: Request,
    date: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> FreeRoomsForDayOut:
    user_email = _require_active_user_email(request)
    target = _parse_query_date(date)
    return await get_free_rooms_for_day(db, user_email=user_email, target_date=target)


@router.delete(
    "",
    response_model=ScheduleDeleteOut,
    summary="Delete the user's full schedule",
)
async def delete_schedule(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ScheduleDeleteOut:
    user_email = _require_active_user_email(request)
    return await delete_user_schedule(db, user_email=user_email)


@router.delete(
    "/class/{class_id}",
    response_model=ScheduleDeleteClassOut,
    summary="Delete a full class from the user's schedule",
)
async def delete_class(
    class_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ScheduleDeleteClassOut:
    user_email = _require_active_user_email(request)
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
    request: Request,
    date: str,
    db: AsyncSession = Depends(get_db),
) -> ScheduleDeleteOccurrenceOut:
    user_email = _require_active_user_email(request)
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
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ScheduleClassesOut:
    user_email = _require_active_user_email(request)
    return await list_schedule_classes(db, user_email=user_email)

@router.get(
    "/recommendations/day", 
    response_model=DayRoomRecommendationsOut
    )
async def room_recommendations_for_day(
    request: Request,
    date: date,
    db: AsyncSession = Depends(get_db),
):
    user_email = _require_active_user_email(request)

    return await get_room_recommendations_for_day(
        db,
        user_email=user_email,
        target_date=date,
    )

@router.get(
    "/{target_email}/week",
    response_model=WeeklyScheduleOut,
    summary="Get a friend's weekly schedule",
)
async def get_friend_week(
    target_email: str,
    request: Request,
    date: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> WeeklyScheduleOut:
    user_email = _require_active_user_email(request)
    reference = _parse_query_date(date)
    

    from app.services.schedule_service import get_friend_weekly_schedule
    
    return await get_friend_weekly_schedule(
        db,
        requester_email=user_email,
        target_email=target_email,
        reference_date=reference,
    )
