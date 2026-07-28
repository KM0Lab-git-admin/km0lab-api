"""Shop CRUD (admin) + merchant profile / QR."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import (
    assert_shop_scope,
    assert_town_scope,
    get_current_user,
    require_admin,
    require_merchant,
)
from app.models import Shop, User
from app.schemas import QrOut, ShopCreate, ShopOut, ShopProfileUpdate, ShopUpdate

router = APIRouter(prefix="/shops", tags=["shops"])


@router.get("", response_model=list[ShopOut])
async def list_shops(
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    stmt = select(Shop).where(Shop.town_id == user.town_id)
    if status_filter:
        stmt = stmt.where(Shop.status == status_filter)
    if q:
        stmt = stmt.where(Shop.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Shop.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [ShopOut.model_validate(s) for s in rows]


@router.post("", response_model=ShopOut, status_code=status.HTTP_201_CREATED)
async def create_shop(
    payload: ShopCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    shop = Shop(
        town_id=user.town_id,
        name=payload.name,
        emoji=payload.emoji,
        logo_url=payload.logo_url,
        categories=payload.categories,
        contact_email=payload.contact_email.lower(),
        visit_points=payload.visit_points,
        address=payload.address,
        status="pending",
    )
    db.add(shop)
    await db.commit()
    await db.refresh(shop)
    return ShopOut.model_validate(shop)


@router.get("/me", response_model=ShopOut)
async def get_my_shop(
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    if not user.shop_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No shop linked")
    shop = await db.get(Shop, user.shop_id)
    if not shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shop not found")
    return ShopOut.model_validate(shop)


@router.patch("/me", response_model=ShopOut)
async def update_my_shop(
    payload: ShopProfileUpdate,
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    if not user.shop_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No shop linked")
    shop = await db.get(Shop, user.shop_id)
    if not shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shop not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shop, field, value)
    await db.commit()
    await db.refresh(shop)
    return ShopOut.model_validate(shop)


@router.post("/me/qr", response_model=QrOut)
async def generate_my_qr(
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    if not user.shop_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No shop linked")
    shop = await db.get(Shop, user.shop_id)
    if not shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if not shop.qr_code:
        shop.qr_code = secrets.token_urlsafe(16)
        await db.commit()
        await db.refresh(shop)
    return QrOut(
        shop_id=shop.id, qr_code=shop.qr_code, visit_points=shop.visit_points
    )


@router.get("/{shop_id}", response_model=ShopOut)
async def get_shop(
    shop_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shop not found")
    if user.role == "admin":
        assert_town_scope(user, shop.town_id)
    elif user.role == "merchant":
        assert_shop_scope(user, shop.id)
    return ShopOut.model_validate(shop)


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
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shop, field, value)
    await db.commit()
    await db.refresh(shop)
    return ShopOut.model_validate(shop)
