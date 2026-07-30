"""Public catalog of shop categories with resolved labels (ca/es/en)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.i18n import DEFAULT_LANG, normalize_lang, resolve_i18n
from app.db import get_db
from app.deps import require_admin
from app.models import ShopCategory, User
from app.schemas.shop_categories import ShopCategoryOut, ShopCategoryUpdate
from app.services.i18n_fields import apply_text_i18n

router = APIRouter(prefix="/shop-categories", tags=["shop-categories"])

# Legacy fallback labels when label_i18n is null (mirrors BO i18n.ts).
_LEGACY_LABELS: dict[str, dict[str, str]] = {
    "bakery": {"ca": "Fleca", "es": "Panadería", "en": "Bakery"},
    "food": {"ca": "Alimentació", "es": "Alimentación", "en": "Food"},
    "cafe": {"ca": "Cafeteria", "es": "Cafetería", "en": "Café"},
    "restaurant": {"ca": "Restauració", "es": "Restauración", "en": "Restaurant"},
    "bar": {"ca": "Bar", "es": "Bar", "en": "Bar"},
    "butcher": {"ca": "Carnisseria", "es": "Carnicería", "en": "Butcher"},
    "greengrocer": {"ca": "Fruiteria", "es": "Frutería", "en": "Greengrocer"},
    "fishmonger": {"ca": "Peixateria", "es": "Pescadería", "en": "Fishmonger"},
    "pharmacy": {"ca": "Farmàcia", "es": "Farmacia", "en": "Pharmacy"},
    "bookstore": {"ca": "Llibreria", "es": "Librería", "en": "Bookstore"},
    "clothing": {"ca": "Moda", "es": "Moda", "en": "Clothing"},
    "hairdresser": {"ca": "Perruqueria", "es": "Peluquería", "en": "Hairdresser"},
    "services": {"ca": "Serveis", "es": "Servicios", "en": "Services"},
    "other": {"ca": "Altres", "es": "Otros", "en": "Other"},
}


def _resolve_out(cat: ShopCategory, lang: str) -> ShopCategoryOut:
    out = ShopCategoryOut.model_validate(cat)
    legacy_map = _LEGACY_LABELS.get(cat.slug) or {}
    legacy = legacy_map.get(lang) or legacy_map.get(DEFAULT_LANG) or cat.slug
    out.label = resolve_i18n(cat.label_i18n, lang, DEFAULT_LANG, legacy=legacy)
    return out


@router.get("", response_model=list[ShopCategoryOut])
async def list_shop_categories(
    include_inactive: bool = Query(default=False),
    lang: str | None = Query(
        default=None,
        description="Response language (ca|es|en). Defaults to ca.",
    ),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ShopCategory).order_by(
        ShopCategory.sort_order.asc(), ShopCategory.slug.asc()
    )
    if not include_inactive:
        stmt = stmt.where(ShopCategory.active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    resolved = normalize_lang(lang) if lang else DEFAULT_LANG
    return [_resolve_out(c, resolved) for c in rows]


@router.patch("/{slug}", response_model=ShopCategoryOut)
async def update_shop_category(
    slug: str,
    payload: ShopCategoryUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    del user  # auth gate only
    cat = await db.get(ShopCategory, slug)
    if not cat:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Category not found")
    data = payload.model_dump(exclude_unset=True)
    label_i18n = data.pop("label_i18n", None)
    i18n_source_lang = data.pop("i18n_source_lang", None)
    for field, value in data.items():
        setattr(cat, field, value)
    if label_i18n is not None or i18n_source_lang is not None:
        src = i18n_source_lang or cat.i18n_source_lang or DEFAULT_LANG
        cat.i18n_source_lang = normalize_lang(src)
        legacy = (_LEGACY_LABELS.get(cat.slug) or {}).get(DEFAULT_LANG)
        filled, _ = await apply_text_i18n(
            payload_i18n=label_i18n,
            payload_plain=None,
            existing_i18n=cat.label_i18n,
            existing_plain=legacy,
            source_lang=src,
            default_lang=DEFAULT_LANG,
        )
        cat.label_i18n = filled
    await db.commit()
    await db.refresh(cat)
    return _resolve_out(cat, cat.i18n_source_lang or DEFAULT_LANG)
