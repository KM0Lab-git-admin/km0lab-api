"""Town config endpoints (admin of that town) + brand media."""

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import assert_town_scope, require_admin
from app.models import Town, User
from app.schemas import TownMediaOut, TownOut, TownUpdate
from app.services.town_media import (
    delete_town_media,
    get_town_media,
    media_public_path,
    upsert_town_media,
)
from app.utils.slug import slugify

router = APIRouter(prefix="/towns", tags=["towns"])


async def _load_town(db: AsyncSession, town_id: str) -> Town | None:
    return (
        await db.execute(
            select(Town)
            .options(selectinload(Town.postal_codes), selectinload(Town.media))
            .where(Town.id == town_id)
        )
    ).scalars().first()


def _to_out(town: Town) -> TownOut:
    data = TownOut.model_validate(town)
    has_logo = any(m.kind == "logo" for m in (town.media or []))
    data.has_logo = has_logo
    if has_logo:
        data.logo_url = media_public_path(town.id, "logo")
    return data


@router.get("/me", response_model=TownOut)
async def get_my_town(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No town linked")
    town = await _load_town(db, user.town_id)
    if not town:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    return _to_out(town)


@router.get("/{town_id}", response_model=TownOut)
async def get_town(
    town_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    assert_town_scope(user, town_id)
    town = await _load_town(db, town_id)
    if not town:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    return _to_out(town)


@router.patch("/{town_id}", response_model=TownOut)
async def update_town(
    town_id: str,
    payload: TownUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    assert_town_scope(user, town_id)
    town = await _load_town(db, town_id)
    if not town:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    data = payload.model_dump(exclude_unset=True)
    # Logo is uploaded via PUT /towns/{id}/media/logo — ignore data URLs.
    logo = data.pop("logo_url", None)
    if logo is not None and not str(logo).startswith("data:"):
        if str(logo).startswith("/api/v1/towns/"):
            pass  # keep existing blob; path is derived
        else:
            town.logo_url = logo
    if "slug" in data:
        wanted = slugify(data.pop("slug") or "")
        taken = (
            await db.execute(
                select(Town.id).where(Town.slug == wanted, Town.id != town.id)
            )
        ).scalar_one_or_none()
        if taken:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Slug already in use"
            )
        town.slug = wanted
    for field, value in data.items():
        setattr(town, field, value)
    await db.commit()
    town = await _load_town(db, town_id)
    return _to_out(town)  # type: ignore[arg-type]


@router.put("/{town_id}/media/{kind}", response_model=TownMediaOut)
async def upload_town_media(
    town_id: str,
    kind: str,
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    assert_town_scope(user, town_id)
    town = await _load_town(db, town_id)
    if not town:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    row = await upsert_town_media(db, town_id=town.id, kind=kind, upload=file)
    town.logo_url = media_public_path(town.id, kind)
    await db.commit()
    return TownMediaOut(
        town_id=town.id,
        kind=row.kind,
        content_type=row.content_type,
        byte_size=row.byte_size,
        url=media_public_path(town.id, kind),
    )


@router.delete("/{town_id}/media/{kind}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_town_media(
    town_id: str,
    kind: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    assert_town_scope(user, town_id)
    town = await _load_town(db, town_id)
    if not town:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    deleted = await delete_town_media(db, town_id=town.id, kind=kind)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Media not found")
    town.logo_url = None
    await db.commit()


@router.get("/{town_id}/media/{kind}")
async def download_town_media(
    town_id: str,
    kind: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve town brand image (public so <img src> works without auth)."""
    row = await get_town_media(db, town_id, kind)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Media not found")
    return Response(
        content=row.data,
        media_type=row.content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Length": str(row.byte_size),
        },
    )
