"""QR scan validation — awards visit points via the ledger (resident).

Points and reactivation interval come from the town's active `qr_scan`
point action (same for all shops). Fallback: shop.visit_points + 30 days.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_resident
from app.models import QrScan, Shop, User
from app.schemas import ScanIn, ScanOut
from app.services.action_grants import ACTION_TYPE_QR_SCAN, find_active_action
from app.services.points import apply_points
from app.services.towns import assign_user_to_town

router = APIRouter(prefix="/scans", tags=["scans"])

DEFAULT_COOLDOWN_DAYS = 30


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _available_at(last_scan_at: datetime, cooldown_days: int) -> datetime:
    return _aware(last_scan_at) + timedelta(days=cooldown_days)


@router.post("", response_model=ScanOut, status_code=status.HTTP_201_CREATED)
async def scan_qr(
    payload: ScanIn,
    user: User = Depends(require_resident),
    db: AsyncSession = Depends(get_db),
):
    shop = (
        await db.execute(
            select(Shop).where(
                Shop.qr_code == payload.qr_code,
                Shop.is_fake.is_(user.is_fake),
            )
        )
    ).scalars().first()
    if not shop or shop.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invalid QR")

    # Temporarily bind town so find_active_action can scope the catalog rule.
    await assign_user_to_town(db, user, shop.town_id)

    action = await find_active_action(
        db,
        action_type=ACTION_TYPE_QR_SCAN,
        user=user,
        town_id=shop.town_id,
    )
    points = action.points if action is not None else shop.visit_points
    cooldown_days = (
        action.cooldown_days
        if action is not None and action.cooldown_days is not None
        else DEFAULT_COOLDOWN_DAYS
    )
    if points <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="QR scan awards no points"
        )

    last = (
        await db.execute(
            select(QrScan)
            .where(QrScan.user_id == user.id, QrScan.shop_id == shop.id)
            .order_by(QrScan.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    now = datetime.now(timezone.utc)
    if last is not None:
        available = _available_at(last.created_at, cooldown_days)
        if now < available:
            available_date = available.date().isoformat()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "qr_cooldown",
                    "message": (
                        f"QR already used for {shop.name}. "
                        f"Available again on {available_date}."
                    ),
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "available_at": available_date,
                    "cooldown_days": cooldown_days,
                },
            )

    today = date.today()
    scan = QrScan(
        user_id=user.id,
        shop_id=shop.id,
        points=points,
        scan_date=today,
        is_fake=user.is_fake,
    )
    db.add(scan)
    await db.flush()

    try:
        await apply_points(
            db,
            user=user,
            points=points,
            type="scan",
            town_id=shop.town_id,
            ref_id=scan.id,
            description=action.name if action else f"QR scan at {shop.name}",
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.refresh(user)
    await db.refresh(scan)
    created = scan.created_at or now
    next_available = _available_at(created, cooldown_days).date().isoformat()
    return ScanOut(
        id=scan.id,
        shop_id=shop.id,
        shop_name=shop.name,
        points=scan.points,
        created_at=created,
        balance=user.points,
        available_at=next_available,
    )
