from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationType, UserStatus
from app.db.repositories.friendships_repo import (
    get_accepted_friends_emails_not_incognito,
    get_user_info,
    get_user_status,
)
from app.db.repositories.notifications_repo import insert_notification
from app.schemas.bookings import BookingOut


async def notify_friends_of_booking(
    db: AsyncSession,
    *,
    booking_user_email: str,
    booking_user_username: str,
    booking: BookingOut,
) -> None:
    sender_status = await get_user_status(db, user_email=booking_user_email)
    if sender_status == UserStatus.incognito:
        return

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


async def notify_friend_request_received(
    db: AsyncSession,
    *,
    requester_email: str,
    recipient_email: str,
) -> None:
    requester_info = await get_user_info(db, user_email=requester_email)
    if requester_info is None:
        return
    _, requester_username = requester_info

    await insert_notification(
        db,
        user_email=recipient_email,
        type=NotificationType.friend_request_received,
        payload={"from_username": requester_username, "from_email": requester_email},
    )
    await db.commit()


async def notify_friend_request_accepted(
    db: AsyncSession,
    *,
    acceptor_email: str,
    requester_email: str,
) -> None:
    acceptor_info = await get_user_info(db, user_email=acceptor_email)
    if acceptor_info is None:
        return
    _, acceptor_username = acceptor_info

    await insert_notification(
        db,
        user_email=requester_email,
        type=NotificationType.friend_request_accepted,
        payload={"from_username": acceptor_username, "from_email": acceptor_email},
    )
    await db.commit()
