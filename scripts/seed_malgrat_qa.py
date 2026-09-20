"""Idempotent Malgrat QA accounts (real town, OTP 123456 in local/staging).

    python -m scripts.seed_malgrat_qa

Requires Malgrat (CP 08380) from ``python -m scripts.seed``.
Does not touch Demo KM0 (00000) nor Gmail/Jobmail residents.
"""

from __future__ import annotations

import asyncio

from app.db import SessionLocal
from app.services.malgrat_qa import ensure_malgrat_qa_accounts


async def seed_malgrat_qa() -> None:
    async with SessionLocal() as db:
        notes = await ensure_malgrat_qa_accounts(db)
        await db.commit()
        print("Malgrat QA accounts ensured (is_fake=false, CP 08380):")
        for line in notes:
            print(line)


if __name__ == "__main__":
    asyncio.run(seed_malgrat_qa())
