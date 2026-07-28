"""Points ledger helpers. Every points mutation goes through here."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PointsTransaction, User


async def apply_points(
    db: AsyncSession,
    *,
    user: User,
    points: int,
    type: str,
    town_id: str | None = None,
    ref_id: str | None = None,
    description: str | None = None,
) -> PointsTransaction:
    """Credit (positive) or debit (negative) points and update cached balance."""
    if points == 0:
        raise ValueError("points must be non-zero")
    if points < 0 and user.points + points < 0:
        raise ValueError("insufficient points")

    tx = PointsTransaction(
        user_id=user.id,
        town_id=town_id or user.town_id,
        type=type,
        points=points,
        ref_id=ref_id,
        description=description,
    )
    db.add(tx)
    user.points = user.points + points
    await db.flush()
    return tx
