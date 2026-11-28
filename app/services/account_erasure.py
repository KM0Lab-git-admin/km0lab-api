"""Delete accounts and the shops they own, children first.

``qa_purge`` and the rehearsal cleanup both use this so the order stays
one: invitations, vouchers, scans, points, the account, then the shop.
The caller has already decided the rows are in scope.
"""

from __future__ import annotations

from sqlalchemy import delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InvitationConversion,
    InvitationEvent,
    InvitationLink,
    OtpCode,
    PointsTransaction,
    Promotion,
    QrScan,
    Redemption,
    RedemptionEvent,
    RewardShop,
    Shop,
    ShopMedia,
    ShopPayment,
    User,
    UserIdentity,
    VoucherAttempt,
)


async def erase_account_graph(
    db: AsyncSession,
    *,
    user_ids: list[str],
    emails: list[str],
    shop_ids: list[str],
    redemption_ids: list[str],
    scan_ids: list[str],
    link_ids: list[str],
    conversion_ids: list[str],
    transaction_ids: list[str],
    orphan_transactions: list[PointsTransaction] | None = None,
) -> None:
    """Remove the graph. Caller commits. An empty id list deletes nothing."""
    if conversion_ids:
        await db.execute(
            delete(InvitationConversion).where(
                InvitationConversion.id.in_(conversion_ids)
            )
        )
    for tx in orphan_transactions or []:
        # A reward paid to someone we are keeping, for an invitation we drop.
        owner = await db.get(User, tx.user_id)
        if owner is not None:
            owner.points = owner.points - tx.points
        await db.delete(tx)
    await db.flush()

    event_clauses = []
    if user_ids:
        event_clauses.append(InvitationEvent.actor_user_id.in_(user_ids))
    if link_ids:
        event_clauses.append(InvitationEvent.link_id.in_(link_ids))
    if event_clauses:
        await db.execute(delete(InvitationEvent).where(or_(*event_clauses)))
    if link_ids:
        await db.execute(
            delete(InvitationLink).where(InvitationLink.id.in_(link_ids))
        )
    if redemption_ids:
        await db.execute(
            delete(RedemptionEvent).where(
                RedemptionEvent.redemption_id.in_(redemption_ids)
            )
        )
        await db.execute(
            delete(Redemption).where(Redemption.id.in_(redemption_ids))
        )
    if scan_ids:
        await db.execute(delete(QrScan).where(QrScan.id.in_(scan_ids)))
    if transaction_ids:
        await db.execute(
            delete(PointsTransaction).where(
                PointsTransaction.id.in_(transaction_ids)
            )
        )
    if emails:
        await db.execute(delete(OtpCode).where(OtpCode.email.in_(emails)))
    if user_ids:
        # MySQL would cascade identities; said out loud so every database does it.
        await db.execute(
            delete(UserIdentity).where(UserIdentity.user_id.in_(user_ids))
        )
        await db.execute(delete(User).where(User.id.in_(user_ids)))

    if shop_ids:
        await db.execute(
            update(User).where(User.shop_id.in_(shop_ids)).values(shop_id=None)
        )
        await db.execute(
            update(Redemption)
            .where(Redemption.shop_id.in_(shop_ids))
            .values(shop_id=None)
        )
        await db.execute(delete(Promotion).where(Promotion.shop_id.in_(shop_ids)))
        await db.execute(delete(RewardShop).where(RewardShop.shop_id.in_(shop_ids)))
        await db.execute(delete(ShopPayment).where(ShopPayment.shop_id.in_(shop_ids)))
        await db.execute(delete(ShopMedia).where(ShopMedia.shop_id.in_(shop_ids)))
        await db.execute(
            delete(VoucherAttempt).where(VoucherAttempt.shop_id.in_(shop_ids))
        )
        await db.execute(delete(Shop).where(Shop.id.in_(shop_ids)))
    await db.flush()
