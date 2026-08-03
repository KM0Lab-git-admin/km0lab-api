"""Demo accounts: fixed OTP bypass + fake content scope (dev/staging only)."""

from __future__ import annotations

from app.config import get_settings
from app.roles import ROLE_ADMIN, ROLE_MERCHANT, ROLE_RESIDENT

DEMO_CODE = "123456"

DEMO_RESIDENT_EMAIL = "resident@km0lab.com"
DEMO_MERCHANT_EMAIL = "merchant@km0lab.com"
DEMO_ADMIN_EMAIL = "admin@km0lab.com"

# Fictional town for product demos / QA (separate from Malgrat real).
DEMO_POSTAL_CODE = "00000"
DEMO_TOWN_NAME = "Demo KM0"
DEMO_TOWN_SLUG = "demo-km0"
# Municipal content (agenda, news) falls back to this population name.
MALGRAT_CP = "08380"
MALGRAT_CONTENT_TOWN = "Malgrat de Mar"

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


def is_demo_postal_code(postal_code: str | None) -> bool:
    return (postal_code or "").strip() == DEMO_POSTAL_CODE


def desired_user_is_fake(email: str, postal_code: str | None) -> bool:
    """Partition a resident should live in.

    - Seeded demo emails always stay on the fake partition.
    - Everyone else: fake iff their postal code is Demo KM0 (00000).
    """
    if is_demo_email(email):
        return True
    return is_demo_postal_code(postal_code)


def sync_user_fake_partition(user, postal_code: str | None = None) -> bool:
    """Align ``user.is_fake`` with Demo KM0 membership.

    ``postal_code`` defaults to ``user.postal_code``. Returns True if the
    flag changed (caller should commit).
    """
    cp = user.postal_code if postal_code is None else postal_code
    desired = desired_user_is_fake(user.email, cp)
    if user.is_fake == desired:
        return False
    user.is_fake = desired
    return True


def resolve_public_demo(postal_code: str, requested: bool) -> bool:
    """Partition for public catalogs.

    - Demo CP (00000) always returns the fake/showcase partition.
    - Malgrat real (08380) never returns fake via the public API.
    - Other CPs keep the caller's ``demo`` flag (tests / future towns).
    """
    cp = postal_code.strip()
    if cp == DEMO_POSTAL_CODE:
        return True
    if cp == MALGRAT_CP:
        return False
    return requested


def fake_match(user_is_fake: bool):
    """SQLAlchemy-friendly: rows visible to this user (real vs fake partition)."""
    return user_is_fake
