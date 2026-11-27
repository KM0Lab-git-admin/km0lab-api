"""Limiter compartido (slowapi). Se importa desde main y desde las rutas
para aplicar límites por IP."""

import ipaddress
import secrets
import uuid

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

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

# Máximo de intentos de verificación por código OTP antes de invalidarlo
# (anti fuerza bruta; complementa al rate limit por IP).
MAX_OTP_ATTEMPTS = 5

# Códigos OTP utilizables a la vez por correo. Pedir uno nuevo no anula los
# anteriores, y cada intento se compara con todos los vivos: este tope es
# lo que acota cuánto rinde un intento (y, con él, el límite por IP).
MAX_LIVE_OTP_CODES = 3
