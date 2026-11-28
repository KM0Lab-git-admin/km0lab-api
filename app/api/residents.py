"""Residents of a town (admin view), with optional activity from ledger."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import require_admin
from app.models import PointsTransaction, TownPostalCode, User
from app.schemas import IdentityOut, ResidentActivityOut, ResidentOut
from app.services.identities import identities_of, is_hidden_email, origins_of
from app.services.towns import load_user_with_town

router = APIRouter(prefix="/residents", tags=["residents"])


def _admin_resident_out(resident: User, origin=None) -> ResidentOut:
    """Admin always sees email; phone stays opt-in via contact_shared.

    ``origin`` is the identity the account was born with, if it has one.
    """
    item = ResidentOut.model_validate(resident)
    item.email = resident.email
    item.phone = resident.phone if resident.contact_shared else None
    item.email_hidden = is_hidden_email(resident.email)
    if origin is not None:
        item.signup_provider = origin.provider
        item.signup_at = origin.created_at
    return item


@router.get("", response_model=list[ResidentOut])
async def list_residents(
    q: str | None = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    stmt = (
        select(User)
        .join(TownPostalCode, User.postal_code == TownPostalCode.postal_code)
        .options(selectinload(User.postal_ref).selectinload(TownPostalCode.town))
        .where(
            User.is_resident.is_(True),
            TownPostalCode.town_id == user.town_id,
            User.is_fake.is_(user.is_fake),
        )
    )
    if q:
        stmt = stmt.where(
            or_(
                User.first_name.ilike(f"%{q}%"),
                User.last_name.ilike(f"%{q}%"),
                User.email.ilike(f"%{q}%"),
                User.slug.ilike(f"%{q}%"),
            )
        )
    stmt = stmt.order_by(User.created_at.desc())
    rows = (await db.execute(stmt)).scalars().unique().all()
    origins = await origins_of(db, [r.id for r in rows])
    return [_admin_resident_out(r, origins.get(r.id)) for r in rows]


@router.get("/{resident_id}", response_model=ResidentOut)
async def get_resident(
    resident_id: str,
    include_activity: bool = Query(default=True),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    resident = await load_user_with_town(db, resident_id)
    if (
        not resident
        or not resident.is_resident
        or resident.town_id != user.town_id
        or resident.is_fake != user.is_fake
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Resident not found")
    doors = await identities_of(db, resident.id)
    item = _admin_resident_out(
        resident, next((d for d in doors if d.is_first), None)
    )
    item.identities = [
        IdentityOut(
            provider=d.provider, linked_at=d.created_at, last_used_at=d.last_used_at
        )
        for d in doors
    ]
    if include_activity:
        txs = (
            await db.execute(
                select(PointsTransaction)
                .where(PointsTransaction.user_id == resident.id)
                .order_by(PointsTransaction.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
        item.activity = [
            ResidentActivityOut(
                id=tx.id,
                type=tx.type,
                description=tx.description,
                points=tx.points,
                created_at=tx.created_at,
            )
            for tx in txs
        ]
    return item
