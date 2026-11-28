"""Delete the shop requests that were rejected more than 30 days ago.

Usage (from repo root):

    python -m scripts.purge_rejected_shops
    python -m scripts.purge_rejected_shops --apply
    python -m scripts.purge_rejected_shops --target railway --apply

A shop that asks to join and is rejected is told its data will be deleted
within 30 days (``app/services/shop_review.py``). This is what deletes it:
the request, its pictures and the note of who invited it. The account of
whoever asked is a resident's and is not touched.

Nothing runs it on its own yet: run it once a month, or put it on a timer.
The 30 days count from the rejection (``shops.updated_at``; a rejected
request cannot be edited, so nothing else moves that date).

Without --apply it only lists what it would delete. With --target railway
it writes to UAT, so it only runs when the user asks to publish.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, guard_write, point_at


async def _run(args: argparse.Namespace) -> int:
    from app.db import SessionLocal
    from app.services.shop_review import purge_rejected_shops

    async with SessionLocal() as db:
        rows = await purge_rejected_shops(db, older_than_days=args.days, apply=args.apply)
        if args.apply:
            await db.commit()
        else:
            await db.rollback()
    if not rows:
        print(f"  No rejected request is older than {args.days} days.")
        return 0
    for name, rejected_at in rows:
        print(f"  {'deleted' if args.apply else 'would delete'}: {name} (rejected {rejected_at:%Y-%m-%d})")
    if not args.apply:
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
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    guard_write(parsed.target, apply=parsed.apply, confirm=parsed.confirm)
    raise SystemExit(asyncio.run(main(parsed)))
