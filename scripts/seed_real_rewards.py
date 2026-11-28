"""Copy the reward catalog to real municipalities.

Usage (from repo root):

    python -m scripts.seed_real_rewards --town "Baix Montseny"
    python -m scripts.seed_real_rewards --town "Baix Montseny" --apply
    python -m scripts.seed_real_rewards --all
    python -m scripts.seed_real_rewards --town 08380 --target railway --apply

The catalog is edited once, in Demo KM0 (CP 00000), and is the same for
every municipality. This copies it:

- a reward the municipality does not have yet is created **active** (with
  the catalog's status): its administrator can switch it off;
- a reward it already has gets the catalog's texts, points and image, and
  **keeps its status and its stock**;
- a copy whose catalog reward is gone is deleted if nobody redeemed it,
  otherwise kept and switched off;
- a reward that is not a copy of the catalog is listed and left alone.

``--town`` is a municipality: name, slug, the name of one of its towns or
a postal code. ``--all`` does every real municipality.

Without --apply it only shows what it would do. With --target railway it
writes to UAT, so it only runs when the user asks to publish.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts._target import TARGETS, guard_write, point_at  # noqa: E402


def _print(town_name: str, report) -> None:
    def show(label: str, names: list[str]) -> None:
        if names:
            print(f"  {town_name}: {label} ({len(names)}): {', '.join(names)}")

    show("new, offered to residents from now on", report.created)
    show("already there, status and stock kept", report.updated)
    for old, new in report.renamed:
        print(f"  {town_name}: renamed '{old}' -> '{new}'")
    for change in report.changed:
        print(f"  {town_name}: CHANGES {change}")
    show("gone from the catalog, redeemed: kept and switched off", report.retired)
    show("gone from the catalog, never redeemed: deleted", report.deleted)
    show("not from the catalog, left alone", report.untouched)
    if not (report.created or report.updated or report.untouched):
        print(f"  {town_name}: nothing to do")


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.catalog.rewards import sync_catalog_rewards
    from app.db import SessionLocal
    from app.demo import is_fake_postal_code
    from app.models import Shop, Town, TownPostalCode
    from app.services.towns import ensure_demo_town, find_municipality

    async with SessionLocal() as db:
        demo = await ensure_demo_town(db)
        if args.town:
            town = await find_municipality(db, args.town)
            if town is None:
                print(f"  REFUSED: no municipality matches '{args.town}'.")
                return 1
            towns = [town]
        else:
            towns = list(
                (await db.execute(select(Town).order_by(Town.name))).scalars().all()
            )

        done = 0
        for town in towns:
            codes = (
                await db.execute(
                    select(TownPostalCode.postal_code).where(
                        TownPostalCode.town_id == town.id
                    )
                )
            ).scalars().all()
            # The catalog itself and the test territory are not destinations.
            if town.id == demo.id or any(is_fake_postal_code(c) for c in codes):
                if args.town:
                    print(f"  REFUSED: {town.name} is a demo or test territory.")
                    return 1
                continue
            shop_id = (
                await db.execute(
                    select(Shop.id).where(
                        Shop.town_id == town.id, Shop.is_fake.is_(False)
                    )
                )
            ).scalars().first()
            report = await sync_catalog_rewards(db, town_id=town.id, shop_id=shop_id)
            _print(town.name, report)
            done += 1

        if not done:
            print("  No real municipality found.")
        if args.apply:
            await db.commit()
        else:
            await db.rollback()
            print("  Nothing written: run again with --apply.")
    return 0


async def main(args: argparse.Namespace) -> int:
    from app.db import engine

    try:
        return await _run(args)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--town", default=None)
    which.add_argument("--all", action="store_true")
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    guard_write(parsed.target, apply=parsed.apply, confirm=parsed.confirm)
    raise SystemExit(asyncio.run(main(parsed)))
