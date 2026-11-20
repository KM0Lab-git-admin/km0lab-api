"""Limiter compartido (slowapi). Se importa desde main y desde las rutas
para aplicar límites por IP."""

import secrets
import uuid

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import get_settings

QA_TOKEN_HEADER = "x-qa-token"


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


def rate_limit_key(request: Request) -> str:
    """Clave del límite: la IP del cliente.

    El robot de pruebas no comparte cubo con nadie: cada petición suya lleva
    una clave única, así que ni se frena a sí mismo (una ejecución da de
    alta una docena de vecinos) ni gasta el cupo de los vecinos reales.
    """
    if is_qa_robot(request):
        return f"qa-robot:{uuid.uuid4().hex}"
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key)

# Máximo de intentos de verificación por código OTP antes de invalidarlo
# (anti fuerza bruta; complementa al rate limit por IP).
MAX_OTP_ATTEMPTS = 5
