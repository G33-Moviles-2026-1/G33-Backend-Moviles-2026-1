import re

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

from app.db.models import UserStatus


USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,25}$")


def normalize_username(value: str) -> str:
    cleaned = value.strip().lower()

    if not USERNAME_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "Username must be 3 to 25 characters long and can only contain "
            "letters, numbers, dots, underscores, or hyphens."
        )

    return cleaned


def normalize_status(value: str | UserStatus) -> UserStatus:
    if isinstance(value, UserStatus):
        return value

    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "incognito": UserStatus.incognito,
        "busy": UserStatus.busy,
        "exercising": UserStatus.exercising,
        "free": UserStatus.free,
        "hanging_out": UserStatus.hanging_out,
        "at_home": UserStatus.at_home,
        "lunching": UserStatus.lunching,
    }

    status_value = aliases.get(cleaned)
    if not status_value:
        raise ValueError(
            "Status must be one of: incognito, busy, exercising, free, "
            "hanging_out, at_home, lunching."
        )

    return status_value


class UserBase(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email_domain(cls, value: str) -> str:
        allowed_domain = "@uniandes.edu.co"
        cleaned = value.strip().lower()

        if not cleaned.endswith(allowed_domain):
            raise HTTPException(
                status_code=403,
                detail=f"The email must match with {allowed_domain}",
            )

        return cleaned


class UserCreate(UserBase):
    first_semester: str
    password: str

    # Temporalmente opcional mientras el frontend empieza a enviarlo.
    # Si no llega, el backend lo genera desde el correo.
    username: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_username(value)


class UserResponse(UserBase):
    first_semester: str
    username: str
    status: UserStatus

    model_config = ConfigDict(from_attributes=True)


class UserProfileResponse(BaseModel):
    email: str
    username: str
    status: UserStatus

    model_config = ConfigDict(from_attributes=True)


class UserUsernameUpdate(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return normalize_username(value)


class UserStatusUpdate(BaseModel):
    status: UserStatus

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: str | UserStatus) -> UserStatus:
        return normalize_status(value)


class UserAuthenticate(UserBase):
    password: str

class UserShareScheduleUpdate(BaseModel):
    share_schedule: bool

class UserPasswordUpdate(BaseModel):
    current_password: str
    new_password: str

class UserShareScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    share_schedule: bool
