"""Role helpers: multi-role users with admin XOR merchant."""

from __future__ import annotations

from typing import Iterable

ROLE_RESIDENT = "resident"
ROLE_MERCHANT = "merchant"
ROLE_ADMIN = "admin"

ALL_ROLES = (ROLE_RESIDENT, ROLE_MERCHANT, ROLE_ADMIN)
VALID_ROLES = frozenset(ALL_ROLES)


class IncompatibleRolesError(ValueError):
    """Raised when admin and merchant are combined."""


def normalize_roles(roles: Iterable[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for role in ALL_ROLES:
        if role in roles and role not in seen:
            ordered.append(role)
            seen.add(role)
    unknown = set(roles) - VALID_ROLES
    if unknown:
        raise ValueError(f"Unknown roles: {sorted(unknown)}")
    if not ordered:
        raise ValueError("At least one role is required")
    if ROLE_ADMIN in ordered and ROLE_MERCHANT in ordered:
        raise IncompatibleRolesError(
            "A user cannot be admin and merchant at the same time"
        )
    return ordered


def flags_from_roles(roles: Iterable[str]) -> dict[str, bool]:
    normalized = normalize_roles(roles)
    return {
        "is_resident": ROLE_RESIDENT in normalized,
        "is_merchant": ROLE_MERCHANT in normalized,
        "is_admin": ROLE_ADMIN in normalized,
    }


def roles_from_flags(
    *, is_resident: bool, is_merchant: bool, is_admin: bool
) -> list[str]:
    roles: list[str] = []
    if is_resident:
        roles.append(ROLE_RESIDENT)
    if is_merchant:
        roles.append(ROLE_MERCHANT)
    if is_admin:
        roles.append(ROLE_ADMIN)
    return normalize_roles(roles)


def primary_role(roles: Iterable[str]) -> str:
    """Preferred role for legacy single-role contexts: admin > merchant > resident."""
    normalized = normalize_roles(roles)
    for preferred in (ROLE_ADMIN, ROLE_MERCHANT, ROLE_RESIDENT):
        if preferred in normalized:
            return preferred
    return ROLE_RESIDENT
