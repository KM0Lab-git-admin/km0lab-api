"""Points ledger helpers. Every points mutation goes through here."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.models import PointsTransaction, User


async def lock_user_points(db: AsyncSession, user: User) -> None:
    """Take the user's row lock and reload the balance. Call it first.

    Two requests from the same resident at once (a double tap, a QR read
    twice by the camera) used to pass the same checks with the same stale
    balance: the scan was recorded twice, or MySQL aborted one of them with
    a deadlock. Holding the row lock from the start makes them run one
    after the other, and each sees what the previous one committed.

    Checks that follow must also use locking reads (``with_for_update``):
    a plain SELECT would still read this transaction's older snapshot.
    """
    fresh = await db.scalar(
        select(User.points).where(User.id == user.id).with_for_update()
    )
    if fresh is not None:
        set_committed_value(user, "points", fresh)


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
        is_fake=user.is_fake,
    )
    db.add(tx)
    user.points = user.points + points
    await db.flush()
    return tx
