"""Idempotent Malgrat QA accounts (real town, local/staging OTP 123456)."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.demo import (
    ADMIN_MALGRAT_EMAIL,
    MALGRAT_CP,
    MERCHANT1_MALGRAT_EMAIL,
    MERCHANT2_MALGRAT_EMAIL,
)
from app.models import Shop, TownPostalCode, User

_SHOPS = (
    {
        "email": MERCHANT1_MALGRAT_EMAIL,
        "name": "Forn QA Malgrat 1",
        "slug": "merchant-1-malgrat",
        "first_name": "Merchant",
        "last_name": "Malgrat 1",
        "key": "malgrat-qa-shop-1",
    },
    {
        "email": MERCHANT2_MALGRAT_EMAIL,
        "name": "Cafe QA Malgrat 2",
        "slug": "merchant-2-malgrat",
        "first_name": "Merchant",
        "last_name": "Malgrat 2",
        "key": "malgrat-qa-shop-2",
    },
)


def _stable_id(key: str) -> str:
    return hashlib.sha256(f"malgrat-qa:{key}".encode()).hexdigest()[:32]


def _id() -> str:
    return uuid.uuid4().hex


async def _malgrat_cp(db: AsyncSession) -> TownPostalCode | None:
    return (
        await db.execute(
            select(TownPostalCode).where(TownPostalCode.postal_code == MALGRAT_CP)
        )
    ).scalars().first()


async def _upsert_user(
    db: AsyncSession,
    *,
    email: str,
    slug: str,
    first_name: str,
    last_name: str,
    is_admin: bool,
    is_merchant: bool,
    shop_id: str | None,
) -> User:
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalars().first()
    if user is None:
        taken = await db.scalar(select(User.id).where(User.slug == slug))
        user = User(
            id=_id(),
            email=email,
            slug=slug if not taken else f"{slug}-{_id()[:6]}",
            first_name=first_name,
            last_name=last_name,
            is_resident=True,
            is_admin=is_admin,
            is_merchant=is_merchant,
            postal_code=MALGRAT_CP,
            shop_id=shop_id,
            lang="ca",
            points=0,
            is_fake=False,
        )
        db.add(user)
        return user
    user.first_name = first_name
    user.last_name = last_name
    user.is_resident = True
    user.is_admin = is_admin
    user.is_merchant = is_merchant
    user.postal_code = MALGRAT_CP
    user.shop_id = shop_id
    user.is_fake = False
    return user


async def _upsert_shop(
    db: AsyncSession,
    *,
    town_id: str,
    email: str,
    name: str,
    key: str,
) -> Shop:
    shop = (
        await db.execute(select(Shop).where(Shop.contact_email == email))
    ).scalars().first()
    qr = f"qr-{key}"[:64]
    if shop is None:
        shop = Shop(
            id=_stable_id(key),
            town_id=town_id,
            name=name,
            emoji="🏪",
            categories=["food"],
            contact_email=email,
            visit_points=10,
            address="Carrer Major, Malgrat de Mar",
            postal_code=MALGRAT_CP,
            status="active",
            qr_code=qr,
            description="Comerç QA local Malgrat (no demo).",
            is_fake=False,
        )
        db.add(shop)
        await db.flush()
        return shop
    shop.town_id = town_id
    shop.name = name
    shop.status = "active"
    shop.is_fake = False
    shop.postal_code = MALGRAT_CP
    if not shop.qr_code:
        shop.qr_code = qr
    return shop


async def ensure_malgrat_qa_accounts(db: AsyncSession) -> list[str]:
    cp = await _malgrat_cp(db)
    if cp is None:
        raise RuntimeError(
            "Malgrat (CP 08380) no existe. Ejecuta primero: python -m scripts.seed"
        )
    town_id = cp.town_id
    notes: list[str] = []

    await _upsert_user(
        db,
        email=ADMIN_MALGRAT_EMAIL,
        slug="admin-malgrat",
        first_name="Admin",
        last_name="Malgrat",
        is_admin=True,
        is_merchant=False,
        shop_id=None,
    )
    notes.append(f"  {ADMIN_MALGRAT_EMAIL} / 123456  -> admin Malgrat (real)")

    for spec in _SHOPS:
        shop = await _upsert_shop(
            db,
            town_id=town_id,
            email=spec["email"],
            name=spec["name"],
            key=spec["key"],
        )
        await db.flush()
        await _upsert_user(
            db,
            email=spec["email"],
            slug=spec["slug"],
            first_name=spec["first_name"],
            last_name=spec["last_name"],
            is_admin=False,
            is_merchant=True,
            shop_id=shop.id,
        )
        notes.append(f"  {spec['email']} / 123456  -> merchant Malgrat (real)")

    return notes
