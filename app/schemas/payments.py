"""Shop payment schemas — town hall settles used vouchers with shops."""

from datetime import datetime

from pydantic import BaseModel, Field


class ShopDebtOut(BaseModel):
    """Aggregated pending/paid amounts per shop (admin view)."""

    shop_id: str
    shop_name: str
    pending_count: int
    pending_amount: float
    paid_total: float


class ShopPaymentOut(BaseModel):
    id: str
    town_id: str
    shop_id: str
    shop_name: str
    total_amount: float
    note: str | None
    redemption_ids: list[str] = Field(default_factory=list)
    is_fake: bool = False
    created_at: datetime


class ShopPaymentCreate(BaseModel):
    shop_id: str
    redemption_ids: list[str] = Field(min_length=1)
    note: str | None = None
