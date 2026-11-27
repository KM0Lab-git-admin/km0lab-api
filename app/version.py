"""Versión del producto y compatibilidad con las apps publicadas.

La fuente única de la versión es el fichero ``VERSION`` de la raíz del
repositorio; solo lo cambia el comando de publicar (ver
``km0lab/docs/VERSIONES.md``).

La app nativa se publica menos a menudo que esta API. Cada petición de la
app trae su versión (``X-App-Version``); si está por debajo de la mínima
admitida (``MIN_APP_VERSION``), se le contesta 426 con
``app_update_required`` y la app enseña «actualiza» en vez de fallar.
"""

from __future__ import annotations

import re
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

APP_VERSION_HEADER = "x-app-version"
APP_PLATFORM_HEADER = "x-app-platform"
UPDATE_REQUIRED_CODE = "app_update_required"


def read_version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


API_VERSION = read_version()


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    """``1.2.0`` → ``(1, 2, 0)``. None si no son tres números."""
    match = _VERSION_RE.match((value or "").strip())
    if not match:
        return None
    return (int(match[1]), int(match[2]), int(match[3]))


def min_app_version() -> str:
    """Versión mínima admitida, o cadena vacía si no se exige ninguna."""
    value = get_settings().min_app_version.strip()
    return value if parse_version(value) else ""


def is_too_old(app_version: str | None) -> bool:
    """La app dice una versión válida y es anterior a la mínima.

    Una petición sin cabecera, o con una versión que no se entiende, no se
    rechaza: el backoffice, las pruebas y las apps anteriores a este
    mecanismo no la envían.
    """
    minimum = parse_version(min_app_version())
    current = parse_version(app_version)
    if minimum is None or current is None:
        return False
    return current < minimum


class AppVersionMiddleware(BaseHTTPMiddleware):
    """Contesta 426 a las apps por debajo de la versión mínima."""

    async def dispatch(self, request: Request, call_next):
        if request.method != "OPTIONS" and not request.url.path.endswith(
            "/health"
        ):
            sent = request.headers.get(APP_VERSION_HEADER)
            if is_too_old(sent):
                return JSONResponse(
                    status_code=426,
                    content={
                        "detail": {
                            "code": UPDATE_REQUIRED_CODE,
                            "min_version": min_app_version(),
                            "your_version": sent,
                        }
                    },
                )
        return await call_next(request)
