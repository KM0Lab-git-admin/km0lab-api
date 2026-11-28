"""Make the demonstration presentable.

Usage (from repo root):

    python -m scripts.tidy_demo
    python -m scripts.tidy_demo --apply
    python -m scripts.tidy_demo --target railway
    python -m scripts.tidy_demo --target railway --apply

Without --apply it only shows what it would change. --target railway is UAT
and --apply against it only runs when someone asks to publish. Shop logos
are not created: that waits on a decision about the pictures.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, guard_write, point_at


async def _run(args: argparse.Namespace) -> int:
    from app.db import SessionLocal
    from app.services.tidy_demo import tidy_demo

    async with SessionLocal() as db:
        report = await tidy_demo(db, apply=args.apply)
        if args.apply:
            await db.commit()
        else:
            await db.rollback()
    for line in report.lines():
        print(f"  {line}")
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
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    guard_write(parsed.target, apply=parsed.apply, confirm=parsed.confirm)
    raise SystemExit(asyncio.run(main(parsed)))
