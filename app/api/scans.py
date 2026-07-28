"""QR scan validation — awards visit points via the ledger (resident)."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_resident
from app.models import QrScan, Shop, User
from app.schemas import ScanIn, ScanOut
from app.services.points import apply_points

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=ScanOut, status_code=status.HTTP_201_CREATED)
async def scan_qr(
    payload: ScanIn,
    user: User = Depends(require_resident),
    db: AsyncSession = Depends(get_db),
):
    shop = (
        await db.execute(select(Shop).where(Shop.qr_code == payload.qr_code))
    ).scalars().first()
    if not shop or shop.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invalid QR")

    today = date.today()
    existing = (
        await db.execute(
            select(QrScan).where(
                QrScan.user_id == user.id,
                QrScan.shop_id == shop.id,
                QrScan.scan_date == today,
            )
        )
    ).scalars().first()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Already scanned today"
        )

    scan = QrScan(
        user_id=user.id,
        shop_id=shop.id,
        points=shop.visit_points,
        scan_date=today,
    )
    db.add(scan)
    await db.flush()

    if not user.town_id:
        user.town_id = shop.town_id

    try:
        await apply_points(
            db,
            user=user,
            points=shop.visit_points,
            type="scan",
            town_id=shop.town_id,
            ref_id=scan.id,
            description=f"QR scan at {shop.name}",
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Already scanned today"
        ) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.refresh(user)
    await db.refresh(scan)
    return ScanOut(
        id=scan.id,
        shop_id=shop.id,
        points=scan.points,
        created_at=scan.created_at or datetime.now(timezone.utc),
        balance=user.points,
    )
