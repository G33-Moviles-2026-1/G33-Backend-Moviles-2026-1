from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.analytics_repo import (
    ensure_session_exists,
    insert_analytics_event,
)
from app.schemas.analytics import AnalyticsEventIn, AnalyticsEventOut


async def track_homepage_event(
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