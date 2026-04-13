from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator


class UserBase(BaseModel):
    email: str | None = None
    operator_number: str | None = None
    nfc_tag_id: str | None = None
    first_name: str
    last_name: str
    role: str
    is_active: bool = True

    @field_validator("operator_number")
    @classmethod
    def operator_number_format(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{4}", v):
            raise ValueError("Bedienernummer muss genau 4 Ziffern lang sein")
        return v

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("E-Mail ist ungültig")
        return normalized


class UserCreate(UserBase):
    password: str | None = None
    pin: str | None = None
    auth_method: Literal["pin", "password"] | None = None

    @field_validator("pin")
    @classmethod
    def pin_length(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{6,8}", v):
            raise ValueError("PIN muss 6–8 Ziffern enthalten")
        return v

    @field_validator("password")
    @classmethod
    def password_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")
        return v

    @model_validator(mode="after")
    def validate_auth_requirements(self) -> UserCreate:
        has_pin = bool(self.pin)
        has_password = bool(self.password)
        has_email = bool(self.email)
        pin_only_roles = {"manager", "staff", "kitchen", "guest"}

        if not has_pin and not has_password:
            raise ValueError("Mindestens PIN oder Passwort muss gesetzt sein")

        if has_email and not has_password:
            raise ValueError("E-Mail und Passwort müssen zusammen gesetzt werden")

        if has_pin and not self.operator_number:
            raise ValueError("Für PIN-Login ist eine 4-stellige Bedienernummer erforderlich")

        if has_password and not self.email:
            raise ValueError("Für Passwort-Login ist eine E-Mail erforderlich")

        if self.role == "owner":
            if not self.email or not self.password:
                raise ValueError("Owner benötigen E-Mail und Passwort")
            if not self.operator_number or not self.pin:
                raise ValueError("Owner benötigen Bedienernummer und PIN für Dashboard/App")
        if self.role in pin_only_roles:
            if has_email or has_password:
                raise ValueError("Nur Owner dürfen E-Mail/Passwort nutzen")
            if not self.operator_number or not self.pin:
                raise ValueError("Für diese Rolle sind Bedienernummer und PIN erforderlich")

        if self.auth_method == "pin" and not has_pin:
            raise ValueError("auth_method=pin benötigt eine PIN")

        if self.auth_method == "password" and not has_password:
            raise ValueError("auth_method=password benötigt ein Passwort")
        if self.role == "owner" and self.auth_method == "pin":
            raise ValueError("Owner verwenden immer Passwort als primäre Login-Art")
        if self.role in pin_only_roles and self.auth_method == "password":
            raise ValueError("Nur Owner dürfen E-Mail/Passwort nutzen")

        return self


class UserUpdate(BaseModel):
    email: str | None = None
    operator_number: str | None = None
    nfc_tag_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None
    pin: str | None = None
    auth_method: Literal["pin", "password"] | None = None

    @field_validator("operator_number")
    @classmethod
    def operator_number_format(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{4}", v):
            raise ValueError("Bedienernummer muss genau 4 Ziffern lang sein")
        return v

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("E-Mail ist ungültig")
        return normalized

    @field_validator("pin")
    @classmethod
    def pin_length(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{6,8}", v):
            raise ValueError("PIN muss 6–8 Ziffern enthalten")
        return v

    @field_validator("password")
    @classmethod
    def password_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")
        return v


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None = None
    email: str | None = None
    operator_number: str | None = None
    nfc_tag_id: str | None = None
    first_name: str
    last_name: str
    role: str
    auth_method: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserMeResponse(UserResponse):
    pass
