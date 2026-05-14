from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationType
from app.db.repositories.friendships_repo import get_accepted_friends_emails_not_incognito
from app.db.repositories.notifications_repo import insert_notification
from app.schemas.bookings import BookingOut


async def notify_friends_of_booking(
    db: AsyncSession,
    *,
    booking_user_email: str,
    booking_user_username: str,
    booking: BookingOut,
) -> None:
    friend_emails = await get_accepted_friends_emails_not_incognito(
        db, user_email=booking_user_email
    )

    for email in friend_emails:
        await insert_notification(
            db,
            user_email=email,
            type=NotificationType.friend_booking,
            payload={
                "friend_username": booking_user_username,
                "room_id": booking.room_id,
                "date": str(booking.date),
                "start_time": str(booking.start_time),
                "end_time": str(booking.end_time),
            },
        )

    if friend_emails:
        await db.commit()
