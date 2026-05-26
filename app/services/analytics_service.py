from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from app.db import models
from sqlalchemy import func, select, text, cast, String, Date
from datetime import date, time, datetime, timezone, timedelta

from app.db.repositories.analytics_repo import (
    ensure_session_exists,
    get_schedule_import_funnel_raw,
    insert_analytics_event,
)
from app.db.repositories.friendships_repo import (
    count_accepted_friendships,
    count_total_users,
)
from app.schemas.analytics import (
    AnalyticsEventIn,
    AnalyticsEventOut,
    FavoriteSubmittedAnalyticsOut,
    FriendCountDistributionSourceResponse,
    FriendCountDistributionUserOut,
    FriendshipUserEdgeOut,
    FriendshipNetworkDensityOut,
    FriendshipNetworkDensitySnapshotOut,
    FriendshipNetworkDensitySnapshotsResponse,
    FunnelStepStat,
    MethodFunnelOut,
    RoomGapSearchEventIn,
    RoomGapSearchEventOut,
    SCHEDULE_IMPORT_STEPS,
    ScheduleImportFunnelOut,
    ScheduleImportStepIn,
    ScheduleImportStepOut,
    RecommendationWeightsOut,
    BookingRoomRecommendationWeightsOut,
    BookingRoomSpecAnalyticsOut,
    BookingRoomSpecsAnalyticsResponse,
)
from app.services.rooms_service import (
    AVAILABILITY_WEIGHT,
    BUILDING_WEIGHT,
    CAPACITY_WEIGHT,
    FLOOR_WEIGHT,
    UTILITY_WEIGHT,
)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)

def _time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _duration_minutes(start: time, end: time) -> int:
    return max(0, _time_to_minutes(end) - _time_to_minutes(start))


def _infer_floor(room_id: str | None) -> int | None:
    if not room_id:
        return None

    parts = room_id.strip().split()
    if len(parts) < 2:
        return None

    room_number = parts[-1]
    if not room_number or not room_number[0].isdigit():
        return None

    return int(room_number[0])

async def track_analytics_event(
    db: AsyncSession,
    payload: AnalyticsEventIn,
) -> AnalyticsEventOut:
    await ensure_session_exists(
        db,
        session_id=payload.session_id,
        device_id=payload.device_id,
        user_email=payload.user_email,
    )

    await insert_analytics_event(
        db,
        session_id=payload.session_id,
        user_email=payload.user_email,
        event_name=payload.event_name,
        screen=payload.screen,
        duration_ms=payload.duration_ms,
        props_json=payload.props_json,
    )

    await db.commit()
    return AnalyticsEventOut(ok=True)


# ── Schedule import funnel ────────────────────────────────────────────────────

async def track_schedule_import_step(
    db: AsyncSession,
    payload: ScheduleImportStepIn,
) -> ScheduleImportStepOut:
    await ensure_session_exists(
        db,
        session_id=payload.session_id,
        device_id=payload.device_id,
        user_email=payload.user_email,
    )

    step_timestamp = payload.timestamp or datetime.now(timezone.utc)
    if step_timestamp.tzinfo is None:
        step_timestamp = step_timestamp.replace(tzinfo=timezone.utc)

    await insert_analytics_event(
        db,
        session_id=payload.session_id,
        user_email=payload.user_email,
        event_name="schedule_import_step",
        screen="schedule_import",
        duration_ms=None,
        props_json={
            "method": payload.method,
            "step": payload.step,
            "step_number": payload.step_number,
            **payload.props_json,
            "timestamp": step_timestamp.isoformat(),
        },
    )

    await db.commit()
    return ScheduleImportStepOut(ok=True)


async def get_user_screen_time_distribution(
    db: AsyncSession
):
    subq = (
        select(
            cast(models.AnalyticsEvent.ts, Date).label("event_date"),
            models.AnalyticsEvent.screen,
            func.coalesce(
                models.AnalyticsEvent.user_email, 
                cast(models.AnalyticsEvent.session_id, String)
            ).label("user_email"),
            models.AnalyticsEvent.ts,
            func.lead(models.AnalyticsEvent.ts)
            .over(partition_by=models.AnalyticsEvent.session_id, order_by=models.AnalyticsEvent.ts)
            .label("next_ts")
        )
        .where(models.AnalyticsEvent.event_name == "open_screen_timestamp")
    )

    subq = subq.subquery()

    stmt = (
        select(
            subq.c.event_date,
            subq.c.screen,
            subq.c.user_email,
            func.sum(
                func.extract("epoch", subq.c.next_ts - subq.c.ts)
            ).label("total_seconds")
        )
        .where(subq.c.next_ts != None)
        .where(func.extract("epoch", subq.c.next_ts - subq.c.ts) < 1800)
        .group_by(subq.c.event_date, subq.c.screen, subq.c.user_email)
        .order_by(subq.c.event_date.desc(), subq.c.screen, text("total_seconds DESC"))
    )

    result = await db.execute(stmt)
    
    return [
        {
            "date": row.event_date,
            "screen": row.screen,
            "user_email": row.user_email,
            "total_seconds": round(float(row.total_seconds), 2)
        }
        for row in result.all()
    ]

async def track_room_gap_search_event(
    db: AsyncSession,
    payload: RoomGapSearchEventIn,
) -> RoomGapSearchEventOut:
    await ensure_session_exists(
        db,
        session_id=payload.session_id,
        device_id=payload.device_id,
        user_email=payload.user_email,
    )

    await insert_analytics_event(
        db,
        session_id=payload.session_id,
        user_email=payload.user_email,
        event_name="room_gap_search_submitted",
        screen="rooms",
        duration_ms=None,
        props_json={
            "date_value": payload.date_value.isoformat(),
            "gap_start": payload.gap_start.isoformat(),
            "gap_end": payload.gap_end.isoformat(),
            "utilities": [u.value for u in payload.utilities],
            **payload.props_json,
        },
    )

    await db.commit()
    return RoomGapSearchEventOut(ok=True)


FAVORITE_SUBMITTED_EVENT_NAME = "favorite_submitted"


async def get_favorites_submitted_analytics(
    db: AsyncSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    building_code: str | None = None,
) -> list[FavoriteSubmittedAnalyticsOut]:
    room_id_col = models.AnalyticsEvent.props_json["room_id"].astext
    action_col = models.AnalyticsEvent.props_json["action"].astext

    stmt = (
        select(
            models.AnalyticsEvent.session_id,
            models.AnalyticsEvent.user_email,
            models.AnalyticsEvent.ts,
            models.AnalyticsEvent.screen,
            room_id_col.label("room_id"),
            action_col.label("action"),
            models.Room.building_code,
            models.Room.room_number,
            models.AnalyticsEvent.props_json,
        )
        .outerjoin(models.Room, models.Room.id == room_id_col)
        .where(models.AnalyticsEvent.event_name == FAVORITE_SUBMITTED_EVENT_NAME)
    )

    if start_date is not None:
        stmt = stmt.where(cast(models.AnalyticsEvent.ts, Date) >= start_date)
    if end_date is not None:
        stmt = stmt.where(cast(models.AnalyticsEvent.ts, Date) <= end_date)

    normalized_building = (
        building_code.strip().upper() if building_code else None
    )
    if normalized_building:
        stmt = stmt.where(models.Room.building_code == normalized_building)

    stmt = stmt.order_by(models.AnalyticsEvent.ts.desc())
    result = await db.execute(stmt)

    return [
        FavoriteSubmittedAnalyticsOut(
            session_id=row.session_id,
            user_email=row.user_email,
            ts=row.ts,
            event_date=row.ts.date(),
            screen=row.screen,
            room_id=row.room_id,
            action=row.action,
            building_code=row.building_code,
            room_number=row.room_number,
            props_json=row.props_json or {},
        )
        for row in result.all()
    ]


FRIENDSHIP_NETWORK_DENSITY_EVENT_NAME = "friendship_network_density_snapshot"
SYSTEM_ANALYTICS_SESSION_ID = UUID("00000000-0000-4000-8000-000000000001")


def _max_possible_friendships(total_users: int) -> int:
    if total_users < 2:
        return 0
    return total_users * (total_users - 1) // 2


def _build_friendship_network_density(
    *,
    total_users: int,
    accepted_friendships: int,
    computed_at: datetime | None = None,
) -> FriendshipNetworkDensityOut:
    max_possible = _max_possible_friendships(total_users)
    density_ratio = (
        accepted_friendships / max_possible if max_possible > 0 else 0.0
    )

    return FriendshipNetworkDensityOut(
        computed_at=computed_at or datetime.now(timezone.utc),
        total_users=total_users,
        accepted_friendships=accepted_friendships,
        max_possible_friendships=max_possible,
        density_ratio=round(density_ratio, 6),
        density_pct=round(density_ratio * 100, 2),
    )


async def compute_friendship_network_density(
    db: AsyncSession,
) -> FriendshipNetworkDensityOut:
    total_users = await count_total_users(db)
    accepted_friendships = await count_accepted_friendships(db)
    return _build_friendship_network_density(
        total_users=total_users,
        accepted_friendships=accepted_friendships,
    )


def _density_from_props(
    props: dict,
    *,
    session_id: UUID,
    ts: datetime,
) -> FriendshipNetworkDensitySnapshotOut | None:
    if not props:
        return None

    try:
        computed_at_raw = props.get("computed_at")
        if isinstance(computed_at_raw, str):
            computed_at = datetime.fromisoformat(
                computed_at_raw.replace("Z", "+00:00")
            )
        else:
            computed_at = ts

        return FriendshipNetworkDensitySnapshotOut(
            session_id=session_id,
            computed_at=computed_at,
            total_users=int(props["total_users"]),
            accepted_friendships=int(props["accepted_friendships"]),
            max_possible_friendships=int(props["max_possible_friendships"]),
            density_ratio=float(props["density_ratio"]),
            density_pct=float(props["density_pct"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def record_friendship_network_density_snapshot(
    db: AsyncSession,
) -> FriendshipNetworkDensityOut:
    metrics = await compute_friendship_network_density(db)

    await ensure_session_exists(
        db,
        session_id=SYSTEM_ANALYTICS_SESSION_ID,
        device_id="backend-snapshot",
        user_email=None,
    )

    await insert_analytics_event(
        db,
        session_id=SYSTEM_ANALYTICS_SESSION_ID,
        user_email=None,
        event_name=FRIENDSHIP_NETWORK_DENSITY_EVENT_NAME,
        screen="analytics",
        duration_ms=None,
        props_json={
            "total_users": metrics.total_users,
            "accepted_friendships": metrics.accepted_friendships,
            "max_possible_friendships": metrics.max_possible_friendships,
            "density_ratio": metrics.density_ratio,
            "density_pct": metrics.density_pct,
            "computed_at": metrics.computed_at.isoformat(),
        },
    )

    await db.commit()
    return metrics


async def get_friendship_network_density_snapshots(
    db: AsyncSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> FriendshipNetworkDensitySnapshotsResponse:
    stmt = select(models.AnalyticsEvent).where(
        models.AnalyticsEvent.event_name == FRIENDSHIP_NETWORK_DENSITY_EVENT_NAME
    )

    if start_date is not None:
        stmt = stmt.where(cast(models.AnalyticsEvent.ts, Date) >= start_date)
    if end_date is not None:
        stmt = stmt.where(cast(models.AnalyticsEvent.ts, Date) <= end_date)

    stmt = stmt.order_by(models.AnalyticsEvent.ts.desc())
    result = await db.execute(stmt)

    items: list[FriendshipNetworkDensitySnapshotOut] = []
    for event in result.scalars().all():
        snapshot = _density_from_props(
            event.props_json or {},
            session_id=event.session_id,
            ts=event.ts,
        )
        if snapshot is not None:
            items.append(snapshot)

    return FriendshipNetworkDensitySnapshotsResponse(
        total=len(items),
        items=items,
    )


async def get_screen_time_stats(db: AsyncSession):
    subq = (
        select(
            models.AnalyticsEvent.screen,
            models.AnalyticsEvent.ts,
            func.lead(models.AnalyticsEvent.ts)
            .over(partition_by=models.AnalyticsEvent.session_id, order_by=models.AnalyticsEvent.ts)
            .label("next_ts")
        )
        .where(models.AnalyticsEvent.event_name == "open_screen_timestamp")
        .subquery()
    )
    stmt = (
        select(
            subq.c.screen,
            func.sum(
                func.extract("epoch", subq.c.next_ts - subq.c.ts)
            ).label("total_seconds")
        )
        .where(subq.c.next_ts != None)
        .group_by(subq.c.screen)
        .order_by(text("total_seconds DESC"))
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "screen": row.screen,
            "total_seconds": round(float(row.total_seconds), 2)
        }
        for row in rows
    ]


async def get_schedule_import_funnel(
    db: AsyncSession,
) -> ScheduleImportFunnelOut:
    """
    Answers BQ: 'What is the most common way users upload/import their
    schedule, and which method has the highest drop-off by step?'
    """
    raw = await get_schedule_import_funnel_raw(db)

    # Build {method: {step_number: (step_name, user_count)}}
    data: dict[str, dict[int, tuple[str, int]]] = {}
    for method, step_number, step, users in raw:
        data.setdefault(method, {})[step_number] = (step, users)

    # Ensure all known methods appear even with zero data
    for method in SCHEDULE_IMPORT_STEPS:
        data.setdefault(method, {})

    method_funnels: list[MethodFunnelOut] = []
    for method, step_definitions in SCHEDULE_IMPORT_STEPS.items():
        step_stats: list[FunnelStepStat] = []
        prev_users: int | None = None

        for step_number, step_name in enumerate(step_definitions, start=1):
            step_data = data[method].get(step_number)
            users = step_data[1] if step_data else 0

            dropoff_pct: float | None = None
            if prev_users is not None and prev_users > 0:
                dropoff_pct = round(
                    (prev_users - users) / prev_users * 100, 1
                )
            elif prev_users == 0:
                dropoff_pct = None

            step_stats.append(
                FunnelStepStat(
                    step_number=step_number,
                    step=step_name,
                    users_reached=users,
                    dropoff_from_prev_pct=dropoff_pct,
                )
            )
            prev_users = users

        total_started = step_stats[0].users_reached if step_stats else 0
        total_completed = step_stats[-1].users_reached if step_stats else 0
        completion_rate = (
            round(total_completed / total_started * 100, 1)
            if total_started > 0
            else 0.0
        )

        method_funnels.append(
            MethodFunnelOut(
                method=method,
                total_started=total_started,
                total_completed=total_completed,
                completion_rate_pct=completion_rate,
                steps=step_stats,
            )
        )

    # Most common method = highest total_started
    most_common = max(
        method_funnels, key=lambda m: m.total_started, default=None)

    # Highest drop-off method = worst max step-to-step drop-off rate
    def _worst_dropoff(mf: MethodFunnelOut) -> float:
        rates = [
            s.dropoff_from_prev_pct
            for s in mf.steps
            if s.dropoff_from_prev_pct is not None
        ]
        return max(rates) if rates else 0.0

    highest_dropoff = max(method_funnels, key=_worst_dropoff, default=None)

    return ScheduleImportFunnelOut(
        most_common_method=most_common.method if most_common and most_common.total_started > 0 else None,
        highest_dropoff_method=highest_dropoff.method if highest_dropoff and _worst_dropoff(
            highest_dropoff) > 0 else None,
        methods=method_funnels,
    )

async def get_friend_count_distribution_source(
    db: AsyncSession,
) -> FriendCountDistributionSourceResponse:
    """
    Dataset for the business question:
    'Given a range of dates, what is the distribution of number of friends per user?'

    This endpoint intentionally returns granular source tables for Power BI:
    - users: all registered users, including users with zero friends.
    - relationship_user_edges: one accepted friendship becomes two directed edges.

    Power BI should filter relationship_user_edges by accepted_date, count distinct
    friend_email per user_email, then group users by that friend count.
    """

    users_result = await db.execute(
        select(
            models.User.email,
            models.User.username,
        ).order_by(
            func.lower(models.User.username).asc(),
            models.User.email.asc(),
        )
    )

    users = [
        FriendCountDistributionUserOut(
            user_email=row.email,
            username=row.username or row.email.split("@", 1)[0],
        )
        for row in users_result.all()
    ]

    accepted_at_expr = func.coalesce(
        models.Friendship.accepted_at,
        models.Friendship.created_at,
    ).label("accepted_at")

    friendships_result = await db.execute(
        select(
            models.Friendship.correo_amigo_1,
            models.Friendship.correo_amigo_2,
            accepted_at_expr,
        )
        .where(models.Friendship.estado == models.FriendshipStatus.accepted.value)
        .order_by(
            accepted_at_expr.asc(),
            models.Friendship.correo_amigo_1.asc(),
            models.Friendship.correo_amigo_2.asc(),
        )
    )

    relationship_user_edges: list[FriendshipUserEdgeOut] = []

    for row in friendships_result.all():
        email_1 = row.correo_amigo_1
        email_2 = row.correo_amigo_2
        accepted_at = row.accepted_at

        if accepted_at is None:
            continue

        friendship_user_pair_key = "|".join(sorted([email_1, email_2]))
        accepted_date = accepted_at.date()

        relationship_user_edges.append(
            FriendshipUserEdgeOut(
                accepted_at=accepted_at,
                accepted_date=accepted_date,
                friendship_user_pair_key=friendship_user_pair_key,
                user_email=email_1,
                friend_email=email_2,
            )
        )

        relationship_user_edges.append(
            FriendshipUserEdgeOut(
                accepted_at=accepted_at,
                accepted_date=accepted_date,
                friendship_user_pair_key=friendship_user_pair_key,
                user_email=email_2,
                friend_email=email_1,
            )
        )

    return FriendCountDistributionSourceResponse(
        users=users,
        relationship_user_edges=relationship_user_edges,
    )

async def get_booking_room_specs_analytics(
    db: AsyncSession,
) -> BookingRoomSpecsAnalyticsResponse:
    """
    Dataset for the business question:
    'Given a booking creation date range, which room specifications are most
    recommended by the booking-based recommendation system?'

    The endpoint returns all historical booking-room rows. Power BI filters
    locally by booking_created_date.
    """

    scoring_weights = BookingRoomRecommendationWeightsOut(
        building_weight=BUILDING_WEIGHT,
        floor_weight=FLOOR_WEIGHT,
        capacity_weight=CAPACITY_WEIGHT,
        utility_weight=UTILITY_WEIGHT,
        availability_weight=AVAILABILITY_WEIGHT,
    )

    bookings_result = await db.execute(
        select(
            models.Booking.created_at.label("booking_created_at"),
            models.Booking.term_id.label("term_id"),

            models.Room.id.label("room_id"),
            models.Room.building_code.label("building_code"),
            func.coalesce(models.Room.building_name, models.Building.name).label("building_name"),
            models.Room.room_number.label("room_number"),
            models.Room.capacity.label("capacity"),
            models.Room.reliability.label("reliability"),
        )
        .join(models.Room, models.Room.id == models.Booking.room_id)
        .outerjoin(models.Building, models.Building.code == models.Room.building_code)
        .order_by(
            models.Booking.created_at.desc(),
            models.Room.id.asc(),
        )
    )

    booking_rows = bookings_result.all()

    if not booking_rows:
        return BookingRoomSpecsAnalyticsResponse(
            total=0,
            scoring_weights=scoring_weights,
            items=[],
        )

    room_ids = sorted({row.room_id for row in booking_rows})
    term_ids = sorted({row.term_id for row in booking_rows})

    utilities_result = await db.execute(
        select(
            models.RoomUtility.room_id,
            models.RoomUtility.utility,
        )
        .where(models.RoomUtility.room_id.in_(room_ids))
        .order_by(
            models.RoomUtility.room_id.asc(),
            models.RoomUtility.utility.asc(),
        )
    )

    utilities_map: dict[str, list[str]] = {}
    for room_id, utility in utilities_result.all():
        utilities_map.setdefault(room_id, []).append(_enum_value(utility))

    availability_result = await db.execute(
        select(
            models.RoomAvailabilityRule.term_id,
            models.RoomAvailabilityRule.room_id,
            func.count(models.RoomAvailabilityRule.id).label("availability_window_count"),
            func.sum(
                (
                    func.extract("epoch", models.RoomAvailabilityRule.end_time)
                    - func.extract("epoch", models.RoomAvailabilityRule.start_time)
                ) / 60
            ).label("total_weekly_available_minutes"),
        )
        .where(
            models.RoomAvailabilityRule.room_id.in_(room_ids),
            models.RoomAvailabilityRule.term_id.in_(term_ids),
        )
        .group_by(
            models.RoomAvailabilityRule.term_id,
            models.RoomAvailabilityRule.room_id,
        )
    )

    availability_map: dict[tuple[str, str], tuple[int, int]] = {}

    for term_id, room_id, window_count, total_minutes in availability_result.all():
        availability_map[(term_id, room_id)] = (
            int(window_count or 0),
            int(total_minutes or 0),
        )

    items: list[BookingRoomSpecAnalyticsOut] = []

    for row in booking_rows:
        utilities = utilities_map.get(row.room_id, [])
        availability_window_count, total_weekly_available_minutes = availability_map.get(
            (row.term_id, row.room_id),
            (0, 0),
        )

        items.append(
            BookingRoomSpecAnalyticsOut(
                booking_created_date=row.booking_created_at.date(),

                room_id=row.room_id,
                building_code=row.building_code,
                building_name=row.building_name,
                room_number=row.room_number,
                room_floor=_infer_floor(row.room_id),
                capacity=row.capacity,
                reliability=float(row.reliability),

                utilities=utilities,
                utility_count=len(utilities),

                availability_window_count=availability_window_count,
                total_weekly_available_minutes=total_weekly_available_minutes,
            )
        )

    return BookingRoomSpecsAnalyticsResponse(
        total=len(items),
        scoring_weights=scoring_weights,
        items=items,
    )