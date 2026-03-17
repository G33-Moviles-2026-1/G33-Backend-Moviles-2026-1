from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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
    FreeRoomsForDayOut,
    FreeSlotOut,
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
CAMPUS_START = time(6, 0)
CAMPUS_END = time(22, 0)

# Minimum free slot to surface (minutes)
MIN_FREE_SLOT_MINUTES = 30

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
    if not m:
        return None
    raw = m.group(1).strip().rstrip(",;")
    return raw.replace("_", " ")


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


async def _sanitize_room_ids(
    db: AsyncSession,
    classes: list[ClassInputData],
) -> list[str]:
    """Set unknown room IDs to None to avoid FK failures and return warnings."""
    raw_room_ids = sorted({c.room_id for c in classes if c.room_id})
    found = await existing_room_ids(db, raw_room_ids)

    warnings: list[str] = []
    for c in classes:
        if c.room_id and c.room_id not in found:
            warnings.append(
                f"Room '{c.room_id}' was not found in DB. Saved as location text only."
            )
            c.room_id = None
    return warnings


# ── Public service functions ─────────────────────────────────────────────────

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
            if r.rule_start < slot_end and r.rule_end > slot_start:
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
