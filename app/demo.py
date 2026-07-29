"""Demo accounts: fixed OTP bypass + fake content scope (dev/staging only)."""

from __future__ import annotations

from app.config import get_settings
from app.roles import ROLE_ADMIN, ROLE_MERCHANT, ROLE_RESIDENT

DEMO_CODE = "123456"

DEMO_RESIDENT_EMAIL = "resident@km0lab.com"
DEMO_MERCHANT_EMAIL = "merchant@km0lab.com"
DEMO_ADMIN_EMAIL = "admin@km0lab.com"

DEMO_EMAILS: frozenset[str] = frozenset(
    {
        DEMO_RESIDENT_EMAIL,
        DEMO_MERCHANT_EMAIL,
        DEMO_ADMIN_EMAIL,
    }
)

DEMO_ROLES: dict[str, list[str]] = {
    DEMO_RESIDENT_EMAIL: [ROLE_RESIDENT],
    DEMO_MERCHANT_EMAIL: [ROLE_RESIDENT, ROLE_MERCHANT],
    DEMO_ADMIN_EMAIL: [ROLE_RESIDENT, ROLE_ADMIN],
}


def demo_enabled() -> bool:
    """Available in development and staging so demos work on Railway staging."""
    env = get_settings().environment.lower().strip()
    return env in {"development", "staging"}


def is_demo_email(email: str) -> bool:
    return email.lower().strip() in DEMO_EMAILS


def fake_match(user_is_fake: bool):
    """SQLAlchemy-friendly: rows visible to this user (real vs fake partition)."""
    return user_is_fake
