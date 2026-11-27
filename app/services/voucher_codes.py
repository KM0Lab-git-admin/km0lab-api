"""Generate unique 5-digit voucher codes for merchant validation."""

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Redemption


async def allocate_voucher_code(db: AsyncSession) -> str:
    """Return a unique 5-digit code in 10000–99999 (never leading zero)."""
    for _ in range(50):
        code = f"{random.randint(10000, 99999)}"
        exists = (
            await db.execute(select(Redemption.id).where(Redemption.code == code))
        ).scalar_one_or_none()
        if exists is None:
            return code
    raise RuntimeError("Could not allocate a unique voucher code")
