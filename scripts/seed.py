"""Seed pilot towns, postal codes, admins, shops and sample catalog.

Usage (from repo root, with DB up and migrations applied):

    python -m scripts.seed
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Reward,
    RewardShop,
    Shop,
    ShopCategory,
    Town,
    TownPostalCode,
    User,
)
from app.catalog.point_actions import ensure_town_point_actions
from app.catalog.shop_categories import DEFAULT_SHOP_CATEGORIES
from app.services.points import apply_points
from app.utils.slug import slugify, split_full_name


settings = get_settings()


def _id() -> str:
    return uuid.uuid4().hex


# Pilot emails (Malgrat)
ADMIN_MALGRAT_EMAIL = "albertmalleu@gmail.com"
RESIDENT_MERCHANT_EMAIL = "km0lab_malgrat_user@yopmail.com"

TOWNS = [
    {
        "name": "Malgrat de Mar",
        "entity_name": "Ajuntament de Malgrat de Mar",
        "contact_email": ADMIN_MALGRAT_EMAIL,
        "manager_name": "Albert Malleu",
        "admin_email": ADMIN_MALGRAT_EMAIL,
        "postal_codes": [("08380", True)],
        "pilot_merchant_email": RESIDENT_MERCHANT_EMAIL,
    },
    {
        "name": "Blanes",
        "entity_name": "Ajuntament de Blanes",
        "contact_email": "admin@blanes.cat",
        "manager_name": "Admin Blanes",
        "admin_email": "admin@blanes.cat",
        "postal_codes": [("17300", True)],
        "pilot_merchant_email": None,
    },
    {
        "name": "Lloret de Mar",
        "entity_name": "Ajuntament de Lloret de Mar",
        "contact_email": "admin@lloret.cat",
        "manager_name": "Admin Lloret",
        "admin_email": "admin@lloret.cat",
        "postal_codes": [("17310", True)],
        "pilot_merchant_email": None,
    },
]


async def seed() -> None:
    async with SessionLocal() as db:
        for slug, order in DEFAULT_SHOP_CATEGORIES:
            if await db.get(ShopCategory, slug) is None:
                db.add(ShopCategory(slug=slug, sort_order=order, active=True))
        await db.flush()

        existing = (await db.execute(select(Town))).scalars().first()
        if existing:
            towns = (await db.execute(select(Town))).scalars().all()
            for town in towns:
                n = await ensure_town_point_actions(db, town.id, is_fake=False)
                print(f"Real point actions reset for {town.name}: {n}")
            await db.commit()
            print("Seed skipped: towns already present (categories + actions ensured).")
            return

        for spec in TOWNS:
            town = Town(
                id=_id(),
                name=spec["name"],
                slug=slugify(spec["name"]),
                entity_name=spec["entity_name"],
                entity_type="city_council",
                contact_email=spec["contact_email"],
                manager_name=spec["manager_name"],
            )
            db.add(town)
            await db.flush()

            primary_cp = None
            for code, is_primary in spec["postal_codes"]:
                db.add(
                    TownPostalCode(
                        postal_code=code,
                        town_id=town.id,
                        is_primary=is_primary,
                    )
                )
                if is_primary:
                    primary_cp = code
            await db.flush()

            admin_first, admin_last = split_full_name(spec["manager_name"])
            admin = User(
                id=_id(),
                email=spec["admin_email"],
                slug=slugify(spec["manager_name"] or spec["admin_email"]),
                first_name=admin_first,
                last_name=admin_last,
                is_resident=True,
                is_admin=True,
                is_merchant=False,
                postal_code=primary_cp,
                lang="ca",
                points=0,
            )
            db.add(admin)

            merchant_email = (
                spec["pilot_merchant_email"]
                or f"comerc@{spec['name'].lower().replace(' ', '')}.cat"
            )
            shop = Shop(
                id=_id(),
                town_id=town.id,
                name=f"Botiga Pilot {spec['name']}",
                emoji="🏪",
                categories=["food"],
                contact_email=merchant_email,
                visit_points=10,
                address="Carrer Major 1",
                postal_code=primary_cp,
                status="active",
                qr_code=f"qr-{town.id[:8]}",
                description="Comerç de prova del programa KM0 LAB.",
            )
            db.add(shop)
            await db.flush()

            # Malgrat: same person as resident (app) + merchant (backoffice client).
            if spec["pilot_merchant_email"]:
                merchant = User(
                    id=_id(),
                    email=spec["pilot_merchant_email"],
                    slug="usuari-malgrat",
                    first_name="Usuari",
                    last_name="Malgrat",
                    is_resident=True,
                    is_merchant=True,
                    is_admin=False,
                    postal_code=primary_cp,
                    shop_id=shop.id,
                    lang="ca",
                    points=0,
                )
                db.add(merchant)
                await db.flush()
                await apply_points(
                    db,
                    user=merchant,
                    points=settings.welcome_points,
                    type="welcome",
                    town_id=town.id,
                    description="Welcome bonus",
                )

            await ensure_town_point_actions(db, town.id, is_fake=False)

            reward = Reward(
                id=_id(),
                town_id=town.id,
                name="Descompte 5 €",
                description="Vale de 5 € en comerços adherits",
                type="discount",
                points_required=500,
                value="5€",
                stock=100,
                status="active",
            )
            db.add(reward)
            await db.flush()
            db.add(RewardShop(id=_id(), reward_id=reward.id, shop_id=shop.id))

            db.add(
                Reward(
                    id=_id(),
                    town_id=town.id,
                    name="Experiència local",
                    description="Activitat cultural al municipi",
                    type="experience",
                    points_required=1000,
                    stock=20,
                    status="active",
                )
            )

        await db.commit()
        print(f"Seeded {len(TOWNS)} towns with postal codes, admins and catalog.")
        print(f"  Malgrat admin: {ADMIN_MALGRAT_EMAIL}")
        print(f"  Malgrat resident+merchant: {RESIDENT_MERCHANT_EMAIL}")


if __name__ == "__main__":
    asyncio.run(seed())
