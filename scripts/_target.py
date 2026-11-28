"""Choose the database a script works on.

``local`` is the machine. ``railway`` is UAT and reads ``RAILWAY_DB_URL``.
``production`` reads ``PROD_DB_URL`` and nothing else: putting the
production address in the UAT variable would make every script write
there by mistake.

Call ``point_at`` before anything imports ``app.config`` or ``app.db``:
those read the connection from the environment the first time they load.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import unquote, urlparse

TARGETS = ("local", "railway", "production")


def point_at(target: str) -> str:
    """Aim ``app.db`` at ``target`` and return a label safe to print."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    if target == "local":
        host = os.environ.get("DB_HOST", "localhost")
        return f"local ({host})"
    if target == "production":
        url = os.environ.get("PROD_DB_URL")
        if not url:
            raise SystemExit(
                "PROD_DB_URL is not set. Production is never read from RAILWAY_DB_URL."
            )
        return _use(url, "PRODUCCIÓN")
    url = os.environ.get("RAILWAY_DB_URL")
    if not url:
        raise SystemExit(
            "RAILWAY_DB_URL is not set (Railway -> MySQL -> Variables -> public URL)."
        )
    return _use(url, "RAILWAY / UAT")


def _use(url: str, label: str) -> str:
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.path.strip("/"):
        raise SystemExit(f"{label} URL is not a valid mysql:// URL.")
    os.environ["DB_HOST"] = parsed.hostname
    os.environ["DB_PORT"] = str(parsed.port or 3306)
    os.environ["DB_USER"] = unquote(parsed.username or "")
    os.environ["DB_PASSWORD"] = unquote(parsed.password or "")
    name = parsed.path.strip("/")
    os.environ["DB_NAME"] = name
    return f"{label} (database {name})"


def guard_write(target: str, *, apply: bool, confirm: str | None) -> None:
    """A write to production names the database, or it does not happen."""
    if target != "production" or not apply:
        return
    name = os.environ.get("DB_NAME", "")
    typed = confirm
    if not typed:
        if not sys.stdin.isatty():
            raise SystemExit(
                "Para escribir en PRODUCCIÓN hace falta --confirm y el nombre de la base."
            )
        typed = input(
            "Escribe el nombre de la base para confirmar la escritura en PRODUCCIÓN: "
        )
    if typed.strip() != name:
        raise SystemExit("El nombre no coincide. No se ha escrito nada en PRODUCCIÓN.")
    print("ATENCIÓN: ESTO ESCRIBE EN PRODUCCIÓN")
