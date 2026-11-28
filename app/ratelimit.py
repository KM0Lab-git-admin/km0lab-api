"""Limiter compartido (slowapi). Se importa desde main y desde las rutas
para aplicar límites por IP."""

import ipaddress
import math
import secrets
import time
import uuid

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings

QA_TOKEN_HEADER = "x-qa-token"
REAL_IP_HEADER = "x-real-ip"


def is_qa_robot(request: Request) -> bool:
    """Petición del robot de pruebas: trae la clave QA_TOKEN válida.

    Solo fuera de producción y solo si la clave está configurada.
    """
    settings = get_settings()
    env = settings.environment.lower().strip()
    expected = settings.qa_token
    if env not in {"development", "staging"} or not expected:
        return False
    token = request.headers.get(QA_TOKEN_HEADER) or ""
    return bool(token) and secrets.compare_digest(token, expected)


def client_ip(request: Request) -> str:
    """La IP de quien llama, vista a través de la entrada de Railway.

    La conexión que llega a la API es la del proxy de Railway, la misma para
    todo el mundo: con ella todos los vecinos compartían un solo cupo de
    códigos. La entrada pública de Railway escribe la IP del cliente en
    ``X-Real-IP`` y pisa la que el cliente intente mandar (comprobado el
    27-11-2026; Railway lo describe como comportamiento actual, no como
    garantía). No se usa ``X-Forwarded-For``: uvicorn tomaría la primera
    dirección de la lista y la documentación no dice qué hace Railway con
    ella.

    Sin la cabecera (en local, o si Railway dejara de mandarla) vale la
    dirección de la conexión, que es lo que había. Lo que entrara por la red
    interna de Railway no pasa por esa entrada y podría traer cualquier
    cabecera: hoy nada llama a la API por ahí.
    """
    claimed = (request.headers.get(REAL_IP_HEADER) or "").strip()
    if claimed:
        try:
            return str(ipaddress.ip_address(claimed))
        except ValueError:
            pass
    return get_remote_address(request)


def rate_limit_key(request: Request) -> str:
    """Clave del límite: la IP del cliente.

    El robot de pruebas no comparte cubo con nadie: cada petición suya lleva
    una clave única, así que ni se frena a sí mismo (una ejecución da de
    alta una docena de vecinos) ni gasta el cupo de los vecinos reales.
    """
    if is_qa_robot(request):
        return f"qa-robot:{uuid.uuid4().hex}"
    return client_ip(request)


limiter = Limiter(key_func=rate_limit_key)

RATE_LIMITED = "rate_limited"


def wait_minutes(seconds: int) -> int:
    """Seconds left, as the whole minutes a person is told to wait."""
    return max(1, math.ceil(seconds / 60))


def too_many_response(code: str, retry_after_seconds: int) -> JSONResponse:
    """429 that says when to try again, for the app and in the headers.

    ``detail`` is ``{"code", "message", "retry_after_seconds"}`` like the
    other refusals of the access; ``Retry-After`` carries the same wait.
    """
    seconds = max(1, int(retry_after_seconds))
    minutes = wait_minutes(seconds)
    return JSONResponse(
        status_code=429,
        content={
            "detail": {
                "code": code,
                "message": (
                    "Massa intents. Torna-ho a provar d'aquí a "
                    f"{minutes} minut{'s' if minutes != 1 else ''}."
                ),
                "retry_after_seconds": seconds,
            }
        },
        headers={"Retry-After": str(seconds)},
    )


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """The limit by connection was hit: say when the window opens again."""
    seconds = 3600
    try:
        item, args = request.state.view_rate_limit
        seconds = item.get_expiry()
        reset_at, _ = limiter.limiter.get_window_stats(item, *args)
        seconds = int(reset_at - time.time())
    except Exception:
        # Without the window's own data, the whole window is the honest answer.
        pass
    return too_many_response(RATE_LIMITED, seconds)

# Máximo de intentos de verificación por código OTP antes de invalidarlo
# (anti fuerza bruta; complementa al rate limit por IP).
MAX_OTP_ATTEMPTS = 5

# Códigos OTP utilizables a la vez por correo. Pedir uno nuevo no anula los
# anteriores, y cada intento se compara con todos los vivos: este tope es
# lo que acota cuánto rinde un intento (y, con él, el límite por IP).
MAX_LIVE_OTP_CODES = 3
