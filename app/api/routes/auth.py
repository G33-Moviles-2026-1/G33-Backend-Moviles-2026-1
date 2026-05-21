import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from ...db import models, session
from ...schemas import user as user_schema
from ...services import utils

BOGOTA_TZ = ZoneInfo("America/Bogota")


router = APIRouter(
    tags=["authentication"]
)

def _build_username_base_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0].strip().lower()
    cleaned = re.sub(r"[^a-z0-9._-]", "-", local_part)

    if len(cleaned) < 3:
        cleaned = (cleaned + "000")[:3]

    return cleaned[:25]


async def _username_exists(
    db: Session,
    *,
    username: str,
    exclude_email: str | None = None,
) -> bool:
    stmt = select(models.User.email).where(
        func.lower(models.User.username) == username.lower()
    )

    if exclude_email is not None:
        stmt = stmt.where(models.User.email != exclude_email)

    result = await db.execute(stmt.limit(1))
    return result.scalar_one_or_none() is not None


async def _generate_username_from_email(db: Session, *, email: str) -> str:
    base_username = _build_username_base_from_email(email)

    if not await _username_exists(db, username=base_username):
        return base_username

    for counter in range(1, 10_000):
        suffix = str(counter)
        prefix_length = 25 - len(suffix)
        candidate = f"{base_username[:prefix_length]}{suffix}"

        if not await _username_exists(db, username=candidate):
            return candidate

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="We could not generate a valid username. Please try again.",
    )


async def _get_current_user(request: Request, db: Session) -> models.User:
    user_email = request.session.get("user_name")

    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="There is no active session",
        )

    stmt = select(models.User).where(models.User.email == user_email)
    result = await db.execute(stmt)
    db_user = result.scalars().first()

    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The authenticated user was not found.",
        )

    return db_user

@router.post("/login/")
async def login(user: user_schema.UserAuthenticate, request: Request, db: Session = Depends(session.get_db)):
    stmt = select(models.User).where(models.User.email == user.email)
    result = await db.execute(stmt)
    db_user = result.scalars().first()
    if db_user is None or not utils.compare_hash(user.password, db_user.password_hash):
        raise HTTPException(status_code=403, detail="Email or Password is Incorrect")
    request.session["user_name"] = db_user.email
    return {"message": "Success"}

@router.post("/logout/")
async def logout(request: Request, response: Response):
    user = request.session.get("user_name")
    if not user:
        raise HTTPException(status_code=401, detail="There is no active session")
    request.session.clear()
    response.delete_cookie(key="session")
    return {"message": "Session closed"}

@router.post("/signup/", response_model=user_schema.UserResponse)
async def create_user(
    item: user_schema.UserCreate,
    request: Request,
    db: Session = Depends(session.get_db)
):
    stmt = select(models.User).where(models.User.email == item.email)
    result = await db.execute(stmt)
    existing_user = result.scalars().first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already registered",
        )

    username = item.username
    if username is None:
        username = await _generate_username_from_email(db, email=item.email)
    elif await _username_exists(db, username=username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken. Please choose another one.",
        )

    hashed_pwd = utils.get_hash(item.password)

    db_item = models.User(
        email=item.email,
        password_hash=hashed_pwd,
        first_semester=item.first_semester,
        username=username,
        status=models.UserStatus.incognito,
    )

    db.add(db_item)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken. Please choose another one.",
        )

    await db.refresh(db_item)

    request.session["user_name"] = db_item.email

    return db_item

@router.get("/me/")
async def read_me(request: Request):
    user = request.session.get("user_name")
    if not user:
        raise HTTPException(status_code=401, detail="There is no active session")
    return {"active_user": user}

@router.get("/me/profile", response_model=user_schema.UserProfileResponse)
async def read_my_profile(
    request: Request,
    db: Session = Depends(session.get_db),
):
    return await _get_current_user(request, db)


@router.get("/me/username", response_model=user_schema.UserProfileResponse)
async def read_my_username(
    request: Request,
    db: Session = Depends(session.get_db),
):
    return await _get_current_user(request, db)


@router.put("/me/username", response_model=user_schema.UserProfileResponse)
async def update_my_username(
    payload: user_schema.UserUsernameUpdate,
    request: Request,
    db: Session = Depends(session.get_db),
):
    db_user = await _get_current_user(request, db)

    if await _username_exists(
        db,
        username=payload.username,
        exclude_email=db_user.email,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken. Please choose another one.",
        )

    db_user.username = payload.username

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken. Please choose another one.",
        )

    await db.refresh(db_user)
    return db_user


@router.get("/me/status", response_model=user_schema.UserProfileResponse)
async def read_my_status(
    request: Request,
    db: Session = Depends(session.get_db),
):
    return await _get_current_user(request, db)


@router.put("/me/status", response_model=user_schema.UserProfileResponse)
async def update_my_status(
    payload: user_schema.UserStatusUpdate,
    request: Request,
    db: Session = Depends(session.get_db),
):
    db_user = await _get_current_user(request, db)

    db_user.status = payload.status

    await db.commit()
    await db.refresh(db_user)

    return db_user

@router.put("/me/share-schedule", response_model=user_schema.UserProfileResponse)
async def update_my_share_schedule(
    payload: user_schema.UserShareScheduleUpdate,
    request: Request,
    db: Session = Depends(session.get_db),
):
    db_user = await _get_current_user(request, db)

    db_user.share_schedule = payload.share_schedule

    await db.commit()
    await db.refresh(db_user)

    return db_user

@router.put("/me/password")
async def update_my_password(
    payload: user_schema.UserPasswordUpdate,
    request: Request,
    db: Session = Depends(session.get_db),
) -> dict:
    db_user = await _get_current_user(request, db)

    if not utils.compare_hash(payload.current_password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    db_user.password_hash = utils.get_hash(payload.new_password)
    await db.commit()

    return {"message": "Password updated"}


@router.get("/email/{user_email}", response_model=user_schema.UserResponse)
async def get_user(user_email: str, db: Session = Depends(session.get_db)):
    stmt = select(models.User).where(models.User.email == user_email)
    result = await db.execute(stmt)
    db_user = result.scalars().first()
    if db_user is None:
        raise HTTPException(status_code=403, detail="That User was not Found")
    return db_user