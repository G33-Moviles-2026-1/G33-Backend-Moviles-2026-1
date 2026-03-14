from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalyticsEvent, Session


async def ensure_session_exists(
    db: AsyncSession,
    *,
    session_id: UUID,
    device_id: str | None,
    user_email: str | None,
) -> None:
    await db.execute(
        insert(Session)
        .values(
            id=session_id,
            device_id=device_id or "unknown",
            user_email=user_email,
        )
        .on_conflict_do_nothing(index_elements=[Session.id])
    )


async def insert_analytics_event(
    db: AsyncSession,
    *,
    session_id: UUID,
    user_email: str | None,
    event_name: str,
    screen: str | None,
    duration_ms: int | None,
    props_json: dict,
) -> None:
    await db.execute(
        insert(AnalyticsEvent).values(
            ts=datetime.now(timezone.utc),
            session_id=session_id,
            user_email=user_email,
            event_name=event_name,
            screen=screen,
            duration_ms=duration_ms,
            props_json=props_json,
        )
    )


# ── Schedule import funnel ────────────────────────────────────────────────────

async def get_schedule_import_funnel_raw(
    db: AsyncSession,
) -> list[tuple[str, int, str, int]]:
    """
    Returns rows of (method, step_number, step, distinct_session_count)
    for all recorded schedule_import_step events.
    """
    method_col = AnalyticsEvent.props_json["method"].astext
    step_number_col = cast(
        AnalyticsEvent.props_json["step_number"].astext, Integer)
    step_col = AnalyticsEvent.props_json["step"].astext

    stmt = (
        select(
            method_col.label("method"),
            step_number_col.label("step_number"),
            step_col.label("step"),
            func.count(func.distinct(
                AnalyticsEvent.session_id)).label("users"),
        )
        .where(AnalyticsEvent.event_name == "schedule_import_step")
        .group_by(method_col, step_number_col, step_col)
        .order_by(method_col, step_number_col)
    )

    result = await db.execute(stmt)
    return [
        (row.method, row.step_number, row.step, row.users)
        for row in result.all()
    ]
