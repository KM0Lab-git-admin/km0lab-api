"""Merchant promotions CRUD."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_merchant
from app.models import Promotion, User
from app.schemas import PromotionCreate, PromotionOut, PromotionUpdate

router = APIRouter(prefix="/promotions", tags=["promotions"])


def _label_for(type_: str, title: str) -> str:
    return title[:40] if title else type_


@router.get("", response_model=list[PromotionOut])
async def list_promotions(
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
    return [PromotionOut.model_validate(p) for p in rows]


@router.post("", response_model=PromotionOut, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    payload: PromotionCreate,
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    if not user.shop_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No shop linked")
    promo = Promotion(
        shop_id=user.shop_id,
        type=payload.type,
        label=payload.label or _label_for(payload.type, payload.title),
        title=payload.title,
        detail=payload.detail,
        value=payload.value,
        min_purchase=payload.min_purchase,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        conditions=payload.conditions,
        active=payload.active,
        is_fake=user.is_fake,
    )
    db.add(promo)
    await db.commit()
    await db.refresh(promo)
    return PromotionOut.model_validate(promo)


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
    data = payload.model_dump(exclude_unset=True)
    # DB column `label` is NOT NULL — never persist null.
    if "label" in data and not data["label"]:
        data["label"] = _label_for(
            data.get("type") or promo.type,
            data.get("title") or promo.title,
        )
    for field, value in data.items():
        setattr(promo, field, value)
    await db.commit()
    await db.refresh(promo)
    return PromotionOut.model_validate(promo)


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
