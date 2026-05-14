from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.db.models import NotificationType


class NotificationOut(BaseModel):
    id: UUID
    type: NotificationType
    payload: dict
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationsResponse(BaseModel):
    total: int
    unread: int
    items: list[NotificationOut]
