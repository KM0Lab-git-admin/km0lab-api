from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


INVITE_KIND_PATTERN = "^(person|business)$"
INVITE_EVENT_PATTERN = (
    "^(share_initiated|link_resolved|registration_started|install_referrer_recovered)$"
)
INVITE_CHANNEL_PATTERN = "^(whatsapp|email|facebook|copy|other)$"
CONV_STATUS_PATTERN = "^(pending_reward|granted|failed)$"


class InviteLinkOut(BaseModel):
    public_code: str
    kind: str
    town_id: str


class InviteResolveIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class InviteResolveOut(BaseModel):
    valid: bool
    code: str | None = None
    kind: str | None = None
    town_id: str | None = None
    town_name: str | None = None


class InviteEventIn(BaseModel):
    type: str = Field(pattern=INVITE_EVENT_PATTERN)
    code: str | None = Field(default=None, max_length=32)
    channel: str | None = Field(default=None, pattern=INVITE_CHANNEL_PATTERN)


class InviteSummaryOut(BaseModel):
    persons_registered: int
    businesses_registered: int
    points_earned: int
    points_pending: int


class InviteConversionOut(BaseModel):
    id: str
    kind: str
    status: str
    display_name: str | None
    completed_at: datetime | None
    granted_at: datetime | None
    points: int
    inviter_user_id: str | None = None
    invitee_user_id: str | None = None
    shop_id: str | None = None
    town_id: str | None = None
    public_code: str | None = None

    model_config = {"from_attributes": True}


class InviteConversionListOut(BaseModel):
    items: list[InviteConversionOut]
    total: int


class AdminInviteListOut(BaseModel):
    conversions: list[InviteConversionOut]
    total: int
    persons_registered: int
    businesses_registered: int
    points_granted: int
    share_events: int


class ShopPublicSignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    tax_id: str = Field(min_length=5, max_length=32)
    categories: list[str] = Field(default_factory=list)
    contact_email: EmailStr
    postal_code: str = Field(min_length=4, max_length=10)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=255)
    description: str | None = None
    invite_code: str | None = Field(default=None, max_length=32)


class ShopPublicSignupOut(BaseModel):
    shop_id: str
    status: str
    contact_email: str
    needs_otp: bool
    message: str
