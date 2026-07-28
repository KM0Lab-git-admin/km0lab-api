"""SQLAlchemy models — KM0 LAB domain (English naming).

users / otp_codes (MVP) + towns, shops, promotions, point_actions,
rewards, points_transactions, qr_scans, redemptions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


# ── Identity ──────────────────────────────────────────────────────────


class Town(Base):
    __tablename__ = "towns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    entity_name: Mapped[str] = mapped_column(String(160), default="")
    entity_type: Mapped[str] = mapped_column(
        String(20), default="city_council"
    )  # city_council | private
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    manager_name: Mapped[str] = mapped_column(String(120), default="")
    logo_url: Mapped[str | None] = mapped_column(String(512), default=None)
    points_per_euro: Mapped[int] = mapped_column(Integer, default=200)
    expiry_months: Mapped[int | None] = mapped_column(Integer, default=None)
    default_visit_points: Mapped[int] = mapped_column(Integer, default=10)
    default_lang: Mapped[str] = mapped_column(String(5), default="ca")  # ca|es|en
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), default=None)
    lang: Mapped[str] = mapped_column(String(5), default="ca")  # ca | es | en
    postal_code: Mapped[str | None] = mapped_column(String(10), default=None)
    # Free-text town label from app onboarding (kept for backward compat).
    town: Mapped[str | None] = mapped_column(String(120), default=None)
    # Cached balance; source of truth is points_transactions.
    points: Mapped[int] = mapped_column(Integer, default=0)
    # Domain role + scope
    role: Mapped[str] = mapped_column(
        String(20), default="resident", index=True
    )  # resident | merchant | admin
    town_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("towns.id"), default=None, index=True
    )
    shop_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("shops.id"), default=None, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    contact_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OtpCode(Base):
    """One-time email OTP. Stores hash only, never plaintext."""

    __tablename__ = "otp_codes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed: Mapped[int] = mapped_column(Integer, default=0)  # 0 | 1
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


# ── Shops & promotions ────────────────────────────────────────────────


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    town_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("towns.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    emoji: Mapped[str | None] = mapped_column(String(16), default=None)
    logo_url: Mapped[str | None] = mapped_column(String(512), default=None)
    hero_url: Mapped[str | None] = mapped_column(String(512), default=None)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    visit_points: Mapped[int] = mapped_column(Integer, default=10)
    address: Mapped[str | None] = mapped_column(String(255), default=None)
    postal_code: Mapped[str | None] = mapped_column(String(10), default=None)
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    website: Mapped[str | None] = mapped_column(String(255), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    opening_hours: Mapped[dict | None] = mapped_column(JSON, default=None)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )  # active | pending | inactive
    qr_code: Mapped[str | None] = mapped_column(
        String(64), unique=True, default=None, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    shop_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("shops.id"), index=True
    )
    type: Mapped[str] = mapped_column(
        String(30)
    )  # discount | two_for_one | gift | special_price
    label: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[str | None] = mapped_column(String(80), default=None)
    min_purchase: Mapped[str | None] = mapped_column(String(80), default=None)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    conditions: Mapped[str | None] = mapped_column(Text, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ── Point actions & rewards ───────────────────────────────────────────


class PointAction(Base):
    __tablename__ = "point_actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    town_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("towns.id"), index=True
    )
    type: Mapped[str] = mapped_column(
        String(30)
    )  # signup | qr_scan | web_visit | web_signup | event | custom
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    points: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int | None] = mapped_column(Integer, default=None)
    total_limit: Mapped[int | None] = mapped_column(Integer, default=None)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    conditions: Mapped[str | None] = mapped_column(Text, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    url: Mapped[str | None] = mapped_column(String(512), default=None)
    event_id: Mapped[str | None] = mapped_column(String(64), default=None)
    shop_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("shops.id"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Reward(Base):
    __tablename__ = "rewards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    town_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("towns.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str | None] = mapped_column(String(512), default=None)
    type: Mapped[str] = mapped_column(
        String(30)
    )  # discount | balance | product | service | merchandise | experience
    points_required: Mapped[int] = mapped_column(Integer)
    value: Mapped[str | None] = mapped_column(String(80), default=None)
    stock: Mapped[int | None] = mapped_column(Integer, default=None)  # None = unlimited
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    conditions: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(
        String(20), default="active", index=True
    )  # active | inactive | sold_out
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    shops: Mapped[list[RewardShop]] = relationship(
        "RewardShop", cascade="all, delete-orphan", lazy="selectin"
    )


class RewardShop(Base):
    """Join table. Empty set for a reward means available at all shops."""

    __tablename__ = "reward_shops"
    __table_args__ = (
        UniqueConstraint("reward_id", "shop_id", name="uq_reward_shop"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    reward_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("rewards.id", ondelete="CASCADE"), index=True
    )
    shop_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("shops.id", ondelete="CASCADE"), index=True
    )


# ── Ledger, QR, redemptions ───────────────────────────────────────────


class PointsTransaction(Base):
    __tablename__ = "points_transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), index=True
    )
    town_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("towns.id"), default=None, index=True
    )
    type: Mapped[str] = mapped_column(
        String(30)
    )  # welcome | action | scan | redemption | adjustment
    points: Mapped[int] = mapped_column(Integer)  # +/-
    ref_id: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    description: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


class QrScan(Base):
    __tablename__ = "qr_scans"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "shop_id", "scan_date", name="uq_qr_scan_user_shop_day"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), index=True
    )
    shop_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("shops.id"), index=True
    )
    points: Mapped[int] = mapped_column(Integer)
    scan_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class Redemption(Base):
    __tablename__ = "redemptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    town_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("towns.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), index=True
    )
    reward_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("rewards.id"), index=True
    )
    flow: Mapped[str] = mapped_column(String(20))  # voucher_qr | delivery
    points_spent: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    # voucher_qr fields
    amount: Mapped[str | None] = mapped_column(String(80), default=None)
    shop_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("shops.id"), default=None
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    amount_applied: Mapped[str | None] = mapped_column(String(80), default=None)
    # delivery fields
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list[RedemptionEvent]] = relationship(
        "RedemptionEvent", cascade="all, delete-orphan", lazy="selectin"
    )


class RedemptionEvent(Base):
    __tablename__ = "redemption_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    redemption_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("redemptions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
