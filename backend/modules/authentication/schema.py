from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

Username = Annotated[
    str,
    StringConstraints(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$"),
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
OTPCode = Annotated[str, StringConstraints(min_length=6, max_length=6, pattern=r"^\d{6}$")]


UtmValue = Annotated[str, StringConstraints(max_length=200)]


class Attribution(BaseModel):
    """First-touch marketing attribution, captured client-side at landing."""
    utm_source: Optional[UtmValue] = None
    utm_medium: Optional[UtmValue] = None
    utm_campaign: Optional[UtmValue] = None
    utm_content: Optional[UtmValue] = None
    utm_term: Optional[UtmValue] = None
    referrer: Optional[Annotated[str, StringConstraints(max_length=500)]] = None
    landing_path: Optional[Annotated[str, StringConstraints(max_length=300)]] = None


# ---------- Request schemas ----------
class SignupRequest(BaseModel):
    email: EmailStr
    username: Username
    password: Password
    attribution: Optional[Attribution] = None


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp_code: OTPCode


class ResendOTPRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: Password


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


# ---------- Response schemas ----------
class MessageResponse(BaseModel):
    message: str


class SignupResponse(BaseModel):
    message: str
    email: EmailStr
    otp_expires_in_minutes: int


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    email: EmailStr
    username: str
    is_verified: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AuthSuccessResponse(BaseModel):
    user: UserPublic
    tokens: TokenPair
