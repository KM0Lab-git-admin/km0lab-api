from datetime import datetime

from pydantic import BaseModel, EmailStr


class ResidentActivityOut(BaseModel):
    id: str
    type: str
    description: str | None
    points: int
    created_at: datetime

    model_config = {"from_attributes": True}


class IdentityOut(BaseModel):
    """One way a person gets into their account. Never the provider's id."""

    provider: str  # email_code | google | facebook | apple
    linked_at: datetime
    last_used_at: datetime | None = None


class ResidentOut(BaseModel):
    id: str
    slug: str
    first_name: str | None
    last_name: str | None
    name: str | None
    points: int
    town_id: str | None
    contact_shared: bool
    email: EmailStr | None = None
    phone: str | None = None
    created_at: datetime
    # How the account was born (null: created by a script and never
    # logged in) and when; the full list only in the resident's card.
    signup_provider: str | None = None
    signup_at: datetime | None = None
    # The email is one of Apple's hidden ones: writing to it may bounce.
    email_hidden: bool = False
    identities: list[IdentityOut] = []
    activity: list[ResidentActivityOut] = []

    model_config = {"from_attributes": True}
