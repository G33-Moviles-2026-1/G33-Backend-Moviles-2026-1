from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

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