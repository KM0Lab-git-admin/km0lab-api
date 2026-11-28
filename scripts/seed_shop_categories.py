"""Create the shop categories that are not there yet.

Usage (from repo root):

    python -m scripts.seed_shop_categories
    python -m scripts.seed_shop_categories --apply
    python -m scripts.seed_shop_categories --target production --apply --confirm <database>

Without --apply it only lists the missing slugs. Existing categories are
left as they are.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, guard_write, point_at


async def _run(apply: bool) -> int:
    from app.db import SessionLocal
    from app.services.prod_seed import ensure_shop_categories

    async with SessionLocal() as db:
        missing = await ensure_shop_categories(db, apply=apply)
        if apply:
            await db.commit()
        else:
            await db.rollback()
    if not missing:
        print("  unchanged: every shop category is already there")
    else:
        print("  missing: " + ", ".join(missing))
    if not apply and missing:
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
