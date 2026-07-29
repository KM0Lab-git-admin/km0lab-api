"""Redemptions: create (resident), manage status (admin), use voucher (merchant)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user, require_admin, require_merchant, require_resident
from app.models import Redemption, RedemptionEvent, Reward, User
from app.schemas import (
    RedemptionCreate,
    RedemptionOut,
    RedemptionStatusUpdate,
    RedemptionUseIn,
    RedemptionValidateIn,
)
from app.services.points import apply_points
from app.services.towns import assign_user_to_town
from app.services.voucher_codes import allocate_voucher_code

router = APIRouter(prefix="/redemptions", tags=["redemptions"])

VOUCHER_TYPES = {"discount", "balance"}


def derive_flow(reward_type: str) -> str:
    return "voucher_qr" if reward_type in VOUCHER_TYPES else "delivery"


def initial_status(flow: str) -> str:
    return "pending_use" if flow == "voucher_qr" else "requested"


def _to_out(r: Redemption) -> RedemptionOut:
    return RedemptionOut.model_validate(r)


async def _load(db: AsyncSession, redemption_id: str) -> Redemption | None:
    return (
        await db.execute(
            select(Redemption)
            .options(selectinload(Redemption.events))
            .where(Redemption.id == redemption_id)
        )
    ).scalars().first()


async def _mark_used(
    db: AsyncSession,
    redemption: Redemption,
    *,
    shop_id: str | None,
    amount_applied: str | None,
) -> None:
    redemption.status = "used"
    redemption.used_at = datetime.now(timezone.utc)
    applied = amount_applied if amount_applied is not None else redemption.amount
    redemption.amount_applied = applied
    if not redemption.shop_id:
        redemption.shop_id = shop_id
    db.add(
        RedemptionEvent(
            redemption_id=redemption.id, status="used", note="Voucher used"
        )
    )


@router.post("", response_model=RedemptionOut, status_code=status.HTTP_201_CREATED)
async def create_redemption(
    payload: RedemptionCreate,
    user: User = Depends(require_resident),
    db: AsyncSession = Depends(get_db),
):
    reward = await db.get(Reward, payload.reward_id)
    if (
        not reward
        or reward.status != "active"
        or reward.is_fake != user.is_fake
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reward not available")
    if user.town_id and reward.town_id != user.town_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Out of town scope")
    if reward.stock is not None and reward.stock <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Out of stock")
    if user.points < reward.points_required:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Insufficient points")

    flow = derive_flow(reward.type)
    code = await allocate_voucher_code(db) if flow == "voucher_qr" else None
    redemption = Redemption(
        town_id=reward.town_id,
        user_id=user.id,
        reward_id=reward.id,
        flow=flow,
        points_spent=reward.points_required,
        status=initial_status(flow),
        code=code,
        amount=payload.amount,
        shop_id=payload.shop_id,
        is_fake=user.is_fake,
    )
    db.add(redemption)
    await db.flush()
    db.add(
        RedemptionEvent(
            redemption_id=redemption.id,
            status=redemption.status,
            note="Created",
            is_fake=user.is_fake,
        )
    )
    try:
        await apply_points(
            db,
            user=user,
            points=-reward.points_required,
            type="redemption",
            town_id=reward.town_id,
            ref_id=redemption.id,
            description=f"Redeemed {reward.name}",
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if reward.stock is not None:
        reward.stock -= 1
        if reward.stock <= 0:
            reward.status = "sold_out"

    # Link resident to town on first redemption if missing.
    await assign_user_to_town(db, user, reward.town_id)

    await db.commit()
    redemption = await _load(db, redemption.id)
    return _to_out(redemption)  # type: ignore[arg-type]


@router.get("", response_model=list[RedemptionOut])
async def list_redemptions(
    status_filter: str | None = Query(default=None, alias="status"),
    reward_type: str | None = None,
    shop_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Redemption).options(selectinload(Redemption.events)).where(
        Redemption.is_fake.is_(user.is_fake)
    )
    if user.has_role("admin"):
        if not user.town_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
        stmt = stmt.where(Redemption.town_id == user.town_id)
    elif user.has_role("merchant") and not user.has_role("resident"):
        stmt = stmt.where(Redemption.shop_id == user.shop_id)
    elif user.has_role("merchant") and user.has_role("resident"):
        # Dual role: own redemptions + shop queue (client can filter).
        stmt = stmt.where(
            or_(Redemption.user_id == user.id, Redemption.shop_id == user.shop_id)
        )
    else:
        stmt = stmt.where(Redemption.user_id == user.id)
    if status_filter:
        stmt = stmt.where(Redemption.status == status_filter)
    if shop_id:
        stmt = stmt.where(Redemption.shop_id == shop_id)
    if reward_type:
        stmt = stmt.join(Reward).where(Reward.type == reward_type)
    stmt = stmt.order_by(Redemption.requested_at.desc())
    rows = (await db.execute(stmt)).scalars().unique().all()
    return [_to_out(r) for r in rows]


@router.post("/validate", response_model=RedemptionOut)
async def validate_voucher(
    payload: RedemptionValidateIn,
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    """Merchant validates a voucher by its 5-digit code (lookup + use)."""
    redemption = (
        await db.execute(
            select(Redemption)
            .options(selectinload(Redemption.events))
            .where(
                Redemption.code == payload.code,
                Redemption.flow == "voucher_qr",
                Redemption.is_fake.is_(user.is_fake),
            )
        )
    ).scalars().first()
    if not redemption:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Voucher not found")
    if redemption.shop_id and redemption.shop_id != user.shop_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Out of shop scope")
    if redemption.status == "used":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="already_used"
        )
    if redemption.status == "cancelled":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="cancelled"
        )
    if redemption.status != "pending_use":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Not pending use"
        )
    await _mark_used(
        db,
        redemption,
        shop_id=user.shop_id,
        amount_applied=payload.amount_applied,
    )
    await db.commit()
    redemption = await _load(db, redemption.id)
    return _to_out(redemption)  # type: ignore[arg-type]


@router.patch("/{redemption_id}/status", response_model=RedemptionOut)
async def update_status(
    redemption_id: str,
    payload: RedemptionStatusUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    redemption = await _load(db, redemption_id)
    if not redemption or redemption.town_id != user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Redemption not found")
    redemption.status = payload.status
    if payload.status == "delivered":
        redemption.delivered_at = datetime.now(timezone.utc)
    if payload.status == "used":
        redemption.used_at = datetime.now(timezone.utc)
    db.add(
        RedemptionEvent(
            redemption_id=redemption.id,
            status=payload.status,
            note=payload.note,
        )
    )
    await db.commit()
    redemption = await _load(db, redemption_id)
    return _to_out(redemption)  # type: ignore[arg-type]


@router.post("/{redemption_id}/use", response_model=RedemptionOut)
async def use_voucher(
    redemption_id: str,
    payload: RedemptionUseIn,
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    redemption = await _load(db, redemption_id)
    if not redemption or redemption.flow != "voucher_qr":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Voucher not found")
    if redemption.shop_id and redemption.shop_id != user.shop_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Out of shop scope")
    if redemption.status != "pending_use":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not pending use")
    await _mark_used(
        db,
        redemption,
        shop_id=user.shop_id,
        amount_applied=payload.amount_applied,
    )
    await db.commit()
    redemption = await _load(db, redemption_id)
    return _to_out(redemption)  # type: ignore[arg-type]
