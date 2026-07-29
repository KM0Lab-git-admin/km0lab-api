"""Upsert / delete binary shop media (logo, hero)."""

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ShopMedia

ALLOWED_KINDS = frozenset({"logo", "hero"})
ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/jpg"}
)
# Back-office: max. 5 MB
MAX_BYTES = 5 * 1024 * 1024


def media_public_path(shop_id: str, kind: str) -> str:
    return f"/api/v1/shops/{shop_id}/media/{kind}"


async def get_shop_media(
    db: AsyncSession, shop_id: str, kind: str
) -> ShopMedia | None:
    stmt = select(ShopMedia).where(
        ShopMedia.shop_id == shop_id, ShopMedia.kind == kind
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def media_kinds_present(db: AsyncSession, shop_id: str) -> set[str]:
    stmt = select(ShopMedia.kind).where(ShopMedia.shop_id == shop_id)
    return set((await db.execute(stmt)).scalars().all())


async def upsert_shop_media(
    db: AsyncSession,
    *,
    shop_id: str,
    kind: str,
    upload: UploadFile,
) -> ShopMedia:
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

    existing = await get_shop_media(db, shop_id, kind)
    if existing:
        existing.content_type = content_type
        existing.data = data
        existing.byte_size = len(data)
        await db.flush()
        return existing

    row = ShopMedia(
        shop_id=shop_id,
        kind=kind,
        content_type=content_type,
        data=data,
        byte_size=len(data),
    )
    db.add(row)
    await db.flush()
    return row


async def delete_shop_media(
    db: AsyncSession, *, shop_id: str, kind: str
) -> bool:
    if kind not in ALLOWED_KINDS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"kind must be one of: {', '.join(sorted(ALLOWED_KINDS))}",
        )
    row = await get_shop_media(db, shop_id, kind)
    if not row:
        return False
    await db.delete(row)
    await db.flush()
    return True
