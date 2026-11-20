"""Upsert / delete binary reward catalog image."""

from datetime import datetime

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.base import NO_VALUE

from app.models import RewardMedia

ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/jpg"}
)
MAX_BYTES = 5 * 1024 * 1024


def _loaded_timestamp(row: RewardMedia, name: str) -> datetime | None:
    """Read a timestamp only if it is already in memory.

    An expired attribute would lazy-load. Under async MySQL that raises
    MissingGreenlet and the upload dies as a 500 without CORS headers.
    """
    value = inspect(row).attrs[name].loaded_value
    if value is NO_VALUE or value is None:
        return None
    if isinstance(value, datetime):
        return value
    return None


def media_version(row: RewardMedia | None) -> str | None:
    if row is None:
        return None
    ts = _loaded_timestamp(row, "updated_at") or _loaded_timestamp(
        row, "created_at"
    )
    if ts is None:
        return str(row.byte_size or 0)
    return str(int(ts.timestamp()))


def media_public_path(reward_id: str, version: str | None = None) -> str:
    path = f"/api/v1/rewards/{reward_id}/media"
    if version:
        return f"{path}?v={version}"
    return path


async def get_reward_media(
    db: AsyncSession, reward_id: str
) -> RewardMedia | None:
    stmt = select(RewardMedia).where(RewardMedia.reward_id == reward_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_reward_media(
    db: AsyncSession,
    *,
    reward_id: str,
    upload: UploadFile,
) -> RewardMedia:
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type == "image/jpg":
        content_type = "image/jpeg"
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Only JPEG, PNG or WebP images are allowed",
        )

    data = await upload.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"File too large (max {MAX_BYTES // (1024 * 1024)} MB)",
        )

    existing = await get_reward_media(db, reward_id)
    if existing:
        existing.content_type = content_type
        existing.data = data
        existing.byte_size = len(data)
        existing.updated_at = datetime.utcnow()
        await db.flush()
        await _load_version_timestamps(db, existing)
        return existing

    now = datetime.utcnow()
    row = RewardMedia(
        reward_id=reward_id,
        content_type=content_type,
        data=data,
        byte_size=len(data),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    await _load_version_timestamps(db, row)
    return row


async def _load_version_timestamps(db: AsyncSession, row: RewardMedia) -> None:
    """MySQL does not echo server defaults.

    ``media_version`` reads ``updated_at`` right after flush. If that
    attribute is expired, the sync lazy-load raises MissingGreenlet, the
    request becomes a bare 500, and the browser reports it as CORS.
    """
    await db.refresh(row, attribute_names=["created_at", "updated_at"])


async def delete_reward_media(db: AsyncSession, *, reward_id: str) -> bool:
    row = await get_reward_media(db, reward_id)
    if not row:
        return False
    await db.delete(row)
    await db.flush()
    return True
