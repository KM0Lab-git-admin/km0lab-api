"""SQLAlchemy models — KM0 LAB domain (English naming).

users / otp_codes (MVP) + towns, shops, promotions, point_actions,
rewards, points_transactions, qr_scans, redemptions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import LONGBLOB
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
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    entity_name: Mapped[str] = mapped_column(String(160), default="")
    entity_type: Mapped[str] = mapped_column(
        String(20), default="city_council"
    )  # city_council | private
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    manager_name: Mapped[str] = mapped_column(String(120), default="")
    logo_url: Mapped[str | None] = mapped_column(String(512), default=None)
    # BO config · Configuració
    points_per_euro: Mapped[int] = mapped_column(Integer, default=200)
    default_visit_points: Mapped[int] = mapped_column(Integer, default=10)
    default_lang: Mapped[str] = mapped_column(String(5), default="ca")  # ca|es|en
    expiry_months: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    postal_codes: Mapped[list[TownPostalCode]] = relationship(
        "TownPostalCode", back_populates="town", cascade="all, delete-orphan"
    )
    media: Mapped[list["TownMedia"]] = relationship(
        "TownMedia",
        back_populates="town",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TownMedia(Base):
    """Binary brand assets for a town (logo)."""

    __tablename__ = "town_media"
    __table_args__ = (
        UniqueConstraint("town_id", "kind", name="uq_town_media_kind"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    town_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("towns.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))  # logo
    content_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(
        LargeBinary().with_variant(LONGBLOB(), "mysql"),
        nullable=False,
    )
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    town: Mapped["Town"] = relationship("Town", back_populates="media")


class TownPostalCode(Base):
    """Postal codes belonging to a town (N per town; each CP is unique)."""

    __tablename__ = "town_postal_codes"

    postal_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    town_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("towns.id", ondelete="CASCADE"), index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    town: Mapped[Town] = relationship("Town", back_populates="postal_codes")


class User(Base):
    """Identity keyed by email. Town membership via postal_code → town_postal_codes.

    Multi-role: resident±merchant or resident±admin (never admin+merchant).
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(80), default=None)
    last_name: Mapped[str | None] = mapped_column(String(120), default=None)
    lang: Mapped[str] = mapped_column(String(5), default="ca")  # ca | es | en
    # FK to town_postal_codes — source of town membership / name.
    postal_code: Mapped[str | None] = mapped_column(
        String(10),
        ForeignKey("town_postal_codes.postal_code"),
        default=None,
        index=True,
    )
    # Cached balance; source of truth is points_transactions.
    points: Mapped[int] = mapped_column(Integer, default=0)
    # Multi-role flags (admin XOR merchant enforced in app.roles).
    is_resident: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_merchant: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    shop_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("shops.id"), default=None, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    birth_date: Mapped[date | None] = mapped_column(Date, default=None)
    contact_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    postal_ref: Mapped[TownPostalCode | None] = relationship(
        "TownPostalCode", lazy="selectin"
    )

    @property
    def name(self) -> str | None:
        """Display name: first_name + last_name."""
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or None

    @property
    def town_id(self) -> str | None:
        return self.postal_ref.town_id if self.postal_ref else None

    @property
    def town_name(self) -> str | None:
        if self.postal_ref is None:
            return None
        town = self.postal_ref.town
        return town.name if town is not None else None

    @property
    def roles(self) -> list[str]:
        from app.roles import roles_from_flags

        return roles_from_flags(
            is_resident=self.is_resident,
            is_merchant=self.is_merchant,
            is_admin=self.is_admin,
        )

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def set_roles(self, roles: list[str]) -> None:
        from app.roles import flags_from_roles

        flags = flags_from_roles(roles)
        self.is_resident = flags["is_resident"]
        self.is_merchant = flags["is_merchant"]
        self.is_admin = flags["is_admin"]


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


class ShopCategory(Base):
    """Catalog of shop categories. Labels live in label_i18n (ca/es/en).

    Legacy front/BO i18n keys (shopCategories.{slug}) remain as fallback
    when label_i18n is null.
    """

    __tablename__ = "shop_categories"

    slug: Mapped[str] = mapped_column(String(40), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    label_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    i18n_source_lang: Mapped[str] = mapped_column(String(5), default="ca")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    town_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("towns.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    emoji: Mapped[str | None] = mapped_column(String(16), default=None)
    # Legacy URL fields; prefer shop_media BLOBs. Kept for migration compat.
    logo_url: Mapped[str | None] = mapped_column(String(512), default=None)
    hero_url: Mapped[str | None] = mapped_column(String(512), default=None)
    # List of shop_categories.slug (not translated labels).
    categories: Mapped[list] = mapped_column(JSON, default=list)
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    visit_points: Mapped[int] = mapped_column(Integer, default=10)
    address: Mapped[str | None] = mapped_column(String(255), default=None)
    postal_code: Mapped[str | None] = mapped_column(String(10), default=None)
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    website: Mapped[str | None] = mapped_column(String(255), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    description_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    i18n_source_lang: Mapped[str] = mapped_column(String(5), default="ca")
    # Weekly schedule JSON — see app.schemas.opening_hours.OpeningHours
    # {"monday": {"closed": false, "opens": "07:00", "closes": "20:00"}, ...}
    opening_hours: Mapped[dict | None] = mapped_column(JSON, default=None)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )  # active | pending | inactive
    qr_code: Mapped[str | None] = mapped_column(
        String(64), unique=True, default=None, index=True
    )
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    media: Mapped[list["ShopMedia"]] = relationship(
        "ShopMedia", back_populates="shop", cascade="all, delete-orphan"
    )


class ShopMedia(Base):
    """Binary logo/hero assets for a shop (stored in MySQL LONGBLOB)."""

    __tablename__ = "shop_media"
    __table_args__ = (
        UniqueConstraint("shop_id", "kind", name="uq_shop_media_kind"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    shop_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("shops.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # logo | hero
    content_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(
        LargeBinary().with_variant(LONGBLOB(), "mysql"),
        nullable=False,
    )
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    shop: Mapped["Shop"] = relationship("Shop", back_populates="media")


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
    label_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    title_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    detail_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    conditions_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    i18n_source_lang: Mapped[str] = mapped_column(String(5), default="ca")
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
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
    )  # signup | birthday | qr_scan | first_scan | web_visit | web_signup | event | custom
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    points: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int | None] = mapped_column(Integer, default=None)
    total_limit: Mapped[int | None] = mapped_column(Integer, default=None)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    conditions: Mapped[str | None] = mapped_column(Text, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Featured on the residents app home ("Cómo ganar puntos hoy").
    visible_home: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Trilingual labels for custom actions; fixed types use the catalog.
    name_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    description_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    conditions_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    i18n_source_lang: Mapped[str] = mapped_column(String(5), default="ca")
    url: Mapped[str | None] = mapped_column(String(512), default=None)
    event_id: Mapped[str | None] = mapped_column(String(64), default=None)
    # Days until the same user can earn points again from the same shop QR.
    cooldown_days: Mapped[int | None] = mapped_column(Integer, default=None)
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
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
    )  # RewardType: discount | balance | product | service | merchandise | experience
    points_required: Mapped[int] = mapped_column(Integer)
    value: Mapped[str | None] = mapped_column(String(80), default=None)
    stock: Mapped[int | None] = mapped_column(Integer, default=None)  # None = unlimited
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    conditions: Mapped[str | None] = mapped_column(Text, default=None)
    name_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    description_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    conditions_i18n: Mapped[dict | None] = mapped_column(JSON, default=None)
    i18n_source_lang: Mapped[str] = mapped_column(String(5), default="ca")
    status: Mapped[str] = mapped_column(
        String(20), default="active", index=True
    )  # active | inactive | sold_out
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    shops: Mapped[list[RewardShop]] = relationship(
        "RewardShop", cascade="all, delete-orphan", lazy="selectin"
    )
    media: Mapped[RewardMedia | None] = relationship(
        "RewardMedia",
        back_populates="reward",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )


class RewardMedia(Base):
    """Binary catalog image for a reward (MySQL LONGBLOB)."""

    __tablename__ = "reward_media"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    reward_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("rewards.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    content_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(
        LargeBinary().with_variant(LONGBLOB(), "mysql"),
        nullable=False,
    )
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    reward: Mapped["Reward"] = relationship("Reward", back_populates="media")


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
    )  # welcome | birthday | action | scan | redemption | adjustment
    points: Mapped[int] = mapped_column(Integer)  # +/-
    ref_id: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    description: Mapped[str | None] = mapped_column(String(255), default=None)
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


class QrScan(Base):
    """Successful QR visit. Cooldown per user+shop is enforced in scans.py."""

    __tablename__ = "qr_scans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), index=True
    )
    shop_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("shops.id"), index=True
    )
    points: Mapped[int] = mapped_column(Integer)
    scan_date: Mapped[date] = mapped_column(Date, index=True)
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
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
    # voucher_qr: 5-digit code shown to the merchant (null for delivery flow)
    code: Mapped[str | None] = mapped_column(String(5), default=None, unique=True)
    # voucher_qr fields
    amount: Mapped[str | None] = mapped_column(String(80), default=None)
    shop_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("shops.id"), default=None
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    amount_applied: Mapped[str | None] = mapped_column(String(80), default=None)
    # Settlement to the shop (used vouchers only); null = pending payment.
    payment_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("shop_payments.id"), default=None, index=True
    )
    # delivery fields
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list[RedemptionEvent]] = relationship(
        "RedemptionEvent", cascade="all, delete-orphan", lazy="selectin"
    )


class ShopPayment(Base):
    """Manual settlement from town hall to a shop for used vouchers."""

    __tablename__ = "shop_payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    town_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("towns.id"), index=True
    )
    shop_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("shops.id"), index=True
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    note: Mapped[str | None] = mapped_column(String(255), default=None)
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class RedemptionEvent(Base):
    __tablename__ = "redemption_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    redemption_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("redemptions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(255), default=None)
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
