"""Public catalog of shop category slugs (labels via front/backoffice i18n)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ShopCategory
from app.schemas.shop_categories import ShopCategoryOut

router = APIRouter(prefix="/shop-categories", tags=["shop-categories"])


@router.get("", response_model=list[ShopCategoryOut])
async def list_shop_categories(
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ShopCategory).order_by(
        ShopCategory.sort_order.asc(), ShopCategory.slug.asc()
    )
    if not include_inactive:
        stmt = stmt.where(ShopCategory.active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [ShopCategoryOut.model_validate(c) for c in rows]
