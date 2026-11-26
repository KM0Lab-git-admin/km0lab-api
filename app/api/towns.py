"""Town config (admin of that town), town media and the public town cards."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import assert_town_scope, require_admin
from app.models import Locality, Town, TownMedia, TownPostalCode, User
from app.schemas import TownMediaOut, TownOut, TownPublicOut, TownUpdate
from app.schemas.towns import LocalityOut
from app.services import public_towns
from app.services.localities import art_urls, get_locality_art, list_localities
from app.services.public_towns import public_town_card, public_town_list
from app.services.media_http import media_bytes_response, media_not_found_response
from app.services.town_media import (
    delete_town_media,
    get_town_media,
    media_public_path,
    media_version,
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


async def _locality_cards(
    db: AsyncSession, town: Town
) -> tuple[list[LocalityOut], str | None]:
    """Every town of the municipality, plus the municipality's own art."""
    localities = await list_localities(db, town.id)
    codes = (
        await db.execute(
            select(TownPostalCode)
            .where(TownPostalCode.town_id == town.id)
            .order_by(TownPostalCode.postal_code)
        )
    ).scalars().all()
    by_locality, town_art = await art_urls(
        db, town.id, [loc.id for loc in localities]
    )
    cards = [
        LocalityOut(
            id=loc.id,
            name=loc.name,
            slug=loc.slug,
            postal_codes=[c.postal_code for c in codes if c.locality_id == loc.id],
            art_url=by_locality.get(loc.id) or town_art,
        )
        for loc in localities
    ]
    return cards, town_art


async def _admin_out(db: AsyncSession, town: Town) -> TownOut:
    """The municipality as its administrator sees it, towns included."""
    out = _to_out(town)
    out.localities, _ = await _locality_cards(db, town)
    return out


@router.get("", response_model=list[TownPublicOut])
async def list_towns_public(db: AsyncSession = Depends(get_db)):
    """Towns the residents app can offer (no auth), sorted by name.

    One entry per town a resident can live in: a municipality that groups
    several towns contributes one entry for each. Leaves out the sales demo
    and the QA territory: they are modes of the product, not places a
    resident picks. Served from memory (``app/services/public_towns``).
    """
    return await public_town_list(db)


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
    return await _admin_out(db, town)


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
    card = await public_town_card(db, postal_code.strip())
    if card is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Unknown postal code",
        )
    return card


@router.api_route("/localities/{locality_id}/art", methods=["GET", "HEAD"])
async def download_locality_art(
    locality_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Illustration of one town of a municipality (public, for <img src>)."""
    row = await get_locality_art(db, locality_id)
    if not row:
        return media_not_found_response()
    return media_bytes_response(
        row.data,
        row.content_type,
        cache="public, max-age=86400",
        byte_size=row.byte_size,
    )


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
    return await _admin_out(db, town)


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
    public_towns.invalidate()
    town = await _load_town(db, town_id)
    return await _admin_out(db, town)  # type: ignore[arg-type]


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
    public_towns.invalidate()
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
    public_towns.invalidate()


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
