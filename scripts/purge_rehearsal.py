"""Remove the accounts of one rehearsal from a municipality.

Usage (from repo root):

    python -m scripts.purge_rehearsal --town Blanes --email a@example.com --email b@example.com
    python -m scripts.purge_rehearsal --town Blanes --email a@example.com --apply
    python -m scripts.purge_rehearsal --town Blanes --email a@example.com --target railway
    python -m scripts.purge_rehearsal --town Blanes --email a@example.com --target railway --apply

Without --apply it only shows what it would delete. --target railway is UAT
and --apply against it only runs when someone asks to publish. The
municipality's account cap is never changed.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, guard_write, point_at


async def _run(args: argparse.Namespace) -> int:
    from app.db import SessionLocal
    from app.services.rehearsal_purge import RehearsalRefused, purge_rehearsal

    async with SessionLocal() as db:
        try:
            report = await purge_rehearsal(
                db, town=args.town, emails=args.email, dry_run=not args.apply
            )
        except RehearsalRefused as exc:
            await db.rollback()
            print(f"  REFUSED: {exc}")
            return 1
        if args.apply:
            await db.commit()
        else:
            await db.rollback()
    for line in report.lines():
        print(f"  {line}")
    if not args.apply and not report.nothing:
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
    parser.add_argument("--town", required=True)
    parser.add_argument("--email", action="append", default=[])
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    guard_write(parsed.target, apply=parsed.apply, confirm=parsed.confirm)
    raise SystemExit(asyncio.run(main(parsed)))
