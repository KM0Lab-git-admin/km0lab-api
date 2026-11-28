"""Register the administrator of a municipality that already exists.

Usage (from repo root):

    python -m scripts.add_admin --town "Baix Montseny" --email someone@example.org
    python -m scripts.add_admin --town "Baix Montseny" --email someone@example.org --apply
    python -m scripts.add_admin ... --target railway --apply

``--town`` is the municipality: its name, its slug, the name of one of its
towns or one of its postal codes. The account has no password: the person
enters the backoffice with that email and the code sent to it.

It refuses when the municipality already has an administrator (pass
``--additional`` to add another on purpose) and when the email belongs to a
merchant, to the admin of another municipality or to a resident of another
town. See ``app/services/admins.py``.

Without --apply it only shows what it would do. With --target railway it
writes to UAT, so it only runs when the user asks to publish.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, guard_write, point_at


async def _run(args: argparse.Namespace) -> int:
    from app.db import SessionLocal
    from app.services.admins import AdminRefused, register_admin
    from app.services.towns import find_municipality

    async with SessionLocal() as db:
        town = await find_municipality(db, args.town)
        if town is None:
            print(f"  REFUSED: no municipality matches '{args.town}'.")
            return 1
        try:
            report = await register_admin(
                db,
                town=town,
                email=args.email,
                first_name=args.first_name,
                last_name=args.last_name,
                allow_additional=args.additional,
            )
        except AdminRefused as exc:
            await db.rollback()
            print(f"  REFUSED: {exc}")
            return 1
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
    parser.add_argument("--town", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--first-name", default=None)
    parser.add_argument("--last-name", default=None)
    parser.add_argument("--additional", action="store_true")
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    guard_write(parsed.target, apply=parsed.apply, confirm=parsed.confirm)
    raise SystemExit(asyncio.run(main(parsed)))
