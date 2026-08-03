from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class RequestOtpIn(BaseModel):
    email: EmailStr
    # UI language (app/BO). If omitted, use stored user.lang or Spanish.
    lang: str | None = Field(default=None, pattern="^(ca|es|en)$")


class VerifyOtpIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=8)


class UserOut(BaseModel):
    id: str
    email: EmailStr
    slug: str
    first_name: str | None
    last_name: str | None
    name: str | None = None  # computed display: first + last
    lang: str
    postal_code: str | None
    town_id: str | None = None
    town_name: str | None = None
    points: int
    roles: list[str]
    shop_id: str | None = None
    phone: str | None = None
    birth_date: date | None = None
    contact_shared: bool = False
    is_fake: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    points_awarded: int | None = None
    points_award_message: str | None = None


class MessageOut(BaseModel):
    message: str
