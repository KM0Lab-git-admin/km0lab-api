"""Derived KPIs for admin and merchant dashboards."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin, require_merchant
from app.models import PointAction, Promotion, QrScan, Redemption, User
from app.schemas import AdminStatsOut, MerchantStatsOut

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/admin", response_model=AdminStatsOut)
async def admin_stats(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    town_id = user.town_id

    active_users = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.role == "resident", User.town_id == town_id)
        )
    ).scalar_one()

    points_in_circulation = (
        await db.execute(
            select(func.coalesce(func.sum(User.points), 0)).where(
                User.role == "resident", User.town_id == town_id
            )
        )
    ).scalar_one()

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    redemptions_this_month = (
        await db.execute(
            select(func.count())
            .select_from(Redemption)
            .where(
                Redemption.town_id == town_id,
                Redemption.requested_at >= month_start,
            )
        )
    ).scalar_one()

    active_actions = (
        await db.execute(
            select(func.count())
            .select_from(PointAction)
            .where(PointAction.town_id == town_id, PointAction.active.is_(True))
        )
    ).scalar_one()

    total_actions = (
        await db.execute(
            select(func.count())
            .select_from(PointAction)
            .where(PointAction.town_id == town_id)
        )
    ).scalar_one()

    return AdminStatsOut(
        active_users=active_users,
        points_in_circulation=int(points_in_circulation),
        redemptions_this_month=redemptions_this_month,
        active_actions=active_actions,
        total_actions=total_actions,
    )


@router.get("/merchant", response_model=MerchantStatsOut)
async def merchant_stats(
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    if not user.shop_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No shop linked")
    shop_id = user.shop_id

    total_scans = (
        await db.execute(
            select(func.count()).select_from(QrScan).where(QrScan.shop_id == shop_id)
        )
    ).scalar_one()

    unique_visitors = (
        await db.execute(
            select(func.count(func.distinct(QrScan.user_id))).where(
                QrScan.shop_id == shop_id
            )
        )
    ).scalar_one()

    points_awarded = (
        await db.execute(
            select(func.coalesce(func.sum(QrScan.points), 0)).where(
                QrScan.shop_id == shop_id
            )
        )
    ).scalar_one()

    active_promotions = (
        await db.execute(
            select(func.count())
            .select_from(Promotion)
            .where(Promotion.shop_id == shop_id, Promotion.active.is_(True))
        )
    ).scalar_one()

    return MerchantStatsOut(
        total_scans=total_scans,
        unique_visitors=unique_visitors,
        points_awarded=int(points_awarded),
        active_promotions=active_promotions,
    )
