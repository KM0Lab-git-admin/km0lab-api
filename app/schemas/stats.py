from pydantic import BaseModel


class AdminStatsOut(BaseModel):
    active_users: int
    points_in_circulation: int
    redemptions_this_month: int
    active_actions: int
    total_actions: int


class MerchantStatsOut(BaseModel):
    total_scans: int
    unique_visitors: int
    points_awarded: int
    active_promotions: int
