from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.bookings import BookingOut, CreateBookingRequest, MyBookingsResponse
from app.services.bookings_service import create_booking, delete_my_booking, get_my_bookings

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


@router.get("/mine", response_model=MyBookingsResponse)
async def my_bookings_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MyBookingsResponse:
    user_email = _require_active_user_email(request)
    return await get_my_bookings(
        db,
        user_email=user_email,
    )


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_booking_endpoint(
    booking_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    user_email = _require_active_user_email(request)

    await delete_my_booking(
        db,
        user_email=user_email,
        booking_id=booking_id,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)