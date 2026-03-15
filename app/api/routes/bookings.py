from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.bookings import BookingOut, CreateBookingRequest
from app.services.bookings_service import create_booking

router = APIRouter(prefix="/bookings", tags=["bookings"])


def _require_active_user_email(request: Request) -> str:
    user_email = request.session.get("user_name")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="There is no active session",
        )
    return user_email


@router.post("/", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking_endpoint(
    payload: CreateBookingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> BookingOut:
    user_email = _require_active_user_email(request)
    return await create_booking(
        db,
        user_email=user_email,
        payload=payload,
    )