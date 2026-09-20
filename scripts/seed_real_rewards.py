"""Mirror the demo catalog onto real towns (Malgrat 08380, Blanes, Lloret).

Usage (from repo root):

    python -m scripts.seed_real_rewards
    python -m scripts.seed_real_rewards --railway

``--railway`` uses RAILWAY_DB_URL from .env (or the environment). It does
not drop tables or copy the local database.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _read_railway_url() -> str:
    env = (os.environ.get("RAILWAY_DB_URL") or "").strip()
    if env:
        return env
    env_path = _ROOT / ".env"
    if not env_path.is_file():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("RAILWAY_DB_URL="):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _apply_railway_env() -> None:
    url = _read_railway_url()
    if not url:
        raise SystemExit("RAILWAY_DB_URL no está definido en el entorno ni en .env")
    parsed = urlparse(url)
    if parsed.scheme.split("+", 1)[0] != "mysql" or not parsed.hostname:
        raise SystemExit("RAILWAY_DB_URL no es una URL MySQL válida")
    os.environ["DB_HOST"] = parsed.hostname
    os.environ["DB_PORT"] = str(parsed.port or 3306)
    os.environ["DB_USER"] = unquote(parsed.username or "")
    os.environ["DB_PASSWORD"] = unquote(parsed.password or "")
    os.environ["DB_NAME"] = parsed.path.lstrip("/")
    print(
        f"Destino: {parsed.hostname}:{parsed.port or 3306}/{parsed.path.lstrip('/')}"
    )


async def _run() -> None:
    from sqlalchemy import select

    from app.catalog.rewards import seed_real_rewards
    from app.db import SessionLocal
    from app.models import Shop, Town
    from app.services.towns import ensure_demo_town

    async with SessionLocal() as db:
        demo = await ensure_demo_town(db)
        towns = (await db.execute(select(Town))).scalars().all()
        real_towns = [t for t in towns if t.id != demo.id and t.slug != demo.slug]
        if not real_towns:
            print("No hay pueblos reales. Ejecuta primero: python -m scripts.seed")
            return
        for town in real_towns:
            shop_id = (
                await db.execute(
                    select(Shop.id).where(
                        Shop.town_id == town.id,
                        Shop.is_fake.is_(False),
                    )
                )
            ).scalars().first()
            count = await seed_real_rewards(
                db, town_id=town.id, shop_id=shop_id
            )
            print(f"  {town.name}: {count} premios reales")
        await db.commit()
        print("Listo.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copia el catálogo demo a los pueblos reales"
    )
    parser.add_argument(
        "--railway",
        action="store_true",
        help="Usar RAILWAY_DB_URL en lugar de la BD local",
    )
    args = parser.parse_args()
    if args.railway:
        _apply_railway_env()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
