from __future__ import annotations

import html
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from app.db.models import User
from sqlalchemy import select
from app.db.repositories.friendships_repo import list_accepted_friends_for_user


import httpx
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ScheduleSource, Weekday
from app.db.repositories.schedule_repo import (
    AvailableRoomRow,
    ClassInputData,
    ScheduleClassRow,
    create_schedule_with_classes,
    clone_class_with_date_range,
    delete_class_by_id,
    existing_room_ids,
    fetch_rooms_for_windows,
    get_active_schedule_id,
    get_class_with_weekdays_for_user,
    get_classes_with_weekdays,
    purge_schedules_for_user,
    update_class_date_range,
    user_exists,
)
from app.schemas.schedule import (
    FreeSlotsForDayOut,
    FreeRoomsForDayOut,
    FreeSlotOut,
    GoogleCalendarAuthUrlOut,
    GoogleCalendarConnectionStatusOut,
    GoogleCalendarListOut,
    GoogleCalendarOut,
    ManualClassIn,
    ScheduleDeleteOut,
    ScheduleDeleteOccurrenceOut,
    ScheduleDeleteClassOut,
    ScheduleClassesOut,
    ScheduleClassBaseOut,
    ManualScheduleOut,
    RoomInSlotOut,
    ScheduleClassOccurrenceOut,
    ScheduleUploadOut,
    SlotWithRoomsOut,
    WeeklyScheduleOut,
)

BOGOTA_TZ = ZoneInfo("America/Bogota")

# Campus operating hours used to compute free slots
CAMPUS_START = time(5, 30)
CAMPUS_END = time(22, 0)

CLASS_START_MIN = time(5, 30)
CLASS_END_MAX = time(22, 0)

# Minimum free slot to surface (minutes)
MIN_FREE_SLOT_MINUTES = 30

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_CALENDAR_SCOPES = "https://www.googleapis.com/auth/calendar.readonly"
GOOGLE_IMPORT_LOOKBACK_DAYS = 30
GOOGLE_IMPORT_LOOKAHEAD_DAYS = 240

_BYDAY_MAP: dict[str, str] = {
    "MO": "monday",
    "TU": "tuesday",
    "WE": "wednesday",
    "TH": "thursday",
    "FR": "friday",
    "SA": "saturday",
    "SU": "sunday",
}

_PYTHON_WEEKDAY_MAP: dict[int, str] = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}

_DB_WEEKDAY: dict[str, Weekday] = {w.value: w for w in Weekday}


# ── ICS Parser ───────────────────────────────────────────────────────────────

@dataclass
class _ParsedClass:
    title: str | None
    location_text: str | None
    room_id: str | None
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    weekdays: list[str]


@dataclass
class _GoogleCalendarFlow:
    user_email: str
    redirect_uri: str
    access_token: str | None = None
    expires_at: datetime | None = None


_GOOGLE_CALENDAR_FLOWS: dict[str, _GoogleCalendarFlow] = {}


def _unfold(text: str) -> str:
    """Remove ICS line-folding (CRLF or LF followed by whitespace)."""
    return re.sub(r"\r?\n[ \t]", "", text)


def _unescape_ics(value: str) -> str:
    """Unescape ICS text escapes."""
    value = value.replace("\\n", "\n").replace("\\N", "\n")
    value = value.replace("\\;", ";").replace("\\,", ",")
    return value.replace("\\\\", "\\")


def _decode_text(value: str) -> str:
    return html.unescape(_unescape_ics(value)).strip()


def _parse_ics_datetime(value: str) -> datetime:
    """Parse ICS datetime value (first 15 chars: YYYYMMDDTHHmmSS)."""
    return datetime.strptime(value[:15], "%Y%m%dT%H%M%S")


def _extract_room_id(location: str) -> str | None:
    """Extract room ID from Uniandes LOCATION field.

    Example: 'Campus: CAMPUS PRINCIPAL Edificio: Edif. Mario Laserna (ML) Salón: ML_515'
    → 'ML 515'
    """
    m = re.search(r"Sal[oó]n:\s*(\S+)", location, re.IGNORECASE)
    if m:
        raw = m.group(1).strip().rstrip(",;")
        return raw.replace("_", " ")

    cleaned = _decode_text(location).strip().rstrip(",;")
    if not cleaned:
        return None

    # Google Calendar often stores Uniandes rooms directly as LOCATION,
    # e.g. "ML_603", "LL_203", "RGD_106-7", or "O 203".
    direct_room = re.search(
        r"\b([A-Z]{1,5})[\s_-]+([0-9][A-Z0-9-]*)\b",
        cleaned.upper(),
    )
    if direct_room:
        return f"{direct_room.group(1)} {direct_room.group(2)}"

    return None


def _get_prop_value(vevent: str, prop_name: str) -> str | None:
    """Extract property value from a VEVENT block.

    Handles parameters like DTSTART;TZID=...:VALUE by splitting on first ':'.
    """
    m = re.search(
        rf"^{re.escape(prop_name)}(?:[;:][^\r\n]*)",
        vevent,
        re.MULTILINE,
    )
    if not m:
        return None
    line = m.group(0)
    colon_pos = line.index(":")
    return line[colon_pos + 1:].strip()


def parse_ics(content: bytes) -> tuple[list[_ParsedClass], list[str]]:
    """Parse an ICS file and return (classes, warnings)."""
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not decode ICS file as UTF-8.",
        )

    text = _unfold(text)
    classes: list[_ParsedClass] = []
    warnings: list[str] = []

    for match in re.finditer(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.DOTALL):
        vevent = match.group(1)

        dtstart_raw = _get_prop_value(vevent, "DTSTART")
        dtend_raw = _get_prop_value(vevent, "DTEND")
        if not dtstart_raw or not dtend_raw:
            warnings.append("Skipped event: missing DTSTART or DTEND.")
            continue

        try:
            dt_start = _parse_ics_datetime(dtstart_raw)
            dt_end = _parse_ics_datetime(dtend_raw)
        except ValueError:
            warnings.append(
                f"Skipped event: could not parse date '{dtstart_raw}'.")
            continue

        start_date = dt_start.date()
        start_time = dt_start.time()
        end_time = dt_end.time()
        end_date = start_date  # default: single occurrence

        weekdays: list[str] = []

        rrule_raw = _get_prop_value(vevent, "RRULE")
        if rrule_raw:
            rrule = {
                k: v
                for part in rrule_raw.split(";")
                if "=" in part
                for k, v in [part.split("=", 1)]
            }
            byday = rrule.get("BYDAY", "")
            weekdays = [
                _BYDAY_MAP[d]
                for d in byday.split(",")
                if d.strip() in _BYDAY_MAP
            ]
            until_raw = rrule.get("UNTIL")
            if until_raw:
                try:
                    end_date = _parse_ics_datetime(until_raw).date()
                except ValueError:
                    warnings.append(
                        f"Could not parse UNTIL '{until_raw}'; using start date.")

        if not weekdays:
            # Single occurrence: infer weekday from DTSTART
            weekdays = [_PYTHON_WEEKDAY_MAP[dt_start.weekday()]]

        summary_raw = _get_prop_value(vevent, "SUMMARY") or ""
        location_raw = _get_prop_value(vevent, "LOCATION") or ""

        title = _decode_text(summary_raw) or None
        location_text = _decode_text(location_raw) or None
        room_id = _extract_room_id(location_raw) if location_raw else None

        classes.append(
            _ParsedClass(
                title=title,
                location_text=location_text,
                room_id=room_id,
                start_date=start_date,
                end_date=end_date,
                start_time=start_time,
                end_time=end_time,
                weekdays=weekdays,
            )
        )

    if not classes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid VEVENT blocks found in the ICS file.",
        )

    return classes, warnings


# ── Upload helpers ───────────────────────────────────────────────────────────

def _parsed_to_input(p: _ParsedClass) -> ClassInputData:
    return ClassInputData(
        title=p.title,
        location_text=p.location_text,
        room_id=p.room_id,
        start_date=p.start_date,
        end_date=p.end_date,
        start_time=p.start_time,
        end_time=p.end_time,
        weekdays=p.weekdays,
    )


def _classes_overlap(a: ClassInputData, b: ClassInputData) -> bool:
    if a.end_date < b.start_date or b.end_date < a.start_date:
        return False

    if not set(a.weekdays).intersection(b.weekdays):
        return False

    return a.start_time < b.end_time and b.start_time < a.end_time


def _normalize_import_classes(
    classes: list[ClassInputData],
) -> tuple[list[ClassInputData], list[str]]:
    normalized: list[ClassInputData] = []
    warnings: list[str] = []

    for c in classes:
        title = c.title or "Untitled event"
        weekdays = [weekday for weekday in c.weekdays if weekday != "sunday"]

        if len(weekdays) != len(c.weekdays):
            warnings.append(f"Skipped Sunday occurrence(s) for '{title}'.")

        if not weekdays:
            warnings.append(f"Skipped '{title}' because it only occurs on Sunday.")
            continue

        if c.start_date > c.end_date:
            warnings.append(f"Skipped '{title}' because its date range is invalid.")
            continue

        start_time = max(c.start_time, CLASS_START_MIN)
        end_time = min(c.end_time, CLASS_END_MAX)

        if end_time <= start_time:
            warnings.append(
                f"Skipped '{title}' because it is outside campus hours."
            )
            continue

        candidate = ClassInputData(
            title=c.title,
            location_text=c.location_text,
            room_id=c.room_id,
            start_date=c.start_date,
            end_date=c.end_date,
            start_time=start_time,
            end_time=end_time,
            weekdays=weekdays,
        )

        if any(_classes_overlap(candidate, accepted) for accepted in normalized):
            warnings.append(
                f"Skipped '{title}' because it overlaps with an earlier class."
            )
            continue

        normalized.append(candidate)

    return normalized, warnings

def _normalize_room_id(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.upper()

    return normalized

async def _sanitize_room_ids(
    db: AsyncSession,
    classes: list[ClassInputData],
) -> list[str]:
    """Normalize room IDs, keep valid ones, and move invalid ones to location_text."""
    
    for c in classes:
        c.room_id = _normalize_room_id(c.room_id)

    raw_room_ids = sorted({c.room_id for c in classes if c.room_id})
    found = await existing_room_ids(db, raw_room_ids)

    warnings: list[str] = []
    for c in classes:
        if c.room_id and c.room_id not in found:
            warnings.append(
                f"Room '{c.room_id}' was not found in DB. Saved as location text only."
            )

            if not c.location_text or not c.location_text.strip():
                c.location_text = c.room_id

            c.room_id = None

    return warnings


def _validate_class_time_ranges(classes: list[ClassInputData]) -> None:
    for c in classes:
        if c.start_time < CLASS_START_MIN or c.start_time >= CLASS_END_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Class start_time must be between 05:30 and 22:00.",
            )

        if c.end_time > CLASS_END_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Class end_time must be at or before 22:00.",
            )

        if c.end_time <= c.start_time:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Class end_time must be later than start_time.",
            )


# ── Public service functions ─────────────────────────────────────────────────

def _require_google_oauth_settings() -> tuple[str, str]:
    client_id = settings.resolved_google_client_id
    client_secret = settings.resolved_google_client_secret

    if not client_id or not client_secret:
        missing = ", ".join(settings.missing_google_oauth_settings)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Google Calendar is not configured on the server. Missing: {missing}.",
        )

    return client_id, client_secret


def create_google_calendar_auth_url(
    *,
    user_email: str,
    redirect_uri: str,
) -> GoogleCalendarAuthUrlOut:
    client_id, _ = _require_google_oauth_settings()
    state = secrets.token_urlsafe(32)
    _GOOGLE_CALENDAR_FLOWS[state] = _GoogleCalendarFlow(
        user_email=user_email,
        redirect_uri=redirect_uri,
    )

    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_CALENDAR_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )

    return GoogleCalendarAuthUrlOut(
        auth_url=f"{GOOGLE_AUTH_URL}?{query}",
        state=state,
    )


async def complete_google_calendar_oauth(
    *,
    state: str,
    code: str,
) -> None:
    client_id, client_secret = _require_google_oauth_settings()
    flow = _GOOGLE_CALENDAR_FLOWS.get(state)

    if flow is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid or expired Google Calendar connection state.",
        )

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": flow.redirect_uri,
            },
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not connect Google Calendar.",
        )

    token_data = response.json()
    access_token = token_data.get("access_token")
    expires_in = int(token_data.get("expires_in") or 3600)

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google did not return an access token.",
        )

    flow.access_token = access_token
    flow.expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)


def _get_connected_google_flow(
    *,
    user_email: str,
    state: str,
) -> _GoogleCalendarFlow:
    flow = _GOOGLE_CALENDAR_FLOWS.get(state)

    if flow is None or flow.user_email != user_email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google Calendar connection was not found.",
        )

    if not flow.access_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Google Calendar connection is not complete yet.",
        )

    if flow.expires_at is not None and flow.expires_at <= datetime.now(UTC):
        _GOOGLE_CALENDAR_FLOWS.pop(state, None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google Calendar connection expired. Please connect again.",
        )

    return flow


def get_google_calendar_connection_status(
    *,
    user_email: str,
    state: str,
) -> GoogleCalendarConnectionStatusOut:
    flow = _GOOGLE_CALENDAR_FLOWS.get(state)
    connected = (
        flow is not None
        and flow.user_email == user_email
        and flow.access_token is not None
        and (flow.expires_at is None or flow.expires_at > datetime.now(UTC))
    )

    return GoogleCalendarConnectionStatusOut(connected=connected)


async def list_google_calendars(
    *,
    user_email: str,
    state: str,
) -> GoogleCalendarListOut:
    flow = _get_connected_google_flow(user_email=user_email, state=state)

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{GOOGLE_CALENDAR_API}/users/me/calendarList",
            headers={"Authorization": f"Bearer {flow.access_token}"},
            params={"minAccessRole": "reader"},
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read Google calendars.",
        )

    calendars: list[GoogleCalendarOut] = []
    for item in response.json().get("items", []):
        calendar_id = item.get("id")
        summary = item.get("summary")

        if not calendar_id or not summary:
            continue

        calendars.append(
            GoogleCalendarOut(
                id=calendar_id,
                summary=summary,
                primary=bool(item.get("primary")),
            )
        )

    return GoogleCalendarListOut(calendars=calendars)


def _parse_google_event_dt(value: dict[str, Any] | None) -> datetime | None:
    if not value:
        return None

    raw = value.get("dateTime")
    if not raw:
        return None

    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BOGOTA_TZ)

    return parsed.astimezone(BOGOTA_TZ)


async def _fetch_google_calendar_events(
    *,
    access_token: str,
    calendar_id: str,
    time_min: datetime,
    time_max: datetime,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    page_token: str | None = None

    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            params = {
                "singleEvents": "true",
                "orderBy": "startTime",
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "maxResults": "2500",
            }
            if page_token:
                params["pageToken"] = page_token

            response = await client.get(
                f"{GOOGLE_CALENDAR_API}/calendars/{calendar_id}/events",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if response.status_code >= 400:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Could not read Google Calendar events.",
                )

            data = response.json()
            events.extend(data.get("items", []))
            page_token = data.get("nextPageToken")

            if not page_token:
                return events


def _google_event_to_class(event: dict[str, Any]) -> ClassInputData | None:
    if event.get("status") == "cancelled":
        return None

    dt_start = _parse_google_event_dt(event.get("start"))
    dt_end = _parse_google_event_dt(event.get("end"))

    if dt_start is None or dt_end is None:
        return None

    title = (event.get("summary") or "Untitled event").strip()
    location_text = (event.get("location") or "").strip() or None
    room_id = _extract_room_id(location_text) if location_text else None
    weekday = _PYTHON_WEEKDAY_MAP[dt_start.weekday()]

    return ClassInputData(
        title=title,
        location_text=location_text,
        room_id=room_id,
        start_date=dt_start.date(),
        end_date=dt_start.date(),
        start_time=dt_start.time().replace(second=0, microsecond=0),
        end_time=dt_end.time().replace(second=0, microsecond=0),
        weekdays=[weekday],
    )


async def upload_ics_schedule(
    db: AsyncSession,
    *,
    user_email: str,
    ics_bytes: bytes,
) -> ScheduleUploadOut:
    if not await user_exists(db, user_email):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please sign up or log in first.",
        )

    parsed, warnings = parse_ics(ics_bytes)
    class_inputs = [_parsed_to_input(p) for p in parsed]
    class_inputs, policy_warnings = _normalize_import_classes(class_inputs)
    warnings.extend(policy_warnings)

    if not class_inputs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid classes were found after applying import rules.",
        )

    warnings.extend(await _sanitize_room_ids(db, class_inputs))

    try:
        await purge_schedules_for_user(db, user_email)
        schedule_id = await create_schedule_with_classes(
            db,
            user_email=user_email,
            source=ScheduleSource.ics_import,
            classes=class_inputs,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not save schedule due to invalid related data.",
        )

    return ScheduleUploadOut(
        ok=True,
        schedule_id=schedule_id,
        classes_count=len(class_inputs),
        warnings=warnings,
    )


async def upload_google_calendar_schedule(
    db: AsyncSession,
    *,
    user_email: str,
    state: str,
    calendar_ids: list[str],
) -> ScheduleUploadOut:
    if not calendar_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select at least one Google calendar.",
        )

    if not await user_exists(db, user_email):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please sign up or log in first.",
        )

    flow = _get_connected_google_flow(user_email=user_email, state=state)
    now = datetime.now(BOGOTA_TZ)
    time_min = now - timedelta(days=GOOGLE_IMPORT_LOOKBACK_DAYS)
    time_max = now + timedelta(days=GOOGLE_IMPORT_LOOKAHEAD_DAYS)

    raw_classes: list[ClassInputData] = []
    warnings: list[str] = []

    for calendar_id in calendar_ids:
        events = await _fetch_google_calendar_events(
            access_token=flow.access_token or "",
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
        )

        for event in events:
            class_input = _google_event_to_class(event)
            if class_input is None:
                title = event.get("summary") or "Untitled event"
                warnings.append(
                    f"Skipped '{title}' because it is not a timed calendar event."
                )
                continue

            raw_classes.append(class_input)

    class_inputs, policy_warnings = _normalize_import_classes(raw_classes)
    warnings.extend(policy_warnings)

    if not class_inputs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid classes were found in the selected calendars.",
        )

    warnings.extend(await _sanitize_room_ids(db, class_inputs))

    try:
        await purge_schedules_for_user(db, user_email)
        schedule_id = await create_schedule_with_classes(
            db,
            user_email=user_email,
            source=ScheduleSource.google_sync,
            classes=class_inputs,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not save Google Calendar schedule.",
        )

    _GOOGLE_CALENDAR_FLOWS.pop(state, None)

    return ScheduleUploadOut(
        ok=True,
        schedule_id=schedule_id,
        classes_count=len(class_inputs),
        warnings=warnings,
    )


async def upload_manual_schedule(
    db: AsyncSession,
    *,
    user_email: str,
    classes_in: list[ManualClassIn],
) -> ManualScheduleOut:
    if not await user_exists(db, user_email):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please sign up or log in first.",
        )

    class_inputs = [
        ClassInputData(
            title=c.title,
            location_text=c.location_text,
            room_id=c.room_id,
            start_date=c.start_date,
            end_date=c.end_date,
            start_time=c.start_time,
            end_time=c.end_time,
            weekdays=list(c.weekdays),
        )
        for c in classes_in
    ]
    _validate_class_time_ranges(class_inputs)
    await _sanitize_room_ids(db, class_inputs)

    try:
        await purge_schedules_for_user(db, user_email)
        schedule_id = await create_schedule_with_classes(
            db,
            user_email=user_email,
            source=ScheduleSource.manual,
            classes=class_inputs,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not save manual schedule due to invalid related data.",
        )

    return ManualScheduleOut(
        ok=True,
        schedule_id=schedule_id,
        classes_count=len(class_inputs),
    )


async def delete_user_schedule(
    db: AsyncSession,
    *,
    user_email: str,
) -> ScheduleDeleteOut:
    if not await user_exists(db, user_email):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please sign up or log in first.",
        )

    schedule_id = await get_active_schedule_id(db, user_email)
    await purge_schedules_for_user(db, user_email)
    await db.commit()

    return ScheduleDeleteOut(ok=True, deleted=schedule_id is not None)


async def list_schedule_classes(
    db: AsyncSession,
    *,
    user_email: str,
) -> ScheduleClassesOut:
    if not await user_exists(db, user_email):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please sign up or log in first.",
        )

    schedule_id = await get_active_schedule_id(db, user_email)
    if schedule_id is None:
        return ScheduleClassesOut(classes=[])

    classes = await get_classes_with_weekdays(db, schedule_id)
    return ScheduleClassesOut(
        classes=[
            ScheduleClassBaseOut(
                class_id=c.class_id,
                title=c.title,
                location_text=c.location_text,
                room_id=c.room_id,
                start_date=c.start_date,
                end_date=c.end_date,
                start_time=c.start_time,
                end_time=c.end_time,
                weekdays=c.weekdays,
            )
            for c in classes
        ]
    )


def _range_has_occurrence(
    *,
    start_date: date,
    end_date: date,
    weekday_str: str,
) -> bool:
    if start_date > end_date:
        return False

    weekday_idx = next(
        (i for i, w in _PYTHON_WEEKDAY_MAP.items() if w == weekday_str), None)
    if weekday_idx is None:
        return False

    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() == weekday_idx:
            return True
        cursor += timedelta(days=1)
    return False


async def delete_schedule_class(
    db: AsyncSession,
    *,
    user_email: str,
    class_id: uuid.UUID,
) -> ScheduleDeleteClassOut:
    cls = await get_class_with_weekdays_for_user(db, user_email=user_email, class_id=class_id)
    if cls is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Class not found for this user.",
        )

    await delete_class_by_id(db, class_id)
    await db.commit()
    return ScheduleDeleteClassOut(ok=True, deleted=True)


async def delete_schedule_occurrence(
    db: AsyncSession,
    *,
    user_email: str,
    class_id: uuid.UUID,
    target_date: date,
) -> ScheduleDeleteOccurrenceOut:
    cls = await get_class_with_weekdays_for_user(db, user_email=user_email, class_id=class_id)
    if cls is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Class not found for this user.",
        )

    if target_date < cls.start_date or target_date > cls.end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Date is outside class range.",
        )

    target_weekday = _PYTHON_WEEKDAY_MAP[target_date.weekday()]
    if target_weekday not in cls.weekdays:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No class occurrence exists on that date.",
        )

    left_start = cls.start_date
    left_end = target_date - timedelta(days=1)
    right_start = target_date + timedelta(days=1)
    right_end = cls.end_date

    left_has = _range_has_occurrence(
        start_date=left_start,
        end_date=left_end,
        weekday_str=target_weekday,
    )
    right_has = _range_has_occurrence(
        start_date=right_start,
        end_date=right_end,
        weekday_str=target_weekday,
    )

    if not left_has and not right_has:
        await delete_class_by_id(db, class_id)
        await db.commit()
        return ScheduleDeleteOccurrenceOut(ok=True, deleted=True, split=False)

    if left_has and not right_has:
        await update_class_date_range(
            db,
            class_id=class_id,
            start_date=left_start,
            end_date=left_end,
        )
        await db.commit()
        return ScheduleDeleteOccurrenceOut(ok=True, deleted=True, split=False)

    if not left_has and right_has:
        await update_class_date_range(
            db,
            class_id=class_id,
            start_date=right_start,
            end_date=right_end,
        )
        await db.commit()
        return ScheduleDeleteOccurrenceOut(ok=True, deleted=True, split=False)

    await update_class_date_range(
        db,
        class_id=class_id,
        start_date=left_start,
        end_date=left_end,
    )
    await clone_class_with_date_range(
        db,
        source=cls,
        start_date=right_start,
        end_date=right_end,
    )
    await db.commit()
    return ScheduleDeleteOccurrenceOut(ok=True, deleted=True, split=True)


# ── Weekly schedule ──────────────────────────────────────────────────────────

def _week_bounds(reference: date) -> tuple[date, date]:
    """Return (monday, sunday) of the week containing reference."""
    monday = reference - timedelta(days=reference.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


async def get_weekly_schedule(
    db: AsyncSession,
    *,
    user_email: str,
    reference_date: date,
) -> WeeklyScheduleOut:
    schedule_id = await get_active_schedule_id(db, user_email)
    if schedule_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schedule found for this user. Upload one first.",
        )

    all_classes = await get_classes_with_weekdays(db, schedule_id)
    week_start, week_end = _week_bounds(reference_date)

    occurrences: list[ScheduleClassOccurrenceOut] = []
    for day_offset in range(7):
        day = week_start + timedelta(days=day_offset)
        weekday_str = _PYTHON_WEEKDAY_MAP[day.weekday()]

        for cls in all_classes:
            if (
                weekday_str in cls.weekdays
                and cls.start_date <= day <= cls.end_date
            ):
                occurrences.append(
                    ScheduleClassOccurrenceOut(
                        class_id=cls.class_id,
                        title=cls.title,
                        location_text=cls.location_text,
                        room_id=cls.room_id,
                        date=day,
                        weekday=weekday_str,
                        start_time=cls.start_time,
                        end_time=cls.end_time,
                    )
                )

    occurrences.sort(key=lambda o: (o.date, o.start_time))

    return WeeklyScheduleOut(
        week_start=week_start,
        week_end=week_end,
        occurrences=occurrences,
    )


# ── Free-room discovery ──────────────────────────────────────────────────────

def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _minutes_to_time(m: int) -> time:
    return time(m // 60, m % 60)


def _compute_free_slots(
    occupied: list[tuple[time, time]],
) -> list[tuple[time, time]]:
    """Return free time windows within CAMPUS_START..CAMPUS_END."""
    if not occupied:
        return [(CAMPUS_START, CAMPUS_END)]

    # Sort and merge overlapping occupied intervals
    occupied_sorted = sorted(occupied, key=lambda x: x[0])
    merged: list[tuple[time, time]] = [occupied_sorted[0]]
    for s, e in occupied_sorted[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))

    free: list[tuple[time, time]] = []
    cursor = CAMPUS_START
    for occ_start, occ_end in merged:
        if occ_start > cursor:
            free.append((cursor, occ_start))
        cursor = max(cursor, occ_end)
    if cursor < CAMPUS_END:
        free.append((cursor, CAMPUS_END))

    # Filter out very short slots
    return [
        (s, e)
        for s, e in free
        if _time_to_minutes(e) - _time_to_minutes(s) >= MIN_FREE_SLOT_MINUTES
    ]


async def get_free_rooms_for_day(
    db: AsyncSession,
    *,
    user_email: str,
    target_date: date,
) -> FreeRoomsForDayOut:
    schedule_id = await get_active_schedule_id(db, user_email)
    if schedule_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schedule found for this user. Upload one first.",
        )

    all_classes = await get_classes_with_weekdays(db, schedule_id)
    weekday_str = _PYTHON_WEEKDAY_MAP[target_date.weekday()]

    # Find classes that occur on target_date
    occupied: list[tuple[time, time]] = [
        (cls.start_time, cls.end_time)
        for cls in all_classes
        if (
            weekday_str in cls.weekdays
            and cls.start_date <= target_date <= cls.end_date
        )
    ]

    free_slots = _compute_free_slots(occupied)

    if not free_slots:
        return FreeRoomsForDayOut(
            date=target_date,
            weekday=weekday_str,
            free_slots=[],
            slots_with_rooms=[],
        )

    db_weekday = _DB_WEEKDAY[weekday_str]
    room_rows = await fetch_rooms_for_windows(
        db,
        weekday=db_weekday,
        target_date=target_date,
        windows=free_slots,
    )

    # Group room availability rules by slot
    slots_with_rooms: list[SlotWithRoomsOut] = []
    for slot_start, slot_end in free_slots:
        # Rooms whose availability rule overlaps this specific slot
        matching: dict[str, RoomInSlotOut] = {}
        for r in room_rows:
            if r.rule_start <= slot_end and r.rule_end >= slot_start:
                if r.room_id not in matching:
                    matching[r.room_id] = RoomInSlotOut(
                        room_id=r.room_id,
                        building_name=r.building_name,
                        capacity=r.capacity,
                        reliability=r.reliability,
                    )
        slots_with_rooms.append(
            SlotWithRoomsOut(
                slot_start=slot_start,
                slot_end=slot_end,
                available_rooms=sorted(
                    matching.values(), key=lambda x: x.room_id
                ),
            )
        )

    return FreeRoomsForDayOut(
        date=target_date,
        weekday=weekday_str,
        free_slots=[FreeSlotOut(start_time=s, end_time=e)
                    for s, e in free_slots],
        slots_with_rooms=slots_with_rooms,
    )


async def get_free_slots_for_day(
    db: AsyncSession,
    *,
    user_email: str,
    target_date: date,
) -> FreeSlotsForDayOut:
    schedule_id = await get_active_schedule_id(db, user_email)
    if schedule_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schedule found for this user. Upload one first.",
        )

    all_classes = await get_classes_with_weekdays(db, schedule_id)
    weekday_str = _PYTHON_WEEKDAY_MAP[target_date.weekday()]

    occupied: list[tuple[time, time]] = [
        (cls.start_time, cls.end_time)
        for cls in all_classes
        if (
            weekday_str in cls.weekdays
            and cls.start_date <= target_date <= cls.end_date
        )
    ]

    free_slots = _compute_free_slots(occupied)

    return FreeSlotsForDayOut(
        date=target_date,
        weekday=weekday_str,
        free_slots=[FreeSlotOut(start_time=s, end_time=e)
                    for s, e in free_slots],
    )

async def get_friend_weekly_schedule(
    db: AsyncSession,
    *,
    requester_email: str,
    target_email: str,
    reference_date: date,
) -> WeeklyScheduleOut:
    if requester_email == target_email:
        return await get_weekly_schedule(
            db,
            user_email=target_email,
            reference_date=reference_date,
        )

    user_res = await db.execute(select(User).where(User.email == target_email))
    target_user = user_res.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if not getattr(target_user, "share_schedule", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This user does not allow others to see their schedule.",
        )

    friends = await list_accepted_friends_for_user(db, user_email=requester_email)
    friend_emails = [friend[0] for friend in friends]

    if target_email not in friend_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be friends with this user to view their schedule.",
        )

    return await get_weekly_schedule(
        db,
        user_email=target_email,
        reference_date=reference_date,
    )
