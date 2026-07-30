"""Merchant promotions CRUD."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.i18n import DEFAULT_LANG, normalize_lang, resolve_i18n
from app.db import get_db
from app.deps import require_merchant
from app.models import Promotion, Shop, Town, User
from app.schemas import PromotionCreate, PromotionOut, PromotionUpdate
from app.services.i18n_fields import apply_text_i18n
from app.services.towns import get_postal_code

router = APIRouter(prefix="/promotions", tags=["promotions"])


def _label_for(type_: str, title: str) -> str:
    return title[:40] if title else type_


def _resolve_out(promo: Promotion, lang: str, fallback_lang: str) -> PromotionOut:
    out = PromotionOut.model_validate(promo)
    out.label = (
        resolve_i18n(promo.label_i18n, lang, fallback_lang, legacy=promo.label) or ""
    )
    out.title = (
        resolve_i18n(promo.title_i18n, lang, fallback_lang, legacy=promo.title) or ""
    )
    out.detail = (
        resolve_i18n(promo.detail_i18n, lang, fallback_lang, legacy=promo.detail) or ""
    )
    out.conditions = resolve_i18n(
        promo.conditions_i18n, lang, fallback_lang, legacy=promo.conditions
    )
    return out


async def _town_default_lang(db: AsyncSession, shop_id: str) -> str:
    shop = await db.get(Shop, shop_id)
    if not shop:
        return DEFAULT_LANG
    town = await db.get(Town, shop.town_id)
    return (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG


async def _apply_promo_i18n(
    promo: Promotion,
    *,
    label: str | None,
    title: str | None,
    detail: str | None,
    conditions: str | None,
    label_i18n: dict | None,
    title_i18n: dict | None,
    detail_i18n: dict | None,
    conditions_i18n: dict | None,
    i18n_source_lang: str | None,
    default_lang: str,
) -> None:
    src = i18n_source_lang or promo.i18n_source_lang or default_lang
    promo.i18n_source_lang = normalize_lang(src)

    filled_title, plain_title = await apply_text_i18n(
        payload_i18n=title_i18n,
        payload_plain=title,
        existing_i18n=promo.title_i18n,
        existing_plain=promo.title,
        source_lang=src,
        default_lang=default_lang,
    )
    promo.title_i18n = filled_title
    promo.title = plain_title or promo.title or ""

    # Label defaults to truncated title when empty.
    effective_label = label
    if effective_label is None and label_i18n is None and not (promo.label or "").strip():
        effective_label = _label_for(promo.type, promo.title)

    filled_label, plain_label = await apply_text_i18n(
        payload_i18n=label_i18n,
        payload_plain=effective_label,
        existing_i18n=promo.label_i18n,
        existing_plain=promo.label,
        source_lang=src,
        default_lang=default_lang,
    )
    promo.label_i18n = filled_label
    promo.label = plain_label or promo.label or _label_for(promo.type, promo.title)

    filled_detail, plain_detail = await apply_text_i18n(
        payload_i18n=detail_i18n,
        payload_plain=detail,
        existing_i18n=promo.detail_i18n,
        existing_plain=promo.detail,
        source_lang=src,
        default_lang=default_lang,
    )
    promo.detail_i18n = filled_detail
    promo.detail = plain_detail or promo.detail or ""

    if conditions_i18n is not None or conditions is not None:
        filled_cond, plain_cond = await apply_text_i18n(
            payload_i18n=conditions_i18n,
            payload_plain=conditions,
            existing_i18n=promo.conditions_i18n,
            existing_plain=promo.conditions,
            source_lang=src,
            default_lang=default_lang,
        )
        promo.conditions_i18n = filled_cond
        promo.conditions = plain_cond or None


@router.get("/public", response_model=list[PromotionOut])
async def list_promotions_public(
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
    """Public promotions catalog for the residents app (no auth).

    Resolves ``postal_code`` → town, then returns active promotions of
    active shops in that town, with texts translated to ``lang``.
    """
    postal = await get_postal_code(db, postal_code.strip())
    if postal is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Unknown postal code",
        )
    town = await db.get(Town, postal.town_id)
    fallback = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    resolved = normalize_lang(lang) if lang else fallback

    rows = (
        await db.execute(
            select(Promotion)
            .join(Shop, Shop.id == Promotion.shop_id)
            .where(
                Shop.town_id == postal.town_id,
                Shop.status == "active",
                Shop.is_fake.is_(demo),
                Promotion.active.is_(True),
                Promotion.is_fake.is_(demo),
            )
            .order_by(Promotion.created_at.desc())
        )
    ).scalars().all()
    return [_resolve_out(p, resolved, fallback) for p in rows]


@router.get("", response_model=list[PromotionOut])
async def list_promotions(
    lang: str | None = Query(default=None),
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    if not user.shop_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No shop linked")
    rows = (
        await db.execute(
            select(Promotion)
            .where(
                Promotion.shop_id == user.shop_id,
                Promotion.is_fake.is_(user.is_fake),
            )
            .order_by(Promotion.created_at.desc())
        )
    ).scalars().all()
    fallback = await _town_default_lang(db, user.shop_id)
    resolved = normalize_lang(lang) if lang else fallback
    return [_resolve_out(p, resolved, fallback) for p in rows]


@router.post("", response_model=PromotionOut, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    payload: PromotionCreate,
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    if not user.shop_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No shop linked")
    default_lang = await _town_default_lang(db, user.shop_id)
    promo = Promotion(
        shop_id=user.shop_id,
        type=payload.type,
        label="",
        title="",
        detail="",
        value=payload.value,
        min_purchase=payload.min_purchase,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        conditions=None,
        active=payload.active,
        is_fake=user.is_fake,
    )
    await _apply_promo_i18n(
        promo,
        label=payload.label,
        title=payload.title,
        detail=payload.detail,
        conditions=payload.conditions,
        label_i18n=payload.label_i18n,
        title_i18n=payload.title_i18n,
        detail_i18n=payload.detail_i18n,
        conditions_i18n=payload.conditions_i18n,
        i18n_source_lang=payload.i18n_source_lang,
        default_lang=default_lang,
    )
    if not promo.title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title is required")
    db.add(promo)
    await db.commit()
    await db.refresh(promo)
    return _resolve_out(promo, default_lang, default_lang)


@router.patch("/{promo_id}", response_model=PromotionOut)
async def update_promotion(
    promo_id: str,
    payload: PromotionUpdate,
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    promo = await db.get(Promotion, promo_id)
    if not promo or promo.shop_id != user.shop_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Promotion not found")
    default_lang = await _town_default_lang(db, user.shop_id)
    data = payload.model_dump(exclude_unset=True)
    label = data.pop("label", None)
    title = data.pop("title", None)
    detail = data.pop("detail", None)
    conditions = data.pop("conditions", None)
    label_i18n = data.pop("label_i18n", None)
    title_i18n = data.pop("title_i18n", None)
    detail_i18n = data.pop("detail_i18n", None)
    conditions_i18n = data.pop("conditions_i18n", None)
    i18n_source_lang = data.pop("i18n_source_lang", None)
    for field, value in data.items():
        setattr(promo, field, value)
    if any(
        v is not None
        for v in (
            label,
            title,
            detail,
            conditions,
            label_i18n,
            title_i18n,
            detail_i18n,
            conditions_i18n,
            i18n_source_lang,
        )
    ):
        await _apply_promo_i18n(
            promo,
            label=label,
            title=title,
            detail=detail,
            conditions=conditions,
            label_i18n=label_i18n,
            title_i18n=title_i18n,
            detail_i18n=detail_i18n,
            conditions_i18n=conditions_i18n,
            i18n_source_lang=i18n_source_lang or promo.i18n_source_lang,
            default_lang=default_lang,
        )
    await db.commit()
    await db.refresh(promo)
    return _resolve_out(promo, default_lang, default_lang)


@router.delete("/{promo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_promotion(
    promo_id: str,
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    promo = await db.get(Promotion, promo_id)
    if not promo or promo.shop_id != user.shop_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Promotion not found")
    await db.delete(promo)
    await db.commit()
