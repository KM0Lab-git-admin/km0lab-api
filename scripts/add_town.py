"""Register one real town: the town, its postal codes and the default actions.

Usage (from repo root):

    python -m scripts.add_town --name "Breda" --postal-code 17400
    python -m scripts.add_town --name "Breda" --postal-code 17400 --apply
    python -m scripts.add_town --name "Breda" --postal-code 17400 --target railway --apply

Only adds. It creates no accounts, shops or rewards: those belong to the
town's own admin. If the town or any of its postal codes already exists it
changes nothing. Without --apply it only shows what it would do. With
--target railway it writes to UAT, so it only runs when the user asks to
publish.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, point_at


async def _run(name: str, postal_codes: list[str], entity_name: str, apply: bool) -> None:
    from sqlalchemy import select

    from app.catalog.point_actions import DEFAULT_POINT_ACTIONS, ensure_town_point_actions
    from app.db import SessionLocal
    from app.models import Town, TownPostalCode
    from app.utils.slug import slugify

    slug = slugify(name)
    async with SessionLocal() as db:
        by_slug = (
            await db.execute(select(Town).where(Town.slug == slug))
        ).scalar_one_or_none()
        taken = (
            (
                await db.execute(
                    select(TownPostalCode).where(
                        TownPostalCode.postal_code.in_(postal_codes)
                    )
                )
            )
            .scalars()
            .all()
        )
        if by_slug is not None or taken:
            if by_slug is not None:
                print(f"  {name}: town '{slug}' already exists. Nothing to do.")
            for row in taken:
                print(f"  {name}: postal code {row.postal_code} already belongs to a town. Nothing to do.")
            return

        print(f"  {name}: add town '{slug}' ({entity_name})")
        print(f"  {name}: add postal codes {', '.join(postal_codes)} (primary {postal_codes[0]})")
        print(f"  {name}: add {len(DEFAULT_POINT_ACTIONS)} default point actions")
        if not apply:
            print("  Nothing written: run again with --apply.")
            return

        town = Town(
            name=name,
            slug=slug,
            entity_name=entity_name,
            entity_type="city_council",
            contact_email="",
            manager_name="",
        )
        db.add(town)
        await db.flush()
        for i, code in enumerate(postal_codes):
            db.add(TownPostalCode(postal_code=code, town_id=town.id, is_primary=i == 0))
        await db.flush()
        # The town a resident sees: one locality named like the municipality.
        from app.services.localities import ensure_default_locality

        await ensure_default_locality(db, town)
        created = await ensure_town_point_actions(db, town.id, is_fake=False)
        await db.commit()
        print(f"  {name}: written (id {town.id}, {created} actions)")


async def main(args: argparse.Namespace) -> None:
    from app.db import engine

    try:
        await _run(
            args.name.strip(),
            [c.strip() for c in args.postal_code],
            (args.entity_name or f"Ajuntament de {args.name.strip()}").strip(),
            args.apply,
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--postal-code", required=True, action="append")
    parser.add_argument("--entity-name", default=None)
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    asyncio.run(main(parsed))
