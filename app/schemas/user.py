from pydantic import BaseModel, ConfigDict
from pydantic import BaseModel, ConfigDict, field_validator, EmailStr

class UserBase(BaseModel):
    email: str
    @field_validator('email')
    @classmethod
    def validate_email_domain(cls, v: str) -> str:
        allowed_domain = "@uniandes.edu.co"
        if not v.lower().endswith(allowed_domain):
            raise ValueError(f"The email must match with {allowed_domain}")
        return v.lower()

class UserCreate(UserBase):
    first_semester: str
    password: str

class UserResponse(UserBase):
    first_semester: str
    model_config = ConfigDict(from_attributes=True)

class UserAuthenticate(UserBase):
    password: str