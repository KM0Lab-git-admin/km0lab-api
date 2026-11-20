"""Upsert / delete binary town media: brand logo and header illustration."""

from datetime import datetime

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.base import NO_VALUE

from app.models import TownMedia

# logo: the entity's brand mark. art: the illustration that identifies the
# town in the residents app (home header, postal-code screen).
ALLOWED_KINDS = frozenset({"logo", "art"})
ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/jpg"}
)
MAX_BYTES = 5 * 1024 * 1024


def _loaded_timestamp(row: TownMedia, name: str) -> datetime | None:
    """Read a timestamp only if it is already in memory.

    An expired attribute would lazy-load, and under async MySQL that raises
    MissingGreenlet (see ``reward_media``).
    """
    value = inspect(row).attrs[name].loaded_value
    if value is NO_VALUE or not isinstance(value, datetime):
        return None
    return value


def media_version(row: TownMedia | None) -> str | None:
    """Cache-busting token: changes whenever the image is replaced."""
    if row is None:
        return None
    ts = _loaded_timestamp(row, "updated_at") or _loaded_timestamp(
        row, "created_at"
    )
    if ts is None:
        return str(row.byte_size or 0)
    return str(int(ts.timestamp()))


def media_public_path(
    town_id: str, kind: str = "logo", version: str | None = None
) -> str:
    path = f"/api/v1/towns/{town_id}/media/{kind}"
    if version:
        return f"{path}?v={version}"
    return path


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
