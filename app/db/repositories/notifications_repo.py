from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Notification, NotificationType


async def insert_notification(
    db: AsyncSession,
    *,
    user_email: str,
    type: NotificationType,
    payload: dict,
) -> Notification:
    notification = Notification(
        user_email=user_email,
        type=type,
        payload=payload,
    )
    db.add(notification)
    await db.flush()
    return notification


async def list_notifications_for_user(
    db: AsyncSession,
    *,
    user_email: str,
    limit: int = 50,
) -> list[Notification]:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_email == user_email)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def mark_notification_read(
    db: AsyncSession,
    *,
    notification_id: UUID,
    user_email: str,
) -> bool:
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_email == user_email,
        )
        .values(is_read=True)
    )
    await db.commit()
    return result.rowcount > 0


async def mark_all_notifications_read(
    db: AsyncSession,
    *,
    user_email: str,
) -> int:
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_email == user_email,
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True)
    )
    await db.commit()
    return result.rowcount


async def delete_notification(
    db: AsyncSession,
    *,
    notification_id: UUID,
    user_email: str,
) -> bool:
    result = await db.execute(
        delete(Notification).where(
            Notification.id == notification_id,
            Notification.user_email == user_email,
        )
    )
    await db.commit()
    return result.rowcount > 0


async def delete_friend_request_notification(
    db: AsyncSession,
    *,
    recipient_email: str,
    requester_email: str,
) -> None:
    """Delete the friend_request_received notification sent by requester to recipient."""
    await db.execute(
        delete(Notification).where(
            Notification.user_email == recipient_email,
            Notification.type == NotificationType.friend_request_received,
            Notification.payload["from_email"].as_string() == requester_email,
        )
    )
    await db.commit()


async def delete_read_notifications(
    db: AsyncSession,
    *,
    user_email: str,
) -> int:
    result = await db.execute(
        delete(Notification).where(
            Notification.user_email == user_email,
            Notification.is_read == True,  # noqa: E712
        )
    )
    await db.commit()
    return result.rowcount
