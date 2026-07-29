from datetime import datetime

from pydantic import BaseModel, Field


class RedemptionEventOut(BaseModel):
    status: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RedemptionOut(BaseModel):
    id: str
    town_id: str
    user_id: str
    reward_id: str
    flow: str
    points_spent: int
    status: str
    code: str | None = None
    amount: str | None
    shop_id: str | None
    used_at: datetime | None
    amount_applied: str | None
    payment_id: str | None = None
    delivered_at: datetime | None
    requested_at: datetime
    is_fake: bool = False
    events: list[RedemptionEventOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RedemptionCreate(BaseModel):
    reward_id: str
    shop_id: str | None = None
    amount: str | None = None


class RedemptionStatusUpdate(BaseModel):
    status: str = Field(
        pattern=(
            "^(pending_use|used|requested|pending_preparation|"
            "prepared|pending_pickup|delivered|cancelled)$"
        )
    )
    note: str | None = None


class RedemptionUseIn(BaseModel):
    """Merchant marks a voucher_qr redemption as used."""

    amount_applied: str | None = None


class RedemptionValidateIn(BaseModel):
    """Merchant validates a voucher by its 5-digit code."""

    code: str = Field(pattern=r"^\d{5}$")
    amount_applied: str | None = None
