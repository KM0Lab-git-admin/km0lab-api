"""Pydantic schemas package — API contract (English field names)."""

from app.schemas.auth import AuthOut, MessageOut, RequestOtpIn, VerifyOtpIn
from app.schemas.users import UpdateUserIn, UserOut
from app.schemas.towns import TownOut, TownUpdate
from app.schemas.shops import (
    ShopCreate,
    ShopOut,
    ShopUpdate,
    ShopProfileUpdate,
    QrOut,
)
from app.schemas.promotions import PromotionCreate, PromotionOut, PromotionUpdate
from app.schemas.actions import PointActionCreate, PointActionOut, PointActionUpdate
from app.schemas.rewards import RewardCreate, RewardOut, RewardUpdate
from app.schemas.redemptions import (
    RedemptionCreate,
    RedemptionOut,
    RedemptionStatusUpdate,
    RedemptionUseIn,
)
from app.schemas.scans import ScanIn, ScanOut
from app.schemas.residents import ResidentOut, ResidentActivityOut
from app.schemas.stats import AdminStatsOut, MerchantStatsOut

__all__ = [
    "AuthOut",
    "MessageOut",
    "RequestOtpIn",
    "VerifyOtpIn",
    "UpdateUserIn",
    "UserOut",
    "TownOut",
    "TownUpdate",
    "ShopCreate",
    "ShopOut",
    "ShopUpdate",
    "ShopProfileUpdate",
    "QrOut",
    "PromotionCreate",
    "PromotionOut",
    "PromotionUpdate",
    "PointActionCreate",
    "PointActionOut",
    "PointActionUpdate",
    "RewardCreate",
    "RewardOut",
    "RewardUpdate",
    "RedemptionCreate",
    "RedemptionOut",
    "RedemptionStatusUpdate",
    "RedemptionUseIn",
    "ScanIn",
    "ScanOut",
    "ResidentOut",
    "ResidentActivityOut",
    "AdminStatsOut",
    "MerchantStatsOut",
]
