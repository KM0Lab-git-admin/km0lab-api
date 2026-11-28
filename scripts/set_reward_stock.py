"""Set how many units of a reward are left in one municipality.

Usage (from repo root):

    python -m scripts.set_reward_stock --town "Malgrat de Mar" --reward "Bono 50 €" --stock 5
    python -m scripts.set_reward_stock --town "Malgrat de Mar" --reward "Bono 50 €" --stock 5 --apply
    python -m scripts.set_reward_stock ... --target railway --apply

The catalog (names, points, images) is shared by every municipality; stock
is each municipality's own and nothing in the backoffice sets it. Use this
to cap what a pilot can redeem, or to top up units.

``--town`` is the municipality: its name, its slug, the name of one of its
towns or one of its postal codes. ``--reward`` is the reward's name in any
language, as the app shows it, or its id. Reaching 0 marks it sold out;
topping up a sold-out reward puts it back on offer; one the administrator
switched off stays off.

Without --apply it only shows what it would do. With --target railway it
writes to UAT, so it only runs when the user asks to publish.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, guard_write, point_at


async def _run(args: argparse.Namespace) -> int:
    from app.db import SessionLocal
    from app.services.reward_stock import StockRefused, set_reward_stock
    from app.services.towns import find_municipality

    async with SessionLocal() as db:
        town = await find_municipality(db, args.town)
        if town is None:
            print(f"  REFUSED: no municipality matches '{args.town}'.")
            return 1
        try:
            report = await set_reward_stock(
                db, town=town, reward=args.reward, stock=args.stock
            )
        except StockRefused as exc:
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
    parser.add_argument("--reward", required=True)
    parser.add_argument("--stock", required=True, type=int)
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    guard_write(parsed.target, apply=parsed.apply, confirm=parsed.confirm)
    raise SystemExit(asyncio.run(main(parsed)))
