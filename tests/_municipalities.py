"""Two municipalities for scope tests: a single town and a grouped one.

- Malgrat de Mar (08380): one town, named like the municipality.
- Baix Montseny: Breda (17400), Hostalric (17450), Riells i Viabrea (17404).

Mirrors what ``scripts/add_town`` + ``scripts/group_towns`` leave in the
database, and the catalog as ``scripts/seed_demo`` leaves it.
"""

from __future__ import annotations

from sqlalchemy import select

from app.catalog.rewards import seed_fake_rewards
from app.models import Locality, Reward, Town, TownPostalCode, User
from app.roles import flags_from_roles
from app.security import create_access_token
from app.services.localities import ensure_default_locality, group_towns
from app.services.towns import ensure_demo_town
from app.utils.slug import slugify

API = "/api/v1"
BAIX_MONTSENY = {"Breda": "17400", "Hostalric": "17450", "Riells i Viabrea": "17404"}


async def single_town(db, name: str, postal_code: str) -> Town:
    town = Town(name=name, slug=slugify(name), default_visit_points=15)
    db.add(town)
    await db.flush()
    db.add(TownPostalCode(postal_code=postal_code, town_id=town.id, is_primary=True))
    await db.flush()
    await ensure_default_locality(db, town)
    return town


async def malgrat(db) -> Town:
    return await single_town(db, "Malgrat de Mar", "08380")


async def baix_montseny(db) -> Town:
    for name, code in BAIX_MONTSENY.items():
        await single_town(db, name, code)
    await group_towns(
        db,
        name="Baix Montseny",
        postal_codes=list(BAIX_MONTSENY.values()),
        dry_run=False,
    )
    return (
        await db.execute(select(Town).where(Town.slug == "baix-montseny"))
    ).scalars().one()


async def locality(db, name: str) -> Locality:
    return (
        await db.execute(select(Locality).where(Locality.name == name))
    ).scalars().one()


async def catalog(db) -> Town:
    """Demo KM0 with the reward catalog in it."""
    demo = await ensure_demo_town(db)
    await seed_fake_rewards(db, town_id=demo.id)
    return demo


async def admin_headers(
    db, town: Town, postal_code: str, *, is_fake: bool = False
) -> dict[str, str]:
    """An administrator of ``town``, tied to it through ``postal_code``."""
    slug = f"admin-{slugify(town.name)}"
    user = User(
        email=f"{slug}@test.cat",
        slug=slug,
        postal_code=postal_code,
        points=0,
        is_fake=is_fake,
        **flags_from_roles(["admin", "resident"]),
    )
    db.add(user)
    await db.commit()
    token = create_access_token(
        user.id, roles=["admin", "resident"], town_id=town.id
    )
    return {"Authorization": f"Bearer {token}"}


async def rewards_of(db, town: Town) -> dict[str, Reward]:
    rows = (
        await db.execute(
            select(Reward)
            .where(Reward.town_id == town.id, Reward.is_fake.is_(False))
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return {r.name: r for r in rows}
