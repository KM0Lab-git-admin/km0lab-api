"""Choose the database a script works on: the local one or Railway/UAT.

Call ``point_at`` before anything imports ``app.config`` or ``app.db``:
those read the connection from the environment the first time they load.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

TARGETS = ("local", "railway")


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
    url = os.environ.get("RAILWAY_DB_URL")
    if not url:
        raise SystemExit(
            "RAILWAY_DB_URL is not set (Railway -> MySQL -> Variables -> public URL)."
        )
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.path.strip("/"):
        raise SystemExit("RAILWAY_DB_URL is not a valid mysql:// URL.")
    os.environ["DB_HOST"] = parsed.hostname
    os.environ["DB_PORT"] = str(parsed.port or 3306)
    os.environ["DB_USER"] = unquote(parsed.username or "")
    os.environ["DB_PASSWORD"] = unquote(parsed.password or "")
    os.environ["DB_NAME"] = parsed.path.strip("/")
    return f"RAILWAY / UAT (database {parsed.path.strip('/')})"
