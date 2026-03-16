from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.analytics import AnalyticsEventIn, AnalyticsEventOut
from app.services.analytics_service import track_analytics_event

router = APIRouter(prefix="/analytics", tags=["analytics"])


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