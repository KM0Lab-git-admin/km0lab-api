from datetime import datetime

from pydantic import BaseModel, Field


class ClaimPointsOut(BaseModel):
    awarded: bool
    points: int = 0
    balance: int
    message: str | None = None


class PointsHistoryItem(BaseModel):
    """One ledger row for the resident points history screen."""

    id: str
    type: str  # welcome | birthday | action | scan | redemption | adjustment
    points: int  # + earned / - spent
    description: str | None = None
    title: str | None = None  # action / reward display name when known
    shop_name: str | None = None
    reward_name: str | None = None
    ref_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PointsHistoryOut(BaseModel):
    balance: int
    earned_total: int = Field(
        description="Sum of positive point movements (absolute earned)."
    )
    spent_total: int = Field(
        description="Sum of absolute negative movements (points spent)."
    )
    items: list[PointsHistoryItem] = Field(default_factory=list)
