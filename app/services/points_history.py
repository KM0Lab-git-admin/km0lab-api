"""Build resident points history from the ledger, with light enrichment."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    PointAction,
    PointsTransaction,
    QrScan,
    Redemption,
    Reward,
    Shop,
    User,
)
from app.schemas.points import PointsHistoryItem, PointsHistoryOut


async def build_points_history(
    db: AsyncSession,
    *,
    user: User,
    filter: str = "all",
    limit: int = 100,
) -> PointsHistoryOut:
    """Return balance, earned/spent totals and filtered ledger items."""
    earned = (
        await db.execute(
            select(func.coalesce(func.sum(PointsTransaction.points), 0)).where(
                PointsTransaction.user_id == user.id,
                PointsTransaction.points > 0,
            )
        )
    ).scalar_one()
    spent_raw = (
        await db.execute(
            select(func.coalesce(func.sum(PointsTransaction.points), 0)).where(
                PointsTransaction.user_id == user.id,
                PointsTransaction.points < 0,
            )
        )
    ).scalar_one()
    earned_total = int(earned)
    spent_total = abs(int(spent_raw))

    stmt = (
        select(PointsTransaction)
        .where(PointsTransaction.user_id == user.id)
        .order_by(PointsTransaction.created_at.desc())
        .limit(limit)
    )
    if filter == "earned":
        stmt = stmt.where(PointsTransaction.points > 0)
    elif filter == "spent":
        stmt = stmt.where(PointsTransaction.points < 0)

    txs = (await db.execute(stmt)).scalars().all()
    items = await _enrich_items(db, txs)
    return PointsHistoryOut(
        balance=user.points,
        earned_total=earned_total,
        spent_total=spent_total,
        items=items,
    )


async def _enrich_items(
    db: AsyncSession, txs: list[PointsTransaction]
) -> list[PointsHistoryItem]:
    scan_ids = [t.ref_id for t in txs if t.type == "scan" and t.ref_id]
    redemption_ids = [
        t.ref_id for t in txs if t.type == "redemption" and t.ref_id
    ]
    action_ids = [
        t.ref_id
        for t in txs
        if t.type in {"welcome", "birthday", "action"} and t.ref_id
    ]

    scans_by_id: dict[str, QrScan] = {}
    shops_by_id: dict[str, Shop] = {}
    redemptions_by_id: dict[str, Redemption] = {}
    rewards_by_id: dict[str, Reward] = {}
    actions_by_id: dict[str, PointAction] = {}

    if scan_ids:
        scans = (
            await db.execute(select(QrScan).where(QrScan.id.in_(scan_ids)))
        ).scalars().all()
        scans_by_id = {s.id: s for s in scans}
        shop_ids = {s.shop_id for s in scans}
        if shop_ids:
            shops = (
                await db.execute(select(Shop).where(Shop.id.in_(shop_ids)))
            ).scalars().all()
            shops_by_id.update({s.id: s for s in shops})

    if redemption_ids:
        redemptions = (
            await db.execute(
                select(Redemption).where(Redemption.id.in_(redemption_ids))
            )
        ).scalars().all()
        redemptions_by_id = {r.id: r for r in redemptions}
        reward_ids = {r.reward_id for r in redemptions}
        shop_ids = {r.shop_id for r in redemptions if r.shop_id}
        if reward_ids:
            rewards = (
                await db.execute(select(Reward).where(Reward.id.in_(reward_ids)))
            ).scalars().all()
            rewards_by_id = {r.id: r for r in rewards}
        if shop_ids:
            shops = (
                await db.execute(select(Shop).where(Shop.id.in_(shop_ids)))
            ).scalars().all()
            shops_by_id.update({s.id: s for s in shops})

    if action_ids:
        actions = (
            await db.execute(
                select(PointAction).where(PointAction.id.in_(action_ids))
            )
        ).scalars().all()
        actions_by_id = {a.id: a for a in actions}

    items: list[PointsHistoryItem] = []
    for tx in txs:
        title: str | None = None
        shop_name: str | None = None
        reward_name: str | None = None

        if tx.type == "scan" and tx.ref_id and tx.ref_id in scans_by_id:
            scan = scans_by_id[tx.ref_id]
            shop = shops_by_id.get(scan.shop_id)
            shop_name = shop.name if shop else None
            title = tx.description or (shop_name and f"QR scan at {shop_name}")
        elif (
            tx.type == "redemption"
            and tx.ref_id
            and tx.ref_id in redemptions_by_id
        ):
            redemption = redemptions_by_id[tx.ref_id]
            reward = rewards_by_id.get(redemption.reward_id)
            reward_name = reward.name if reward else None
            if redemption.shop_id:
                shop = shops_by_id.get(redemption.shop_id)
                shop_name = shop.name if shop else None
            title = reward_name or tx.description
        elif tx.type in {"welcome", "birthday", "action"} and tx.ref_id:
            action = actions_by_id.get(tx.ref_id)
            title = (action.name if action else None) or tx.description
        else:
            title = tx.description

        items.append(
            PointsHistoryItem(
                id=tx.id,
                type=tx.type,
                points=tx.points,
                description=tx.description,
                title=title,
                shop_name=shop_name,
                reward_name=reward_name,
                ref_id=tx.ref_id,
                created_at=tx.created_at,
            )
        )
    return items
