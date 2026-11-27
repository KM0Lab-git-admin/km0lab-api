"""Group several towns under one municipality.

Usage (from repo root):

    python -m scripts.group_towns --name "Baix Montseny" --postal-code 17400 --postal-code 17450 --postal-code 17404
    python -m scripts.group_towns --name "Baix Montseny" --postal-code 17400 --postal-code 17450 --postal-code 17404 --apply
    python -m scripts.group_towns ... --target railway --apply

A municipality is the managed scope: one admin, one set of point rules,
actions and rewards. The towns inside it keep their name, postal codes and
illustration; shops belong to one of them. See ``app/models.Locality``.

Each postal code must already exist (``scripts/add_town.py``) as a town on
its own. This moves those towns into the municipality — created if missing,
with the default actions — and removes the emptied ones. It refuses if a
town already has activity of its own (rewards, redemptions, point movements,
invitation links or an admin): that has to be decided by hand.

Without --apply it only shows what it would do. With --target railway it
writes to UAT, so it only runs when the user asks to publish.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, point_at


async def _run(name: str, postal_codes: list[str], apply: bool) -> int:
    from app.db import SessionLocal
    from app.services.localities import GroupRefused, group_towns

    async with SessionLocal() as db:
        try:
            report = await group_towns(
                db, name=name, postal_codes=postal_codes, dry_run=not apply
            )
        except GroupRefused as exc:
            await db.rollback()
            print(f"  REFUSED: {exc}")
            return 1
        if apply:
            await db.commit()
        else:
            await db.rollback()
    for line in report.lines():
        print(f"  {line}")
    if not apply:
        print("  Nothing written: run again with --apply.")
    return 0


async def main(args: argparse.Namespace) -> int:
    from app.db import engine

    try:
        return await _run(
            args.name.strip(), [c.strip() for c in args.postal_code], args.apply
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--postal-code", required=True, action="append")
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    raise SystemExit(asyncio.run(main(parsed)))
