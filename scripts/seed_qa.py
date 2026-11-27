"""Build or repair the QA territory (CP 99999, ``qa+…@km0lab.com``).

    python -m scripts.seed_qa

Idempotent. Writes to the database configured in the environment (the
local one, unless you are running inside the UAT service). Refuses to run
in production. See ``app/qa.py``.
"""

from __future__ import annotations

import asyncio

from app.db import SessionLocal
from app.demo import demo_enabled
from app.qa import QA_FIXTURE_EMAILS, QA_POSTAL_CODE
from app.services.qa_territory import ensure_qa_territory


async def seed_qa() -> None:
    if not demo_enabled():
        raise SystemExit("QA territory is disabled in production.")
    async with SessionLocal() as db:
        summary = await ensure_qa_territory(db)
        await db.commit()
    print(f"QA territory ready (CP {QA_POSTAL_CODE}, is_fake=true):")
    for name, count in summary.items():
        print(f"  {name}: {count}")
    print("Fixture accounts (fixed OTP, dev/staging only):")
    for email in sorted(QA_FIXTURE_EMAILS):
        print(f"  {email}")


if __name__ == "__main__":
    asyncio.run(seed_qa())
