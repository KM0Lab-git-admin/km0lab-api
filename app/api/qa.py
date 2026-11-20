"""QA territory maintenance for automated tests (dev/staging only).

``POST /qa/prepare`` lets the test robot leave the QA territory ready
before a run: it removes what earlier runs created and repairs the fixture.

Closed by default. It answers 404 unless the environment is development or
staging **and** ``QA_TOKEN`` is configured, and it requires that token in
the ``X-QA-Token`` header. It can only touch QA data: see
``app/services/qa_purge.py`` for the checks.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.demo import demo_enabled
from app.qa import QA_POSTAL_CODE
from app.services.qa_purge import QaPurgeRefused, purge_qa_territory
from app.services.qa_territory import ensure_qa_territory

router = APIRouter(prefix="/qa", tags=["qa"])


def require_qa_token(
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
) -> None:
    expected = get_settings().qa_token
    if not demo_enabled() or not expected:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    if not x_qa_token or not secrets.compare_digest(x_qa_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.post("/prepare", dependencies=[Depends(require_qa_token)])
async def prepare_qa_territory(
    older_than_minutes: int = Query(
        default=120,
        ge=0,
        le=60 * 24 * 30,
        description=(
            "Remove test-run data older than this. Keeps runs in progress "
            "(another branch, another workflow) untouched."
        ),
    ),
    dry_run: bool = Query(
        default=False,
        description="Report what would be removed without changing anything.",
    ),
    db: AsyncSession = Depends(get_db),
):
    try:
        report = await purge_qa_territory(
            db,
            everything=False,
            older_than_minutes=older_than_minutes,
            dry_run=dry_run,
        )
    except QaPurgeRefused as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if dry_run:
        await db.rollback()
        return {"purge": report.as_dict(), "fixture": None}

    fixture = await ensure_qa_territory(db)
    await db.commit()
    return {
        "purge": report.as_dict(),
        "fixture": {"postal_code": QA_POSTAL_CODE, **fixture},
    }
