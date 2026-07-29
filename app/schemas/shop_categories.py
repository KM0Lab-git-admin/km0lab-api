from datetime import datetime

from pydantic import BaseModel


class ShopCategoryOut(BaseModel):
    slug: str
    sort_order: int
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
