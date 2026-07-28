from datetime import datetime

from pydantic import BaseModel, Field


class RewardOut(BaseModel):
    id: str
    town_id: str
    name: str
    description: str
    image_url: str | None
    type: str
    points_required: int
    value: str | None
    stock: int | None
    valid_from: datetime | None
    valid_until: datetime | None
    conditions: str | None
    status: str
    shop_ids: list[str] = Field(default_factory=list)  # empty = all shops
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RewardCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str = ""
    image_url: str | None = None
    type: str = Field(
        pattern="^(discount|balance|product|service|merchandise|experience)$"
    )
    points_required: int = Field(ge=0)
    value: str | None = None
    stock: int | None = Field(default=None, ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    conditions: str | None = None
    status: str = Field(default="active", pattern="^(active|inactive|sold_out)$")
    shop_ids: list[str] = Field(default_factory=list)


class RewardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    image_url: str | None = None
    type: str | None = Field(
        default=None,
        pattern="^(discount|balance|product|service|merchandise|experience)$",
    )
    points_required: int | None = Field(default=None, ge=0)
    value: str | None = None
    stock: int | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    conditions: str | None = None
    status: str | None = Field(
        default=None, pattern="^(active|inactive|sold_out)$"
    )
    shop_ids: list[str] | None = None
