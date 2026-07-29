from datetime import datetime

from pydantic import BaseModel, Field


class PromotionOut(BaseModel):
    id: str
    shop_id: str
    type: str
    label: str
    title: str
    detail: str
    value: str | None
    min_purchase: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    conditions: str | None
    active: bool
    is_fake: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromotionCreate(BaseModel):
    type: str = Field(pattern="^(discount|two_for_one|gift|special_price)$")
    label: str | None = Field(default=None, max_length=80)
    title: str = Field(max_length=200)
    detail: str = ""
    value: str | None = None
    min_purchase: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    conditions: str | None = None
    active: bool = True


class PromotionUpdate(BaseModel):
    type: str | None = Field(
        default=None, pattern="^(discount|two_for_one|gift|special_price)$"
    )
    label: str | None = None
    title: str | None = None
    detail: str | None = None
    value: str | None = None
    min_purchase: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    conditions: str | None = None
    active: bool | None = None
