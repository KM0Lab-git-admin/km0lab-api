"""Delete QA test data (CP 9999x, ``qa+…@km0lab.com``).

    python -m scripts.purge_qa                 # shows what would go (no changes)
    python -m scripts.purge_qa --apply         # deletes what test runs created
    python -m scripts.purge_qa --all --apply   # deletes the whole territory

By default it only **shows** what it would delete. It refuses to delete
anything if a row in scope is not flagged ``is_fake`` or a QA town is not
named ``[QA] …``. Refuses to run in production. See ``app/qa.py``.

Works on the database configured in the environment (the local one,
unless you are running inside the UAT service).
"""

from __future__ import annotations

import argparse
import asyncio

from app.db import SessionLocal
from app.demo import demo_enabled
from app.services.qa_purge import QaPurgeRefused, purge_qa_territory


async def purge_qa(*, everything: bool, older_than: int, apply: bool) -> int:
    if not demo_enabled():
        print("QA territory is disabled in production.")
        return 2
    async with SessionLocal() as db:
        try:
            report = await purge_qa_territory(
                db,
                everything=everything,
                older_than_minutes=older_than,
                dry_run=not apply,
            )
        except QaPurgeRefused as exc:
            await db.rollback()
            print(f"REFUSED: {exc}")
            return 1
        if apply:
            await db.commit()
        else:
            await db.rollback()
    verb = "Deleted" if apply else "Would delete"
    print(f"{verb} ({report.mode}):")
    for name, count in report.counts.items():
        print(f"  {name}: {count}")
    if not apply:
        print("Nothing was changed. Add --apply to delete.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--all",
        action="store_true",
        help="also delete the fixture (accounts, catalog and QA towns)",
    )
    parser.add_argument(
        "--older-than-minutes",
        type=int,
        default=0,
        help="only data older than this (ignored with --all)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="actually delete (default: show)"
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            purge_qa(
                everything=args.all,
                older_than=args.older_than_minutes,
                apply=args.apply,
            )
        )
    )


if __name__ == "__main__":
    main()
