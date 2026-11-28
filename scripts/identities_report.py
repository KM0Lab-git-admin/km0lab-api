"""How residents came in, across every municipality (read only).

Usage (from repo root):

    python -m scripts.identities_report
    python -m scripts.identities_report --target railway

Each administrator sees the figure of their own municipality in the panel
("12 by email, 5 by Google…"). No panel adds municipalities together: this
prints the total and the breakdown by municipality.

It counts the door each account was **born** with, residents only, and
leaves out demonstration and test accounts. An account created by a script
that never logged in has no door yet and is listed as "never came in".

It never writes: with --target railway it only reads UAT.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, point_at

LABELS = {
    "email_code": "code by email",
    "google": "Google",
    "facebook": "Facebook",
    "apple": "Apple",
}


def _line(name: str, counts: dict[str, int], never: int) -> str:
    total = sum(counts.values())
    parts = [
        f"{LABELS[provider]} {n}" + (f" ({round(100 * n / total)}%)" if total else "")
        for provider, n in counts.items()
    ]
    tail = f" · never came in {never}" if never else ""
    return f"  {name}: {total} · " + " · ".join(parts) + tail


async def _run() -> int:
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Town, TownPostalCode, User, UserIdentity
    from app.services.identities import signups_by_provider

    async with SessionLocal() as db:

        async def never_came_in(town_id: str | None) -> int:
            stmt = (
                select(func.count(func.distinct(User.id)))
                .select_from(User)
                .where(
                    User.is_resident.is_(True),
                    User.is_fake.is_(False),
                    User.id.notin_(select(UserIdentity.user_id)),
                )
            )
            if town_id is not None:
                stmt = stmt.join(
                    TownPostalCode, User.postal_code == TownPostalCode.postal_code
                ).where(TownPostalCode.town_id == town_id)
            return int(await db.scalar(stmt) or 0)

        everyone = await signups_by_provider(db, town_id=None, is_fake=False)
        print(_line("All municipalities", everyone, await never_came_in(None)))
        towns = (await db.execute(select(Town).order_by(Town.name))).scalars().all()
        for town in towns:
            counts = await signups_by_provider(db, town_id=town.id, is_fake=False)
            never = await never_came_in(town.id)
            if sum(counts.values()) or never:
                print(_line(town.name, counts, never))
        await db.rollback()
    return 0


async def main() -> int:
    from app.db import engine

    try:
        return await _run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, default="local")
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    raise SystemExit(asyncio.run(main()))
