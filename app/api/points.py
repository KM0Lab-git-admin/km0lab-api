"""Points claim + resident history endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_resident
from app.models import User
from app.schemas.points import ClaimPointsOut, PointsHistoryOut
from app.services.action_grants import grant_birthday_points
from app.services.points_history import build_points_history

router = APIRouter(prefix="/points", tags=["points"])


@router.get("/me/history", response_model=PointsHistoryOut)
async def my_points_history(
    filter: str = Query(
        default="all",
        pattern="^(all|earned|spent)$",
        description="all | earned (points>0) | spent (points<0)",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_resident),
    db: AsyncSession = Depends(get_db),
):
    """Ledger history for the authenticated resident (app 'Historial de punts')."""
    return await build_points_history(
        db, user=user, filter=filter, limit=limit
    )


@router.post("/claim-birthday", response_model=ClaimPointsOut)
async def claim_birthday(
    user: User = Depends(require_resident),
    db: AsyncSession = Depends(get_db),
):
    """On app open: if today is the user's birthday, grant catalogued points once/year."""
    result = await grant_birthday_points(db, user=user)
    if result.points > 0:
        await db.commit()
        await db.refresh(user)
    return ClaimPointsOut(
        awarded=result.points > 0,
        points=result.points,
        balance=user.points,
        message=result.message,
    )
