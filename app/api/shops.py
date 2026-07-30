"""Shop CRUD (admin) + merchant profile / QR / binary media."""

from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.demo import resolve_public_demo
from app.deps import (
    assert_shop_scope,
    assert_town_scope,
    get_current_user,
    require_admin,
    require_resident,
    resolve_acting_shop,
)
from app.catalog.i18n import DEFAULT_LANG, normalize_lang, resolve_i18n
from app.models import QrScan, Shop, Town, User
from app.schemas import (
    QrOut,
    ShopCreate,
    ShopOut,
    ShopResidentOut,
    ShopProfileUpdate,
    ShopUpdate,
)
from app.schemas.shops import ShopMediaOut
from app.services.action_grants import ACTION_TYPE_QR_SCAN, find_active_action
from app.services.i18n_fields import apply_text_i18n
from app.services.shop_categories import resolve_category_slugs
from app.services.shop_media import (
    delete_shop_media,
    get_shop_media,
    media_kinds_present,
    media_public_path,
    upsert_shop_media,
)
from app.services.shop_qr import build_scan_url, ensure_shop_qr, qr_png_url
from app.services.towns import get_postal_code

router = APIRouter(prefix="/shops", tags=["shops"])

DEFAULT_COOLDOWN_DAYS = 30


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _available_at(last_scan_at: datetime, cooldown_days: int) -> datetime:
    return _aware(last_scan_at) + timedelta(days=cooldown_days)


async def _shop_out(
    db: AsyncSession,
    shop: Shop,
    *,
    lang: str | None = None,
    fallback_lang: str | None = None,
) -> ShopOut:
    kinds = await media_kinds_present(db, shop.id)
    has_logo = "logo" in kinds
    has_hero = "hero" in kinds
    town = await db.get(Town, shop.town_id)
    data = ShopOut.model_validate(shop)
    fb = fallback_lang or DEFAULT_LANG
    resolved = normalize_lang(lang) if lang else fb
    data.description = resolve_i18n(
        shop.description_i18n, resolved, fb, legacy=shop.description
    )
    return data.model_copy(
        update={
            "town_name": town.name if town else None,
            "has_logo": has_logo,
            "has_hero": has_hero,
            "logo_url": media_public_path(shop.id, "logo")
            if has_logo
            else shop.logo_url,
            "hero_url": media_public_path(shop.id, "hero")
            if has_hero
            else shop.hero_url,
        }
    )


async def _default_lang_for_shop(db: AsyncSession, shop: Shop) -> str:
    town = await db.get(Town, shop.town_id)
    return (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG


async def _apply_shop_description_i18n(
    shop: Shop,
    *,
    description: str | None,
    description_i18n: dict | None,
    i18n_source_lang: str | None,
    default_lang: str,
) -> None:
    src = i18n_source_lang or shop.i18n_source_lang or default_lang
    shop.i18n_source_lang = normalize_lang(src)
    filled, plain = await apply_text_i18n(
        payload_i18n=description_i18n,
        payload_plain=description,
        existing_i18n=shop.description_i18n,
        existing_plain=shop.description,
        source_lang=src,
        default_lang=default_lang,
    )
    shop.description_i18n = filled
    shop.description = plain or None


async def _qr_out(db: AsyncSession, shop: Shop, *, is_fake: bool) -> QrOut:
    await ensure_shop_qr(db, shop)
    total_scans = (
        await db.execute(
            select(func.count())
            .select_from(QrScan)
            .where(QrScan.shop_id == shop.id, QrScan.is_fake.is_(is_fake))
        )
    ).scalar_one()
    points_awarded = (
        await db.execute(
            select(func.coalesce(func.sum(QrScan.points), 0)).where(
                QrScan.shop_id == shop.id, QrScan.is_fake.is_(is_fake)
            )
        )
    ).scalar_one()
    assert shop.qr_code is not None
    return QrOut(
        shop_id=shop.id,
        qr_code=shop.qr_code,
        scan_url=build_scan_url(shop.qr_code),
        png_url=qr_png_url(shop.id),
        visit_points=shop.visit_points,
        total_scans=total_scans,
        points_awarded=int(points_awarded),
    )


@router.get("/public", response_model=list[ShopOut])
async def list_shops_public(
    postal_code: str = Query(
        ...,
        min_length=4,
        max_length=10,
        description="Postal code that resolves to a town (e.g. 08380)",
    ),
    lang: str | None = Query(
        default=None,
        description="Response language (ca|es|en). Defaults to the town's default_lang.",
    ),
    demo: bool = Query(
        default=False,
        description="If true, return the fake/demo partition (is_fake=true)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Public shops catalog for the residents app (no auth).

    Resolves ``postal_code`` → town, then returns active shops with
    description translated to ``lang``.
    """
    postal = await get_postal_code(db, postal_code.strip())
    if postal is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Unknown postal code",
        )
    town = await db.get(Town, postal.town_id)
    fallback = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    use_demo = resolve_public_demo(postal.postal_code, demo)

    rows = (
        await db.execute(
            select(Shop)
            .where(
                Shop.town_id == postal.town_id,
                Shop.is_fake.is_(use_demo),
                Shop.status == "active",
            )
            .order_by(Shop.created_at.desc())
        )
    ).scalars().all()
    return [
        await _shop_out(db, s, lang=lang, fallback_lang=fallback) for s in rows
    ]


@router.get("/for-me", response_model=list[ShopResidentOut])
async def list_shops_for_resident(
    postal_code: str | None = Query(
        default=None,
        min_length=4,
        max_length=10,
        description=(
            "Postal code that resolves to a town. "
            "Defaults to the authenticated user's postal_code."
        ),
    ),
    lang: str | None = Query(
        default=None,
        description="Response language (ca|es|en). Defaults to the town's default_lang.",
    ),
    user: User = Depends(require_resident),
    db: AsyncSession = Depends(get_db),
):
    """Resident shop list for a town, with this user's QR scan state.

    Note: ``GET /shops/me`` is the merchant profile; this endpoint is the
    resident catalog with ``scanned`` / ``scan_available`` per shop.
    Partition matches ``user.is_fake`` (same as ``POST /scans``).
    """
    cp = (postal_code or user.postal_code or "").strip()
    if not cp:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="postal_code required (query or user profile)",
        )
    postal = await get_postal_code(db, cp)
    if postal is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Unknown postal code",
        )
    town = await db.get(Town, postal.town_id)
    fallback = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    # Scans are partitioned by user.is_fake — list the same partition.
    use_demo = user.is_fake

    rows = (
        await db.execute(
            select(Shop)
            .where(
                Shop.town_id == postal.town_id,
                Shop.is_fake.is_(use_demo),
                Shop.status == "active",
            )
            .order_by(Shop.created_at.desc())
        )
    ).scalars().all()
    if not rows:
        return []

    shop_ids = [s.id for s in rows]
    last_scans = (
        await db.execute(
            select(QrScan)
            .where(
                QrScan.user_id == user.id,
                QrScan.shop_id.in_(shop_ids),
            )
            .order_by(QrScan.created_at.desc())
        )
    ).scalars().all()
    last_by_shop: dict[str, QrScan] = {}
    for scan in last_scans:
        if scan.shop_id not in last_by_shop:
            last_by_shop[scan.shop_id] = scan

    action = await find_active_action(
        db,
        action_type=ACTION_TYPE_QR_SCAN,
        user=user,
        town_id=postal.town_id,
    )
    cooldown_days = (
        action.cooldown_days
        if action is not None and action.cooldown_days is not None
        else DEFAULT_COOLDOWN_DAYS
    )

    now = datetime.now(timezone.utc)
    out: list[ShopResidentOut] = []
    for shop in rows:
        base = await _shop_out(db, shop, lang=lang, fallback_lang=fallback)
        last = last_by_shop.get(shop.id)
        scanned = last is not None
        available_at: str | None = None
        scan_available = True
        if last is not None:
            nxt = _available_at(last.created_at, cooldown_days)
            available_at = nxt.date().isoformat()
            scan_available = now >= nxt
        out.append(
            ShopResidentOut(
                **base.model_dump(),
                scanned=scanned,
                last_scanned_at=last.created_at if last else None,
                available_at=available_at,
                scan_available=scan_available,
            )
        )
    return out


@router.get("", response_model=list[ShopOut])
async def list_shops(
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    lang: str | None = Query(default=None),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    stmt = select(Shop).where(
        Shop.town_id == user.town_id,
        Shop.is_fake.is_(user.is_fake),
    )
    if status_filter:
        stmt = stmt.where(Shop.status == status_filter)
    if q:
        stmt = stmt.where(Shop.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Shop.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    town = await db.get(Town, user.town_id)
    fallback = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    return [await _shop_out(db, s, lang=lang, fallback_lang=fallback) for s in rows]


@router.post("", response_model=ShopOut, status_code=status.HTTP_201_CREATED)
async def create_shop(
    payload: ShopCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    categories = await resolve_category_slugs(db, payload.categories)
    town = await db.get(Town, user.town_id)
    default_lang = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    visit_points = (
        payload.visit_points
        if payload.visit_points is not None
        else (town.default_visit_points if town else 10)
    )
    shop = Shop(
        town_id=user.town_id,
        name=payload.name,
        emoji=payload.emoji,
        categories=categories,
        contact_email=payload.contact_email.lower(),
        visit_points=visit_points,
        address=payload.address,
        postal_code=payload.postal_code,
        phone=payload.phone,
        website=payload.website,
        opening_hours=(
            payload.opening_hours.model_dump() if payload.opening_hours else None
        ),
        status="pending",
        is_fake=user.is_fake,
    )
    if payload.description is not None or payload.description_i18n is not None:
        await _apply_shop_description_i18n(
            shop,
            description=payload.description,
            description_i18n=payload.description_i18n,
            i18n_source_lang=payload.i18n_source_lang,
            default_lang=default_lang,
        )
    db.add(shop)
    await db.flush()
    await ensure_shop_qr(db, shop)
    await db.commit()
    await db.refresh(shop)
    return await _shop_out(db, shop, fallback_lang=default_lang)


@router.get("/me", response_model=ShopOut)
async def get_my_shop(
    lang: str | None = Query(default=None),
    shop: Shop = Depends(resolve_acting_shop),
    db: AsyncSession = Depends(get_db),
):
    fallback = await _default_lang_for_shop(db, shop)
    return await _shop_out(db, shop, lang=lang, fallback_lang=fallback)


@router.patch("/me", response_model=ShopOut)
async def update_my_shop(
    payload: ShopProfileUpdate,
    shop: Shop = Depends(resolve_acting_shop),
    db: AsyncSession = Depends(get_db),
):
    default_lang = await _default_lang_for_shop(db, shop)
    data = payload.model_dump(exclude_unset=True)
    if "categories" in data:
        data["categories"] = await resolve_category_slugs(db, data["categories"])
    description = data.pop("description", None)
    description_i18n = data.pop("description_i18n", None)
    i18n_source_lang = data.pop("i18n_source_lang", None)
    for field, value in data.items():
        setattr(shop, field, value)
    if any(v is not None for v in (description, description_i18n, i18n_source_lang)):
        await _apply_shop_description_i18n(
            shop,
            description=description,
            description_i18n=description_i18n,
            i18n_source_lang=i18n_source_lang or shop.i18n_source_lang,
            default_lang=default_lang,
        )
    await db.commit()
    await db.refresh(shop)
    return await _shop_out(db, shop, fallback_lang=default_lang)


@router.put("/me/media/{kind}", response_model=ShopMediaOut)
async def upload_my_media(
    kind: str,
    file: UploadFile = File(...),
    shop: Shop = Depends(resolve_acting_shop),
    db: AsyncSession = Depends(get_db),
):
    row = await upsert_shop_media(db, shop_id=shop.id, kind=kind, upload=file)
    await db.commit()
    return ShopMediaOut(
        shop_id=shop.id,
        kind=row.kind,
        content_type=row.content_type,
        byte_size=row.byte_size,
        url=media_public_path(shop.id, row.kind),
    )


@router.delete("/me/media/{kind}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_media(
    kind: str,
    shop: Shop = Depends(resolve_acting_shop),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_shop_media(db, shop_id=shop.id, kind=kind)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Media not found")
    await db.commit()


@router.get("/me/qr", response_model=QrOut)
async def get_my_qr(
    shop: Shop = Depends(resolve_acting_shop),
    db: AsyncSession = Depends(get_db),
):
    """Merchant 'Mi QR' screen: PNG URL + scan/points stats."""
    out = await _qr_out(db, shop, is_fake=shop.is_fake)
    await db.commit()
    return out


@router.post("/me/qr", response_model=QrOut)
async def generate_my_qr(
    shop: Shop = Depends(resolve_acting_shop),
    db: AsyncSession = Depends(get_db),
):
    """Idempotent: ensure token+PNG exist (does not rotate)."""
    out = await _qr_out(db, shop, is_fake=shop.is_fake)
    await db.commit()
    return out


@router.put("/{shop_id}/media/{kind}", response_model=ShopMediaOut)
async def upload_shop_media(
    shop_id: str,
    kind: str,
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shop not found")
    assert_town_scope(user, shop.town_id)
    row = await upsert_shop_media(db, shop_id=shop.id, kind=kind, upload=file)
    await db.commit()
    return ShopMediaOut(
        shop_id=shop.id,
        kind=row.kind,
        content_type=row.content_type,
        byte_size=row.byte_size,
        url=media_public_path(shop.id, row.kind),
    )


@router.get("/{shop_id}/media/{kind}")
async def download_shop_media(
    shop_id: str,
    kind: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve logo/hero/qr bytes (public so <img src> works without auth)."""
    row = await get_shop_media(db, shop_id, kind)
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


@router.get("/{shop_id}", response_model=ShopOut)
async def get_shop(
    shop_id: str,
    lang: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if user.has_role("admin"):
        assert_town_scope(user, shop.town_id)
    elif user.has_role("merchant"):
        assert_shop_scope(user, shop.id)
    fallback = await _default_lang_for_shop(db, shop)
    return await _shop_out(db, shop, lang=lang, fallback_lang=fallback)


@router.patch("/{shop_id}", response_model=ShopOut)
async def update_shop(
    shop_id: str,
    payload: ShopUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shop not found")
    assert_town_scope(user, shop.town_id)
    default_lang = await _default_lang_for_shop(db, shop)
    data = payload.model_dump(exclude_unset=True)
    if "categories" in data:
        data["categories"] = await resolve_category_slugs(db, data["categories"])
    description = data.pop("description", None)
    description_i18n = data.pop("description_i18n", None)
    i18n_source_lang = data.pop("i18n_source_lang", None)
    for field, value in data.items():
        setattr(shop, field, value)
    if any(v is not None for v in (description, description_i18n, i18n_source_lang)):
        await _apply_shop_description_i18n(
            shop,
            description=description,
            description_i18n=description_i18n,
            i18n_source_lang=i18n_source_lang or shop.i18n_source_lang,
            default_lang=default_lang,
        )
    await db.commit()
    await db.refresh(shop)
    return await _shop_out(db, shop, fallback_lang=default_lang)
