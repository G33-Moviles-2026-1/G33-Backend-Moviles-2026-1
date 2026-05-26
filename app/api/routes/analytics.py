from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from sqlalchemy import Date, cast, select
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
    FavoriteSubmittedAnalyticsOut,
    FriendCountDistributionSourceResponse,
    FriendshipNetworkDensityOut,
    FriendshipNetworkDensitySnapshotsResponse,
    ScreenTimeResponse,
    BookingRoomSpecsAnalyticsResponse,
)
from app.services.analytics_service import (
    get_schedule_import_funnel,
    track_room_gap_search_event,
    track_analytics_event,
    track_schedule_import_step,
    get_screen_time_stats,
    get_booking_room_specs_analytics,
    get_favorites_submitted_analytics,
    compute_friendship_network_density,
    record_friendship_network_density_snapshot,
    get_friendship_network_density_snapshots,
    get_friend_count_distribution_source,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

FILTER_USAGE_EVENT_NAMES = (
    "home_filters_opened",
    "home_search_submitted",
    "room_gap_search_submitted",
)


def _map_event_out(event: models.AnalyticsEvent) -> AnalyticsEventOutRead:
    return AnalyticsEventOutRead(
        session_id=event.session_id,
        user_email=event.user_email,
        event_name=event.event_name,
        screen=event.screen,
        ts=event.ts,
        event_date=event.ts.date(),
        duration_ms=event.duration_ms,
        props_json=event.props_json,
    )


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
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> List[AnalyticsEventOutRead]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be later than end_date",
        )

    stmt = select(models.AnalyticsEvent).where(models.AnalyticsEvent.event_name == event_name)

    if start_date is not None:
        stmt = stmt.where(cast(models.AnalyticsEvent.ts, Date) >= start_date)
    if end_date is not None:
        stmt = stmt.where(cast(models.AnalyticsEvent.ts, Date) <= end_date)

    stmt = stmt.order_by(models.AnalyticsEvent.ts.desc())
    result = await db.execute(stmt)
    events = result.scalars().all()
    return [_map_event_out(event) for event in events]


@router.get(
    "/filters-used",
    response_model=List[AnalyticsEventOutRead],
    summary="List filter-usage analytics events for Power BI",
)
async def list_filters_used_events(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> List[AnalyticsEventOutRead]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be later than end_date",
        )

    stmt = select(models.AnalyticsEvent).where(
        models.AnalyticsEvent.event_name.in_(FILTER_USAGE_EVENT_NAMES)
    )

    if start_date is not None:
        stmt = stmt.where(cast(models.AnalyticsEvent.ts, Date) >= start_date)
    if end_date is not None:
        stmt = stmt.where(cast(models.AnalyticsEvent.ts, Date) <= end_date)

    stmt = stmt.order_by(models.AnalyticsEvent.ts.desc())
    result = await db.execute(stmt)
    events = result.scalars().all()
    return [_map_event_out(event) for event in events]


@router.get(
    "/favorites-submitted",
    response_model=List[FavoriteSubmittedAnalyticsOut],
    summary="List favorite_submitted analytics events for Power BI",
    description=(
        "Returns favorite_submitted events enriched with room_id, action, "
        "building_code and room_number. Filter by date range and optionally "
        "by building (e.g. ML). Power BI can connect via Web to this URL."
    ),
)
async def list_favorites_submitted_events(
    start_date: date | None = None,
    end_date: date | None = None,
    building_code: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> List[FavoriteSubmittedAnalyticsOut]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be later than end_date",
        )

    return await get_favorites_submitted_analytics(
        db,
        start_date=start_date,
        end_date=end_date,
        building_code=building_code,
    )


@router.get(
    "/friendship-network-density",
    response_model=FriendshipNetworkDensityOut,
    summary="Current friendship network density (live)",
    description=(
        "Density = accepted_friendships / max_possible_friendships, where "
        "max_possible = total_users * (total_users - 1) / 2 among all registered users."
    ),
)
async def friendship_network_density_live(
    db: AsyncSession = Depends(get_db),
) -> FriendshipNetworkDensityOut:
    return await compute_friendship_network_density(db)


@router.post(
    "/friendship-network-density/snapshot",
    response_model=FriendshipNetworkDensityOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record friendship network density snapshot for Power BI history",
    description=(
        "Computes density, stores a friendship_network_density_snapshot "
        "analytics event, and returns the metrics. Call on a schedule (e.g. daily) "
        "to build a time series in Power BI."
    ),
)
async def friendship_network_density_snapshot(
    db: AsyncSession = Depends(get_db),
) -> FriendshipNetworkDensityOut:
    return await record_friendship_network_density_snapshot(db)


@router.get(
    "/friendship-network-density/snapshots",
    response_model=FriendshipNetworkDensitySnapshotsResponse,
    summary="List friendship network density snapshots for Power BI",
)
async def friendship_network_density_snapshots(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> FriendshipNetworkDensitySnapshotsResponse:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be later than end_date",
        )

    return await get_friendship_network_density_snapshots(
        db,
        start_date=start_date,
        end_date=end_date,
    )

@router.get(
    "/friend-count-distribution-source",
    response_model=FriendCountDistributionSourceResponse,
    summary="Source dataset for friend-count distribution per user",
    description=(
        "Returns the source tables needed by Power BI to answer: "
        "'Given a range of dates, what is the distribution of number of friends per user?' "
        "The response includes all users, including users with zero friends, and directed "
        "relationship edges for accepted friendships. Power BI should filter edges locally "
        "by accepted_date, count distinct friend_email per user_email, then group users by "
        "that friend count."
    ),
)
async def friend_count_distribution_source(
    db: AsyncSession = Depends(get_db),
) -> FriendCountDistributionSourceResponse:
    return await get_friend_count_distribution_source(db)


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

@router.get(
    "/bookings-room-specs",
    response_model=BookingRoomSpecsAnalyticsResponse,
    summary="Analytics dataset for booking-based room recommendation specs",
    description=(
        "Returns all historical bookings enriched with the room specifications "
        "needed to reproduce booking-based recommendation scoring in Power BI. "
        "Power BI should filter locally by booking_created_date."
    ),
)
async def booking_room_specs_analytics(
    db: AsyncSession = Depends(get_db),
) -> BookingRoomSpecsAnalyticsResponse:
    return await get_booking_room_specs_analytics(db)