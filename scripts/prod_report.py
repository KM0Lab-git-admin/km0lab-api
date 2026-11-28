"""Read what a production load left behind. It never writes.

Usage (from repo root):

    python -m scripts.prod_report
    python -m scripts.prod_report --target production
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, point_at


async def _run() -> int:
    from app.db import SessionLocal
    from app.services.prod_seed import production_counts

    async with SessionLocal() as db:
        counts = await production_counts(db)
        await db.rollback()
    print(f"  postal codes: {counts['postal_codes']}")
    print(f"  localities: {counts['localities']}")
    print(f"  administrators: {counts['administrators']}")
    print(f"  accounts: {counts['accounts']}")
    print(f"  shops: {counts['shops']}")
    for town in counts["municipalities"]:
        cap = "unlimited" if town["capacity"] is None else town["capacity"]
        actions = ", ".join(
            f"{row['type']} {row['points']}" for row in town["actions"]
        ) or "none"
        print(
            f"  {town['name']}: postals {town['postals']}, "
            f"capacity {cap}, rewards {town['rewards']}, actions {actions}"
        )
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
