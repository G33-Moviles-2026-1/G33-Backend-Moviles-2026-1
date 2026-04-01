from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.favorites import CreateFavoriteRequest, FavoriteOut, MyFavoritesResponse
from app.services.favorites_service import create_favorite, delete_my_favorite, get_my_favorites

router = APIRouter(prefix="/favorites", tags=["favorites"])


def _require_active_user_email(request: Request) -> str:
    user_email = request.session.get("user_name")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="There is no active session",
        )
    return user_email


@router.post("/", response_model=FavoriteOut, status_code=status.HTTP_201_CREATED)
async def create_favorite_endpoint(
    payload: CreateFavoriteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FavoriteOut:
    user_email = _require_active_user_email(request)
    return await create_favorite(
        db,
        user_email=user_email,
        payload=payload,
    )


@router.get("/mine", response_model=MyFavoritesResponse)
async def my_favorites_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MyFavoritesResponse:
    user_email = _require_active_user_email(request)
    return await get_my_favorites(
        db,
        user_email=user_email,
    )


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_favorite_endpoint(
    room_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    user_email = _require_active_user_email(request)
    normalized_room_id = " ".join(room_id.upper().split())

    await delete_my_favorite(
        db,
        user_email=user_email,
        room_id=normalized_room_id,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
