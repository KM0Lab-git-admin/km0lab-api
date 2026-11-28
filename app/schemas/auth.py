from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class RequestOtpIn(BaseModel):
    email: EmailStr
    # UI language (app/BO). If omitted, use stored user.lang or Spanish.
    lang: str | None = Field(default=None, pattern="^(ca|es|en)$")
    invite_code: str | None = Field(default=None, max_length=32)
    postal_code: str | None = Field(default=None, max_length=10)
    # Version of the pilot terms the person ticked before asking for a code.
    terms_version: str | None = Field(default=None, max_length=16)


class VerifyOtpIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=8)
    invite_code: str | None = Field(default=None, max_length=32)
    postal_code: str | None = Field(default=None, max_length=10)
    terms_version: str | None = Field(default=None, max_length=16)


class ShopRequestOut(BaseModel):
    """A shop this person asked to register and is not live."""

    shop_id: str
    name: str
    # review (waiting for validation) | rejected
    status: str
    # Why it was rejected, as the administrator wrote it.
    reason: str | None = None


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
    # ``town_name`` is the town the person lives in (what the app shows).
    # ``municipality_name`` is the managed scope: what the backoffice
    # shows its administrator. They differ when a municipality groups towns.
    town_name: str | None = None
    municipality_name: str | None = None
    points: int
    roles: list[str]
    shop_id: str | None = None
    phone: str | None = None
    birth_date: date | None = None
    contact_shared: bool = False
    # Proof of consent: null until the person accepts the terms in force.
    terms_version: str | None = None
    terms_accepted_at: datetime | None = None
    is_fake: bool = False
    # Set while the shop this person asked for waits or was rejected,
    # so the panel can say so instead of "this email has no shop".
    shop_request: ShopRequestOut | None = None
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
