"""Limiter compartido (slowapi). Se importa desde main y desde las rutas
para aplicar límites por IP."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Máximo de intentos de verificación por código OTP antes de invalidarlo
# (anti fuerza bruta; complementa al rate limit por IP).
MAX_OTP_ATTEMPTS = 5
