"""Pydantic schemas package — API contract (English field names)."""

from app.schemas.users import UpdateUserIn
from app.schemas.auth import AuthOut, MessageOut, RequestOtpIn, VerifyOtpIn, UserOut
from app.schemas.towns import (
    TownOut,
    TownUpdate,
    TownPostalCodeOut,
    TownPostalCodeCreate,
    TownMediaOut,
)
from app.schemas.shops import (
    ShopCreate,
    ShopOut,
    ShopUpdate,
    ShopProfileUpdate,
    ShopMediaOut,
    QrOut,
)
from app.schemas.opening_hours import DayHours, OpeningHours
from app.schemas.shop_categories import ShopCategoryOut, ShopCategoryUpdate
from app.schemas.promotions import PromotionCreate, PromotionOut, PromotionUpdate
from app.schemas.actions import PointActionCreate, PointActionOut, PointActionUpdate
from app.schemas.rewards import RewardCreate, RewardMediaOut, RewardOut, RewardUpdate
from app.schemas.redemptions import (
    RedemptionCreate,
    RedemptionOut,
    RedemptionStatusUpdate,
    RedemptionUseIn,
    RedemptionValidateIn,
)
from app.schemas.payments import ShopDebtOut, ShopPaymentCreate, ShopPaymentOut
from app.schemas.scans import ScanIn, ScanOut
from app.schemas.residents import ResidentOut, ResidentActivityOut
from app.schemas.stats import AdminStatsOut, MerchantStatsOut
from app.schemas.points import ClaimPointsOut, PointsHistoryItem, PointsHistoryOut

__all__ = [
    "AuthOut",
    "MessageOut",
    "RequestOtpIn",
    "VerifyOtpIn",
    "UpdateUserIn",
    "UserOut",
    "TownOut",
    "TownUpdate",
    "TownPostalCodeOut",
    "TownPostalCodeCreate",
    "TownMediaOut",
    "ShopCreate",
    "ShopOut",
    "ShopUpdate",
    "ShopProfileUpdate",
    "ShopMediaOut",
    "QrOut",
    "DayHours",
    "OpeningHours",
    "ShopCategoryOut",
    "ShopCategoryUpdate",
    "PromotionCreate",
    "PromotionOut",
    "PromotionUpdate",
    "PointActionCreate",
    "PointActionOut",
    "PointActionUpdate",
    "ClaimPointsOut",
    "PointsHistoryItem",
    "PointsHistoryOut",
    "RewardCreate",
    "RewardOut",
    "RewardUpdate",
    "RewardMediaOut",
    "RedemptionCreate",
    "RedemptionOut",
    "RedemptionStatusUpdate",
    "RedemptionUseIn",
    "RedemptionValidateIn",
    "ShopDebtOut",
    "ShopPaymentCreate",
    "ShopPaymentOut",
    "ScanIn",
    "ScanOut",
    "ResidentOut",
    "ResidentActivityOut",
    "AdminStatsOut",
    "MerchantStatsOut",
]
