"""The pieces of a production load that are not a whole demo.

Categories, and the demonstration town as a catalog of rewards. No demo
accounts, shops, promotions or points movements. Callers commit.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.rewards import (
    FAKE_DEMO_REWARDS,
    seed_fake_rewards,
    upsert_demo_reward_images,
)
from app.catalog.shop_categories import (
    DEFAULT_SHOP_CATEGORIES,
    DEFAULT_SHOP_CATEGORY_EMOJIS,
)
from app.demo import DEMO_TOWN_SLUG
from app.models import (
    Locality,
    PointAction,
    Reward,
    Shop,
    ShopCategory,
    Town,
    TownPostalCode,
    User,
)
from app.services.towns import ensure_demo_town


async def missing_shop_categories(db: AsyncSession) -> list[str]:
    missing = []
    for slug, _order in DEFAULT_SHOP_CATEGORIES:
        if await db.get(ShopCategory, slug) is None:
            missing.append(slug)
    return missing


async def ensure_shop_categories(db: AsyncSession, *, apply: bool) -> list[str]:
    """Categories that are absent. Created only when ``apply`` is true."""
    missing = await missing_shop_categories(db)
    if apply:
        for slug, order in DEFAULT_SHOP_CATEGORIES:
            if slug not in missing:
                continue
            db.add(
                ShopCategory(
                    slug=slug,
                    sort_order=order,
                    active=True,
                    emoji=DEFAULT_SHOP_CATEGORY_EMOJIS.get(slug),
                )
            )
        await db.flush()
    return missing


async def seed_catalog(db: AsyncSession, *, apply: bool) -> tuple[int, int]:
    """Demo town plus its reward catalog and images. Returns (new, images)."""
    if not apply:
        town = (
            await db.execute(select(Town).where(Town.slug == DEMO_TOWN_SLUG))
        ).scalars().first()
        if town is None:
            return len(FAKE_DEMO_REWARDS), sum(
                1 for spec in FAKE_DEMO_REWARDS if spec.get("image")
            )
        have = set(
            (
                await db.execute(
                    select(Reward.name).where(
                        Reward.town_id == town.id, Reward.is_fake.is_(True)
                    )
                )
            ).scalars().all()
        )
        missing = [spec for spec in FAKE_DEMO_REWARDS if spec["name"] not in have]
        return len(missing), sum(1 for spec in missing if spec.get("image"))

    town = await ensure_demo_town(db)
    before = int(
        await db.scalar(
            select(func.count()).select_from(Reward).where(Reward.town_id == town.id)
        )
        or 0
    )
    # The catalog helper reports "how many specs" once they already exist,
    # so the number of new rows is counted here.
    await seed_fake_rewards(db, town_id=town.id, shop_id=None)
    images = await upsert_demo_reward_images(db, town_id=town.id)
    after = int(
        await db.scalar(
            select(func.count()).select_from(Reward).where(Reward.town_id == town.id)
        )
        or 0
    )
    return after - before, images


async def production_counts(db: AsyncSession) -> dict[str, object]:
    """A read of what a load left behind. No writes."""
    towns = list((await db.execute(select(Town).order_by(Town.name))).scalars().all())
    postals = int(await db.scalar(select(func.count()).select_from(TownPostalCode)) or 0)
    localities = int(await db.scalar(select(func.count()).select_from(Locality)) or 0)
    admins = int(
        await db.scalar(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        )
        or 0
    )
    accounts = int(await db.scalar(select(func.count()).select_from(User)) or 0)
    shops = int(await db.scalar(select(func.count()).select_from(Shop)) or 0)
    actions = list(
        (
            await db.execute(
                select(PointAction).where(PointAction.active.is_(True)).order_by(
                    PointAction.town_id, PointAction.type
                )
            )
        ).scalars().all()
    )
    rewards = list(
        (await db.execute(select(Reward.town_id, Reward.id))).all()
    )
    per_town: dict[str, int] = {}
    for town_id, _reward_id in rewards:
        per_town[town_id] = per_town.get(town_id, 0) + 1
    return {
        "municipalities": [
            {
                "name": town.name,
                "postals": int(
                    await db.scalar(
                        select(func.count())
                        .select_from(TownPostalCode)
                        .where(TownPostalCode.town_id == town.id)
                    )
                    or 0
                ),
                "capacity": town.max_residents,
                "rewards": per_town.get(town.id, 0),
                "actions": [
                    {"type": action.type, "points": action.points}
                    for action in actions
                    if action.town_id == town.id
                ],
            }
            for town in towns
        ],
        "postal_codes": postals,
        "localities": localities,
        "administrators": admins,
        "accounts": accounts,
        "shops": shops,
    }
