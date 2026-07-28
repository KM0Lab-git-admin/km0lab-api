"""Rewards catalog (admin write, resident read)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import Reward, RewardShop, User
from app.schemas import RewardCreate, RewardOut, RewardUpdate

router = APIRouter(prefix="/rewards", tags=["rewards"])


def _to_out(reward: Reward) -> RewardOut:
    data = RewardOut.model_validate(reward)
    data.shop_ids = [rs.shop_id for rs in (reward.shops or [])]
    return data


async def _load_reward(db: AsyncSession, reward_id: str) -> Reward | None:
    return (
        await db.execute(
            select(Reward)
            .options(selectinload(Reward.shops))
            .where(Reward.id == reward_id)
        )
    ).scalars().first()


@router.get("", response_model=list[RewardOut])
async def list_rewards(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    town_id = user.town_id
    if not town_id and user.role == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    stmt = select(Reward).options(selectinload(Reward.shops))
    if town_id:
        stmt = stmt.where(Reward.town_id == town_id)
    if user.role == "resident":
        stmt = stmt.where(Reward.status == "active")
    stmt = stmt.order_by(Reward.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=RewardOut, status_code=status.HTTP_201_CREATED)
async def create_reward(
    payload: RewardCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    data = payload.model_dump(exclude={"shop_ids"})
    reward = Reward(town_id=user.town_id, **data)
    db.add(reward)
    await db.flush()
    for shop_id in payload.shop_ids:
        db.add(RewardShop(reward_id=reward.id, shop_id=shop_id))
    await db.commit()
    reward = await _load_reward(db, reward.id)
    return _to_out(reward)  # type: ignore[arg-type]


@router.patch("/{reward_id}", response_model=RewardOut)
async def update_reward(
    reward_id: str,
    payload: RewardUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    reward = await _load_reward(db, reward_id)
    if not reward or reward.town_id != user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reward not found")
    data = payload.model_dump(exclude_unset=True)
    shop_ids = data.pop("shop_ids", None)
    for field, value in data.items():
        setattr(reward, field, value)
    if shop_ids is not None:
        await db.execute(delete(RewardShop).where(RewardShop.reward_id == reward.id))
        for shop_id in shop_ids:
            db.add(RewardShop(reward_id=reward.id, shop_id=shop_id))
    await db.commit()
    reward = await _load_reward(db, reward_id)
    return _to_out(reward)  # type: ignore[arg-type]


@router.get("/{reward_id}", response_model=RewardOut)
async def get_reward(
    reward_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    reward = await _load_reward(db, reward_id)
    if not reward:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reward not found")
    if user.role == "admin" and reward.town_id != user.town_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Out of town scope")
    return _to_out(reward)
