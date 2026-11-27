"""Refresh demo reward catalog images (and insert missing gorra/cinema).

Usage (from repo root, with DB up):

    python -m scripts.seed_reward_images

Does not change existing points or names. PNG sources live in
scripts/seed_media/rewards/ (ported from Lovable, never /__l5e/ URLs).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.catalog.rewards import seed_fake_rewards
from app.db import SessionLocal
from app.models import Reward, Shop, Town


async def _towns_with_fake_rewards(db) -> list[Town]:
    town_ids = (
        await db.execute(
            select(Reward.town_id).where(Reward.is_fake.is_(True)).distinct()
        )
    ).scalars().all()
    if not town_ids:
        return []
    return list(
        (await db.execute(select(Town).where(Town.id.in_(town_ids))))
        .scalars()
        .all()
    )


async def _demo_shop_id(db, town_id: str) -> str | None:
    shop = (
        await db.execute(
            select(Shop).where(
                Shop.town_id == town_id,
                Shop.qr_code == "DEMO-KM0-QR",
            )
        )
    ).scalars().first()
    if shop is not None:
        return shop.id
    return (
        await db.execute(select(Shop.id).where(Shop.town_id == town_id).limit(1))
    ).scalar_one_or_none()


async def main() -> None:
    async with SessionLocal() as db:
        towns = await _towns_with_fake_rewards(db)
        if not towns:
            print("No fake towns found. Run: python -m scripts.seed_demo")
            return
        total_rewards = 0
        for town in towns:
            shop_id = await _demo_shop_id(db, town.id)
            count = await seed_fake_rewards(
                db, town_id=town.id, shop_id=shop_id
            )
            total_rewards += count
            print(f"  {town.name}: catalog refreshed ({count} specs)")
        await db.commit()
        with_media = (
            await db.execute(
                select(Reward.id).where(
                    Reward.is_fake.is_(True),
                    Reward.image_url.is_not(None),
                )
            )
        ).scalars().all()
        print(f"Done. Fake rewards with image_url: {len(with_media)}")
        print(f"Specs processed: {total_rewards}")


if __name__ == "__main__":
    asyncio.run(main())
