"""Town config (admin of that town), town media and the public town cards."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, lazyload, selectinload

from app.db import get_db
from app.demo import DEMO_TOWN_SLUG
from app.deps import assert_town_scope, require_admin
from app.models import Town, TownMedia, User
from app.qa import QA_SLUG_PREFIX
from app.schemas import TownMediaOut, TownOut, TownPublicOut, TownUpdate
from app.services.media_http import media_bytes_response, media_not_found_response
from app.services.town_media import (
    delete_town_media,
    get_town_media,
    media_public_path,
    media_version,
    upsert_town_media,
)
from app.services.towns import get_postal_code
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


def _art_url(town_id: str, media: list[TownMedia]) -> str | None:
    row = next((m for m in media if m.kind == "art"), None)
    if row is None:
        return None
    return media_public_path(town_id, "art", media_version(row))


def _to_out(town: Town) -> TownOut:
    data = TownOut.model_validate(town)
    media = list(town.media or [])
    has_logo = any(m.kind == "logo" for m in media)
    data.has_logo = has_logo
    if has_logo:
        data.logo_url = media_public_path(town.id, "logo")
    data.art_url = _art_url(town.id, media)
    return data


def _to_public(town: Town, media: list[TownMedia] | None = None) -> TownPublicOut:
    """``media`` lets a listing pass rows loaded without their binary data."""
    rows = list(town.media or []) if media is None else media
    has_logo = any(m.kind == "logo" for m in rows)
    logo_url = media_public_path(town.id, "logo") if has_logo else town.logo_url
    codes = sorted(
        town.postal_codes or [], key=lambda c: (not c.is_primary, c.postal_code)
    )
    return TownPublicOut(
        id=town.id,
        name=town.name,
        slug=town.slug,
        postal_codes=[c.postal_code for c in codes],
        logo_url=logo_url,
        has_logo=has_logo,
        art_url=_art_url(town.id, rows),
        points_per_euro=town.points_per_euro,
        default_visit_points=town.default_visit_points,
        default_lang=town.default_lang,
        expiry_months=town.expiry_months,
    )


@router.get("", response_model=list[TownPublicOut])
async def list_towns_public(db: AsyncSession = Depends(get_db)):
    """Towns the residents app can offer (no auth), sorted by name.

    Leaves out the sales demo and the QA territory: they are modes of the
    product, not places a resident picks.
    """
    towns = list(
        (
            await db.execute(
                select(Town)
                .options(selectinload(Town.postal_codes), lazyload(Town.media))
                .where(
                    Town.slug != DEMO_TOWN_SLUG,
                    Town.slug.not_like(f"{QA_SLUG_PREFIX}%"),
                )
                .order_by(Town.name)
            )
        )
        .scalars()
        .all()
    )
    if not towns:
        return []
    # Only what the URLs need: the images themselves stay in the database.
    media_rows = (
        (
            await db.execute(
                select(TownMedia)
                .options(defer(TownMedia.data))
                .where(TownMedia.town_id.in_([t.id for t in towns]))
            )
        )
        .scalars()
        .all()
    )
    by_town: dict[str, list[TownMedia]] = {}
    for row in media_rows:
        by_town.setdefault(row.town_id, []).append(row)
    return [_to_public(t, by_town.get(t.id, [])) for t in towns]


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


@router.get("/public", response_model=TownPublicOut)
async def get_town_public(
    postal_code: str = Query(
        ...,
        min_length=4,
        max_length=10,
        description="Postal code that resolves to a town (e.g. 08380)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Public town rules for the residents app (no auth).

    Resolves ``postal_code`` → town and returns logo + point rules used when
    scanning QRs (``default_visit_points``) and converting euros.
    """
    postal = await get_postal_code(db, postal_code.strip())
    if postal is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Unknown postal code",
        )
    town = await _load_town(db, postal.town_id)
    if town is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    return _to_public(town)


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
    out = TownMediaOut(
        town_id=town.id,
        kind=kind,
        content_type=row.content_type,
        byte_size=row.byte_size,
        url=media_public_path(town.id, kind),
    )
    if kind == "logo":
        town.logo_url = out.url
    await db.commit()
    if kind != "logo":
        out.url = media_public_path(town.id, kind, media_version(row))
    return out


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
    if kind == "logo":
        town.logo_url = None
    await db.commit()


@router.api_route("/{town_id}/media/{kind}", methods=["GET", "HEAD"])
async def download_town_media(
    town_id: str,
    kind: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve town brand image (public so <img src> works without auth)."""
    row = await get_town_media(db, town_id, kind)
    if not row:
        return media_not_found_response()
    return media_bytes_response(
        row.data,
        row.content_type,
        cache="public, max-age=86400",
        byte_size=row.byte_size,
    )
