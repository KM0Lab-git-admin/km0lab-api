"""Shop payments: admin settles used vouchers with local shops."""

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin
from app.models import Redemption, Reward, Shop, ShopPayment, User
from app.schemas import ShopDebtOut, ShopPaymentCreate, ShopPaymentOut
from app.services.payments import voucher_amount

router = APIRouter(prefix="/payments", tags=["payments"])


def _require_town(user: User) -> str:
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    return user.town_id


async def _shop_names(db: AsyncSession, shop_ids: set[str]) -> dict[str, str]:
    if not shop_ids:
        return {}
    shops = (
        (await db.execute(select(Shop).where(Shop.id.in_(shop_ids)))).scalars().all()
    )
    return {s.id: s.name for s in shops}


@router.get("/debts", response_model=list[ShopDebtOut])
async def list_debts(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Pending (used, unpaid vouchers) and paid totals aggregated per shop."""
    town_id = _require_town(user)
    rows = (
        await db.execute(
            select(Redemption, Reward)
            .join(Reward, Redemption.reward_id == Reward.id)
            .where(
                Redemption.town_id == town_id,
                Redemption.is_fake.is_(user.is_fake),
                Redemption.flow == "voucher_qr",
                Redemption.status == "used",
                Redemption.payment_id.is_(None),
                Redemption.shop_id.is_not(None),
            )
        )
    ).all()
    pending_count: dict[str, int] = defaultdict(int)
    pending_amount: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for redemption, reward in rows:
        pending_count[redemption.shop_id] += 1
        pending_amount[redemption.shop_id] += voucher_amount(redemption, reward)

    paid_rows = (
        await db.execute(
            select(ShopPayment.shop_id, func.sum(ShopPayment.total_amount))
            .where(
                ShopPayment.town_id == town_id,
                ShopPayment.is_fake.is_(user.is_fake),
            )
            .group_by(ShopPayment.shop_id)
        )
    ).all()
    paid = {shop_id: Decimal(total or 0) for shop_id, total in paid_rows}

    shop_ids = set(pending_count) | set(paid)
    names = await _shop_names(db, shop_ids)
    debts = [
        ShopDebtOut(
            shop_id=shop_id,
            shop_name=names.get(shop_id, ""),
            pending_count=pending_count.get(shop_id, 0),
            pending_amount=float(pending_amount.get(shop_id, Decimal("0"))),
            paid_total=float(paid.get(shop_id, Decimal("0"))),
        )
        for shop_id in shop_ids
    ]
    debts.sort(key=lambda d: (-d.pending_amount, d.shop_name))
    return debts


@router.get("", response_model=list[ShopPaymentOut])
async def list_payments(
    shop_id: str | None = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    town_id = _require_town(user)
    stmt = select(ShopPayment).where(
        ShopPayment.town_id == town_id,
        ShopPayment.is_fake.is_(user.is_fake),
    )
    if shop_id:
        stmt = stmt.where(ShopPayment.shop_id == shop_id)
    stmt = stmt.order_by(ShopPayment.created_at.desc())
    payments = (await db.execute(stmt)).scalars().all()
    if not payments:
        return []

    payment_ids = [p.id for p in payments]
    linked = (
        await db.execute(
            select(Redemption.id, Redemption.payment_id).where(
                Redemption.payment_id.in_(payment_ids)
            )
        )
    ).all()
    by_payment: dict[str, list[str]] = defaultdict(list)
    for redemption_id, pid in linked:
        by_payment[pid].append(redemption_id)
    names = await _shop_names(db, {p.shop_id for p in payments})
    return [
        ShopPaymentOut(
            id=p.id,
            town_id=p.town_id,
            shop_id=p.shop_id,
            shop_name=names.get(p.shop_id, ""),
            total_amount=float(p.total_amount),
            note=p.note,
            redemption_ids=by_payment.get(p.id, []),
            is_fake=p.is_fake,
            created_at=p.created_at,
        )
        for p in payments
    ]


@router.post("", response_model=ShopPaymentOut, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: ShopPaymentCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Settle a batch of used vouchers with a shop."""
    town_id = _require_town(user)
    shop = await db.get(Shop, payload.shop_id)
    if not shop or shop.town_id != town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shop not found")

    rows = (
        await db.execute(
            select(Redemption, Reward)
            .join(Reward, Redemption.reward_id == Reward.id)
            .where(Redemption.id.in_(payload.redemption_ids))
        )
    ).all()
    found = {r.id for r, _ in rows}
    missing = set(payload.redemption_ids) - found
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Redemptions not found: {', '.join(sorted(missing))}",
        )

    total = Decimal("0")
    for redemption, reward in rows:
        if (
            redemption.town_id != town_id
            or redemption.is_fake != user.is_fake
            or redemption.shop_id != payload.shop_id
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Redemption {redemption.id} out of scope",
            )
        if redemption.flow != "voucher_qr" or redemption.status != "used":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Redemption {redemption.id} is not a used voucher",
            )
        if redemption.payment_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Redemption {redemption.id} already paid",
            )
        total += voucher_amount(redemption, reward)

    payment = ShopPayment(
        town_id=town_id,
        shop_id=payload.shop_id,
        total_amount=total,
        note=payload.note,
        is_fake=user.is_fake,
    )
    db.add(payment)
    await db.flush()
    for redemption, _ in rows:
        redemption.payment_id = payment.id
    await db.commit()
    await db.refresh(payment)
    return ShopPaymentOut(
        id=payment.id,
        town_id=payment.town_id,
        shop_id=payment.shop_id,
        shop_name=shop.name,
        total_amount=float(payment.total_amount),
        note=payment.note,
        redemption_ids=[r.id for r, _ in rows],
        is_fake=payment.is_fake,
        created_at=payment.created_at,
    )
