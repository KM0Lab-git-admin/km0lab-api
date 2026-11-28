"""Load the header illustration of each town (media kind ``art``).

Usage (from repo root, with DB up):

    python -m scripts.seed_town_art                            # shows what would change
    python -m scripts.seed_town_art --apply                    # writes to the local DB
    python -m scripts.seed_town_art --target railway --apply   # writes to UAT

One image per town in scripts/seed_media/towns/<town-slug>.webp. A town with
no file keeps what it has; a file with no town is reported and skipped.
With --target railway it is a publication, so it only runs when the user
asks to publish.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from scripts._target import TARGETS, guard_write, point_at

ART_DIR = Path(__file__).resolve().parent / "seed_media" / "towns"
CONTENT_TYPES = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg"}


async def _run(apply: bool) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Town, TownMedia

    files = sorted(p for p in ART_DIR.iterdir() if p.suffix.lower() in CONTENT_TYPES)
    if not files:
        print(f"No images in {ART_DIR}")
        return
    changed = 0
    async with SessionLocal() as db:
        for path in files:
            slug = path.stem
            town = (
                await db.execute(select(Town).where(Town.slug == slug))
            ).scalar_one_or_none()
            if town is None:
                print(f"  {slug}: no town with that slug, skipped")
                continue
            data = path.read_bytes()
            row = (
                await db.execute(
                    select(TownMedia).where(
                        TownMedia.town_id == town.id, TownMedia.kind == "art"
                    )
                )
            ).scalar_one_or_none()
            if row is not None and row.data == data:
                print(f"  {town.name}: up to date")
                continue
            verb = "replace" if row is not None else "add"
            print(f"  {town.name}: {verb} ({len(data) // 1024} KB)")
            changed += 1
            if not apply:
                continue
            if row is None:
                db.add(
                    TownMedia(
                        town_id=town.id,
                        kind="art",
                        content_type=CONTENT_TYPES[path.suffix.lower()],
                        data=data,
                        byte_size=len(data),
                    )
                )
            else:
                row.content_type = CONTENT_TYPES[path.suffix.lower()]
                row.data = data
                row.byte_size = len(data)
        if apply:
            await db.commit()
    if changed and not apply:
        print(f"{changed} to write. Nothing written: run again with --apply.")
    else:
        print(f"Done. Written: {changed if apply else 0}")


async def main(apply: bool) -> None:
    from app.db import engine

    try:
        await _run(apply)
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
    asyncio.run(main(parsed.apply))
