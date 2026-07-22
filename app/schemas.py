"""Schemas Pydantic (request/response). Contrato de la API."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RequestOtpIn(BaseModel):
    email: EmailStr


class VerifyOtpIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=8)


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str | None
    lang: str
    postal_code: str | None
    town: str | None
    points: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UpdateUserIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    lang: str | None = Field(default=None, pattern="^(ca|es|en)$")
    postal_code: str | None = Field(default=None, max_length=10)
    town: str | None = Field(default=None, max_length=120)


class MessageOut(BaseModel):
    message: str
