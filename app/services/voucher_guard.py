"""Rules for using a voucher: whose town, how many misses, when it expires."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Redemption, Shop, Town, User, VoucherAttempt
from app.ratelimit import too_many_response

# Wrong codes a shop may try in an hour before it has to wait.
MISS_LIMIT = 10
WINDOW = timedelta(hours=1)


def add_months(when: datetime, months: int) -> datetime:
    """The same clock time, ``months`` later. The day clamps to the month."""
    index = when.month - 1 + months
    year = when.year + index // 12
    month = index % 12 + 1
    day = min(when.day, monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def expiry_for(db: AsyncSession, town_id: str) -> datetime | None:
    """When a voucher created now expires, or None if the town has no term."""
    months = await db.scalar(select(Town.expiry_months).where(Town.id == town_id))
    if not months or months < 1:
        return None
    return add_months(datetime.now(timezone.utc), months)


def is_expired(redemption: Redemption, now: datetime | None = None) -> bool:
    if redemption.expires_at is None:
        return False
    moment = now or datetime.now(timezone.utc)
    return _aware(redemption.expires_at) <= moment


async def _misses_since(db: AsyncSession, shop_id: str, since: datetime) -> list[datetime]:
    rows = (
        await db.execute(
            select(VoucherAttempt.attempted_at).where(
                VoucherAttempt.shop_id == shop_id,
                VoucherAttempt.success.is_(False),
                VoucherAttempt.attempted_at >= since,
            )
        )
    ).scalars().all()
    return [_aware(row) for row in rows]


async def miss_refusal(db: AsyncSession, shop_id: str):
    """429 once the shop has used up its misses, else None."""
    now = datetime.now(timezone.utc)
    misses = await _misses_since(db, shop_id, now - WINDOW)
    if len(misses) < MISS_LIMIT:
        return None
    oldest = min(misses)
    seconds = max(1, int((oldest + WINDOW - now).total_seconds()))
    return too_many_response("too_many_attempts", seconds)


async def note_attempt(db: AsyncSession, shop_id: str, *, success: bool) -> None:
    """Remember the try and commit it. A miss has to survive the 404."""
    db.add(
        VoucherAttempt(
            shop_id=shop_id,
            success=success,
            attempted_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


async def is_self_validated(
    db: AsyncSession, redemption: Redemption, shop: Shop, actor: User
) -> bool:
    """The voucher is the validator's, or it belongs to the shop's owner."""
    if redemption.user_id == actor.id:
        return True
    owner_id = await db.scalar(select(User.id).where(User.shop_id == shop.id))
    return owner_id is not None and owner_id == redemption.user_id


async def self_validated_pending(db: AsyncSession, shop_ids: set[str]) -> dict[str, int]:
    """How many unpaid used vouchers of each shop were self-validated."""
    if not shop_ids:
        return {}
    rows = (
        await db.execute(
            select(Redemption.shop_id, func.count())
            .where(
                Redemption.shop_id.in_(shop_ids),
                Redemption.self_validated.is_(True),
                Redemption.status == "used",
                Redemption.payment_id.is_(None),
            )
            .group_by(Redemption.shop_id)
        )
    ).all()
    return {shop_id: int(count) for shop_id, count in rows}
