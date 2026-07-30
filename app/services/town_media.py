"""Upsert / delete binary town brand media (logo)."""

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TownMedia

ALLOWED_KINDS = frozenset({"logo"})
ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/jpg"}
)
MAX_BYTES = 5 * 1024 * 1024


def media_public_path(town_id: str, kind: str = "logo") -> str:
    return f"/api/v1/towns/{town_id}/media/{kind}"


async def get_town_media(
    db: AsyncSession, town_id: str, kind: str = "logo"
) -> TownMedia | None:
    stmt = select(TownMedia).where(
        TownMedia.town_id == town_id, TownMedia.kind == kind
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_town_media(
    db: AsyncSession,
    *,
    town_id: str,
    kind: str,
    upload: UploadFile,
) -> TownMedia:
    if kind not in ALLOWED_KINDS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"kind must be one of: {', '.join(sorted(ALLOWED_KINDS))}",
        )

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

    existing = await get_town_media(db, town_id, kind)
    if existing:
        existing.content_type = content_type
        existing.data = data
        existing.byte_size = len(data)
        await db.flush()
        return existing

    row = TownMedia(
        town_id=town_id,
        kind=kind,
        content_type=content_type,
        data=data,
        byte_size=len(data),
    )
    db.add(row)
    await db.flush()
    return row


async def delete_town_media(
    db: AsyncSession, *, town_id: str, kind: str = "logo"
) -> bool:
    if kind not in ALLOWED_KINDS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"kind must be one of: {', '.join(sorted(ALLOWED_KINDS))}",
        )
    row = await get_town_media(db, town_id, kind)
    if not row:
        return False
    await db.delete(row)
    await db.flush()
    return True
