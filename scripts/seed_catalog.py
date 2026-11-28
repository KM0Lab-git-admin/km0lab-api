"""Create the demonstration town and its reward catalog.

The town is the source other municipalities copy from. This does not
create demo accounts, shops, promotions or points movements.

Usage (from repo root):

    python -m scripts.seed_catalog
    python -m scripts.seed_catalog --apply
    python -m scripts.seed_catalog --target production --apply --confirm <database>
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, guard_write, point_at


async def _run(apply: bool) -> int:
    from app.db import SessionLocal
    from app.services.prod_seed import seed_catalog

    async with SessionLocal() as db:
        created, images = await seed_catalog(db, apply=apply)
        if apply:
            await db.commit()
        else:
            await db.rollback()
    print(f"  rewards to add: {created}")
    print(f"  images to attach: {images}")
    if not apply and (created or images):
        print("  Nothing written: run again with --apply.")
    return 0


async def main(apply: bool) -> int:
    from app.db import engine

    try:
        return await _run(apply)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    guard_write(parsed.target, apply=parsed.apply, confirm=parsed.confirm)
    raise SystemExit(asyncio.run(main(parsed.apply)))
