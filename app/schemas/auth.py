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
    # After "your email is missing": who the person proved to be in a
    # social network, to link it to the account this code opens.
    link_token: str | None = Field(default=None, max_length=2048)


class SocialLoginIn(BaseModel):
    # What the network handed the app: verified here, never stored.
    credential: str = Field(min_length=10, max_length=8192)
    invite_code: str | None = Field(default=None, max_length=32)
    postal_code: str | None = Field(default=None, max_length=10)
    terms_version: str | None = Field(default=None, max_length=16)
    # Apple gives the name only the first time, and to the app.
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=120)


class AuthProviderOut(BaseModel):
    provider: str  # google | facebook | apple
    # Public id of our app in that network: the button needs it.
    client_id: str


class AuthProvidersOut(BaseModel):
    providers: list[AuthProviderOut] = []


class SignInMethodOut(BaseModel):
    provider: str  # email_code | google | facebook | apple
    linked_at: datetime
    last_used_at: datetime | None = None


class SignInMethodsOut(BaseModel):
    """How this person gets into their account (their own view)."""

    # The door the account was born with; null if it never logged in.
    created_with: str | None = None
    email: str
    # One of Apple's hidden emails: the person does not know it.
    email_hidden: bool = False
    methods: list[SignInMethodOut] = []


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
