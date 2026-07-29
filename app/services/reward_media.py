"""Upsert / delete binary reward catalog image."""

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RewardMedia

ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/jpg"}
)
MAX_BYTES = 5 * 1024 * 1024


def media_public_path(reward_id: str) -> str:
    return f"/api/v1/rewards/{reward_id}/media"


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
        await db.flush()
        return existing

    row = RewardMedia(
        reward_id=reward_id,
        content_type=content_type,
        data=data,
        byte_size=len(data),
    )
    db.add(row)
    await db.flush()
    return row


async def delete_reward_media(db: AsyncSession, *, reward_id: str) -> bool:
    row = await get_reward_media(db, reward_id)
    if not row:
        return False
    await db.delete(row)
    await db.flush()
    return True
