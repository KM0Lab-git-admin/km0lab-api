"""JWT and OTP hashing."""

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Iterable

from jose import JWTError, jwt

from app.config import get_settings
from app.roles import normalize_roles, primary_role

settings = get_settings()


def create_access_token(
    user_id: str,
    *,
    roles: Iterable[str] | None = None,
    role: str | None = None,
    town_id: str | None = None,
    shop_id: str | None = None,
) -> str:
    """Issue JWT. Prefer `roles`; legacy single `role=` still accepted."""
    if roles is not None:
        role_list = normalize_roles(roles)
    elif role is not None:
        role_list = normalize_roles([role])
    else:
        role_list = normalize_roles(["resident"])

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "roles": role_list,
        # Legacy single-role claim for older clients.
        "role": primary_role(role_list),
        "town_id": town_id,
        "shop_id": shop_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        if not payload.get("sub"):
            return None
        return payload
    except JWTError:
        return None


def hash_otp(code: str) -> str:
    """Deterministic OTP hash salted with the JWT secret."""
    return hmac.new(
        settings.jwt_secret.encode(), code.encode(), hashlib.sha256
    ).hexdigest()


def verify_otp(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(code), code_hash)
