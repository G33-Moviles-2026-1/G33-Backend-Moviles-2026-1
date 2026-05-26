from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.repositories.notifications_repo import (
    delete_notification,
    delete_read_notifications,
    list_notifications_for_user,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.schemas.notifications import NotificationOut, NotificationsResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _require_active_user_email(request: Request) -> str:
    user_email = request.session.get("user_name")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="There is no active session",
        )
    return user_email


@router.get("/", response_model=NotificationsResponse)
async def list_my_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> NotificationsResponse:
    user_email = _require_active_user_email(request)
    notifications = await list_notifications_for_user(db, user_email=user_email)
    unread = sum(1 for n in notifications if not n.is_read)
    return NotificationsResponse(
        total=len(notifications),
        unread=unread,
        items=[NotificationOut.model_validate(n) for n in notifications],
    )


@router.put("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_read(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user_email = _require_active_user_email(request)
    updated = await mark_all_notifications_read(db, user_email=user_email)
    return {"updated": updated}


@router.put("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_one_read(
    notification_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user_email = _require_active_user_email(request)
    found = await mark_notification_read(
        db, notification_id=notification_id, user_email=user_email
    )
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return {"message": "Marked as read"}


@router.delete("/read", status_code=status.HTTP_200_OK)
async def delete_all_read(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user_email = _require_active_user_email(request)
    deleted = await delete_read_notifications(db, user_email=user_email)
    return {"deleted": deleted}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_one(
    notification_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    user_email = _require_active_user_email(request)
    found = await delete_notification(
        db, notification_id=notification_id, user_email=user_email
    )
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
