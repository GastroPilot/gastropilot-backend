"""Guest authentication schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, model_validator


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
    allergen_ids: list | None = None
    email_verified: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _mirror_allergen_fields(self):
        # Frontend-Aliase: app/ liest allergen_ids, restaurant-app/admin
        # liest allergen_profile. Beide Felder spiegeln das DB-Feld
        # GuestProfile.allergen_profile.
        if self.allergen_ids is None:
            self.allergen_ids = self.allergen_profile
        return self


class GuestProfileUpdateRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    allergen_profile: list | None = None
    allergen_ids: list | None = None

    @model_validator(mode="after")
    def _consolidate_allergens(self):
        # App schickt allergen_ids, andere Clients allergen_profile.
        # Falls beide leer sind, bleibt None (kein Update).
        if self.allergen_profile is None and self.allergen_ids is not None:
            self.allergen_profile = self.allergen_ids
        return self


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
