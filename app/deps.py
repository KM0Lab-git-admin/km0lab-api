"""FastAPI dependencies: auth + role/scope guards."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=True)

ROLE_RESIDENT = "resident"
ROLE_MERCHANT = "merchant"
ROLE_ADMIN = "admin"


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user


def _require_roles(*roles: str):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
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
    if user.role == ROLE_ADMIN and user.town_id == town_id:
        return
    if user.role == ROLE_MERCHANT and user.town_id == town_id:
        return
    if user.role == ROLE_RESIDENT and (user.town_id is None or user.town_id == town_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Out of town scope"
    )


def assert_shop_scope(user: User, shop_id: str) -> None:
    if user.role == ROLE_ADMIN and user.town_id:
        return  # admin may manage any shop in their town (caller checks town)
    if user.role == ROLE_MERCHANT and user.shop_id == shop_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Out of shop scope"
    )
