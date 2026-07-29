"""FastAPI dependencies: auth + role/scope guards."""

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.roles import (
    ROLE_ADMIN,
    ROLE_MERCHANT,
    ROLE_RESIDENT,
    primary_role,
)
from app.security import decode_access_token
from app.services.towns import load_user_with_town

bearer = HTTPBearer(auto_error=True)

__all__ = [
    "ROLE_RESIDENT",
    "ROLE_MERCHANT",
    "ROLE_ADMIN",
    "get_current_user",
    "get_active_role",
    "require_admin",
    "require_merchant",
    "require_backoffice",
    "require_resident",
    "assert_town_scope",
    "assert_shop_scope",
]


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    user = await load_user_with_town(db, payload["sub"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user


def get_active_role(
    user: User = Depends(get_current_user),
    x_active_role: str | None = Header(default=None, alias="X-Active-Role"),
) -> str:
    """Role context for the request: app sends resident, backoffice admin/merchant.

    If the header is omitted, preference is admin > merchant > resident.
    """
    roles = user.roles
    if x_active_role:
        if x_active_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Active role not granted to this user",
            )
        return x_active_role
    return primary_role(roles)


def _require_roles(*needed: str):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if not any(user.has_role(r) for r in needed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role"
            )
        return user

    return _dep


require_admin = _require_roles(ROLE_ADMIN)
require_merchant = _require_roles(ROLE_MERCHANT)
require_backoffice = _require_roles(ROLE_ADMIN, ROLE_MERCHANT)
require_resident = _require_roles(ROLE_RESIDENT)


def assert_town_scope(user: User, town_id: str) -> None:
    if user.has_role(ROLE_ADMIN) and user.town_id == town_id:
        return
    if user.has_role(ROLE_MERCHANT) and user.town_id == town_id:
        return
    if user.has_role(ROLE_RESIDENT) and (
        user.town_id is None or user.town_id == town_id
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Out of town scope"
    )


def assert_shop_scope(user: User, shop_id: str) -> None:
    if user.has_role(ROLE_ADMIN) and user.town_id:
        return
    if user.has_role(ROLE_MERCHANT) and user.shop_id == shop_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Out of shop scope"
    )
