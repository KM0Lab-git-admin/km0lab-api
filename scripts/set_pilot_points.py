"""Put every municipality on the points of the pilot.

Usage (from repo root):

    python -m scripts.set_pilot_points                      # shows, writes nothing
    python -m scripts.set_pilot_points --town "Malgrat de Mar"
    python -m scripts.set_pilot_points --apply
    python -m scripts.set_pilot_points --target railway            # rehearsal on UAT
    python -m scripts.set_pilot_points --target railway --apply    # writes to UAT

What it leaves (``app/services/pilot_points.py``):

- Signing up 50 points, scanning a QR 100, inviting a friend 50. Every
  other action (birthday, inviting a business, the rest) switched off.
- 100 points = 1 EUR. A reward whose value is an amount in euros costs that
  amount x 100; the KM0 LAB T-shirt, 1000. The number on each shop's card
  and "points per 1 EUR" in the municipality's settings follow.

Every municipality, the demonstration included; never the QA territory.
``--town`` limits it to one (name, slug, one of its towns or postal codes).

It can be run again: it sets values, it does not multiply what is there.
Rewards the rule does not cover (percentages, products without a price) are
left as they are and listed under "TO DECIDE". Points residents already hold
are not touched: the last lines say how many accounts hold some.

Without --apply it only reads. With --target railway --apply it writes to
UAT, so it only runs when the user asks to publish.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from scripts._target import TARGETS, point_at

KIND_LABEL = {
    "municipality": "municipality",
    "shops": "shops",
    "action": "action",
    "reward": "reward",
}


def _print_report(report) -> None:
    from app.services.pilot_points import SCAN_POINTS

    print(f"\n== {report.name} ({report.slug})")
    if not report.changes:
        print(f"   nothing to change ({report.unchanged} values already right)")
    for c in report.changes:
        print(f"   {KIND_LABEL[c.kind]:<13}{c.what}: {c.before} -> {c.after}")
    if report.changes and report.unchanged:
        print(f"   ({report.unchanged} other values already right)")
    days = report.scan_cooldown_days
    print(
        "   same shop again: "
        + (f"every {days} days" if days is not None else "every 30 days (no rule set)")
    )
    if report.undecided:
        print("   TO DECIDE (left as they are):")
        for r in report.undecided:
            scans = r.points / SCAN_POINTS
            origin = "own" if r.own else "catalog"
            print(
                f"     - «{r.name}» [{r.type}, {r.value or 'no value'}, {origin}, "
                f"{r.status}]: {r.points} points = {scans:g} scans"
            )
    for label, (accounts, points) in (
        ("test accounts", report.balances_test),
        ("OTHER accounts", report.balances_other),
    ):
        if accounts:
            print(f"   balance on the old scale: {accounts} {label}, {points} points")


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy import text

    from app.db import SessionLocal
    from app.services.pilot_points import (
        is_pilot_town,
        pilot_towns,
        set_pilot_points,
    )
    from app.services.towns import find_municipality

    async with SessionLocal() as db:
        if not args.apply and db.bind.dialect.name == "mysql":
            # A rehearsal cannot write even by mistake.
            await db.execute(text("SET SESSION TRANSACTION READ ONLY"))
        if args.town:
            town = await find_municipality(db, args.town)
            if town is None:
                print(f"  REFUSED: no municipality matches '{args.town}'.")
                return 1
            if not is_pilot_town(town):
                print("  REFUSED: the QA territory keeps its own numbers.")
                return 1
            towns = [town]
        else:
            towns = await pilot_towns(db)

        reports = [await set_pilot_points(db, t, apply=args.apply) for t in towns]
        if args.apply:
            await db.commit()
        else:
            await db.rollback()

    for report in reports:
        _print_report(report)
    total = sum(len(r.changes) for r in reports)
    undecided = sum(len(r.undecided) for r in reports)
    print(
        f"\n{len(reports)} municipalities, {total} changes"
        f"{' written' if args.apply else ''}, {undecided} rewards to decide."
    )
    if not args.apply:
        print("Nothing written: run again with --apply.")
    return 0


async def main(args: argparse.Namespace) -> int:
    from app.db import engine

    try:
        return await _run(args)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--town", default=None)
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Database: {point_at(parsed.target)}")
    raise SystemExit(asyncio.run(main(parsed)))
