"""Guest authentication schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr


class GuestRegisterRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    phone: str | None = None


class GuestLoginRequest(BaseModel):
    email: EmailStr
    password: str


class GuestTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class GuestProfileResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    allergen_profile: list | None = None
    email_verified: bool = False

    model_config = {"from_attributes": True}


class GuestProfileUpdateRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    allergen_profile: list | None = None


class GuestChangeEmailRequest(BaseModel):
    new_email: EmailStr
    password: str


class GuestChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class EmailVerifyRequest(BaseModel):
    token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str
