"""Seed pilot towns, admins, shops and sample catalog data.

Usage (from repo root, with DB up and migrations applied):

    python -m scripts.seed
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    PointAction,
    Reward,
    RewardShop,
    Shop,
    Town,
    User,
)


def _id() -> str:
    return uuid.uuid4().hex


TOWNS = [
    {
        "name": "Malgrat de Mar",
        "entity_name": "Ajuntament de Malgrat de Mar",
        "contact_email": "admin@malgrat.cat",
        "manager_name": "Admin Malgrat",
        "admin_email": "admin@malgrat.cat",
    },
    {
        "name": "Blanes",
        "entity_name": "Ajuntament de Blanes",
        "contact_email": "admin@blanes.cat",
        "manager_name": "Admin Blanes",
        "admin_email": "admin@blanes.cat",
    },
    {
        "name": "Lloret de Mar",
        "entity_name": "Ajuntament de Lloret de Mar",
        "contact_email": "admin@lloret.cat",
        "manager_name": "Admin Lloret",
        "admin_email": "admin@lloret.cat",
    },
]


async def seed() -> None:
    async with SessionLocal() as db:
        existing = (await db.execute(select(Town))).scalars().first()
        if existing:
            print("Seed skipped: towns already present.")
            return

        for spec in TOWNS:
            town = Town(
                id=_id(),
                name=spec["name"],
                entity_name=spec["entity_name"],
                entity_type="city_council",
                contact_email=spec["contact_email"],
                manager_name=spec["manager_name"],
                points_per_euro=200,
                default_visit_points=10,
                default_lang="ca",
            )
            db.add(town)
            await db.flush()

            admin = User(
                id=_id(),
                email=spec["admin_email"],
                name=spec["manager_name"],
                role="admin",
                town_id=town.id,
                lang="ca",
                points=0,
            )
            db.add(admin)

            shop = Shop(
                id=_id(),
                town_id=town.id,
                name=f"Botiga Pilot {spec['name']}",
                emoji="🏪",
                categories=["Alimentació"],
                contact_email=f"comerc@{spec['name'].lower().replace(' ', '')}.cat",
                visit_points=10,
                address="Carrer Major 1",
                status="active",
                qr_code=f"qr-{town.id[:8]}",
                description="Comerç de prova del programa KM0 LAB.",
            )
            db.add(shop)
            await db.flush()

            db.add(
                PointAction(
                    id=_id(),
                    town_id=town.id,
                    type="signup",
                    name="Registre al programa",
                    description="Punts de benvinguda",
                    points=100,
                    active=True,
                )
            )
            db.add(
                PointAction(
                    id=_id(),
                    town_id=town.id,
                    type="qr_scan",
                    name="Escaneig QR comerç",
                    description="Visita a un comerç adherit",
                    points=10,
                    per_user_limit=1,
                    active=True,
                    shop_id=shop.id,
                )
            )

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
        print(f"Seeded {len(TOWNS)} towns with admins, shops and sample catalog.")


if __name__ == "__main__":
    asyncio.run(seed())
