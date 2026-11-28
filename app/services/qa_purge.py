"""Cleanup of the QA territory. See ``app/qa.py``.

Safe on a database shared with real residents because:

1. Only rows reachable from a QA town (CP 9999x) or a QA account
   (``qa+…@km0lab.com``) are ever in scope.
2. Before deleting, every row in scope must be on the ``is_fake`` partition
   and every QA town must carry the ``[QA]`` name and ``qa-`` slug.
3. If anything outside the scope still points into it, nothing is deleted.

Any failed check raises ``QaPurgeRefused`` before the first DELETE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InvitationConversion,
    InvitationLink,
    Locality,
    OtpCode,
    PointAction,
    PointsTransaction,
    QrScan,
    Redemption,
    Reward,
    RewardMedia,
    RewardShop,
    Shop,
    ShopMedia,
    ShopPayment,
    Town,
    TownMedia,
    TownPostalCode,
    User,
)
from app.qa import (
    QA_EMAIL_LIKE,
    QA_FIXTURE_EMAILS,
    QA_NAME_PREFIX,
    QA_POSTAL_PREFIX,
    QA_SLUG_PREFIX,
    is_qa_email,
)
from app.services.account_erasure import erase_account_graph
from app.services.qa_territory import QA_FIXTURE_SHOP_IDS


class QaPurgeRefused(RuntimeError):
    """A safety check failed; nothing was deleted."""


@dataclass
class QaPurgeReport:
    mode: str
    dry_run: bool
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "counts": self.counts,
            "total": self.total,
        }


def _older_than(created: datetime | None, cutoff: datetime | None) -> bool:
    if cutoff is None or created is None:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created < cutoff


async def _all(db: AsyncSession, stmt) -> list:
    return list((await db.execute(stmt)).scalars().all())


async def _count(db: AsyncSession, model, *clauses) -> int:
    stmt = select(func.count()).select_from(model).where(*clauses)
    return int(await db.scalar(stmt) or 0)


def _require_fake(rows: list, what: str) -> None:
    bad = sum(1 for r in rows if not r.is_fake)
    if bad:
        raise QaPurgeRefused(
            f"{bad} {what} in scope are not flagged is_fake. Refusing."
        )


async def purge_qa_territory(
    db: AsyncSession,
    *,
    everything: bool = False,
    older_than_minutes: int = 0,
    dry_run: bool = True,
) -> QaPurgeReport:
    """Delete QA test data. Caller commits (unless ``dry_run``).

    - Default (``everything=False``): what test runs created — QA accounts
      other than the three fixture ones, with their movements, scans,
      redemptions and invitations, plus shops registered by tests. With
      ``older_than_minutes`` only data older than that goes, so a run in
      progress is left alone.
    - ``everything=True``: the whole territory, fixture included (accounts,
      catalog and towns). ``ensure_qa_territory`` rebuilds it.
    """
    report = QaPurgeReport(
        mode="everything" if everything else "runs", dry_run=dry_run
    )
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
        if older_than_minutes > 0 and not everything
        else None
    )

    # ── Scope: towns ──────────────────────────────────────────────────
    qa_postals = await _all(
        db,
        select(TownPostalCode).where(
            TownPostalCode.postal_code.like(f"{QA_POSTAL_PREFIX}_")
        ),
    )
    postal_codes = [p.postal_code for p in qa_postals]
    town_ids = sorted({p.town_id for p in qa_postals})
    towns = (
        await _all(db, select(Town).where(Town.id.in_(town_ids)))
        if town_ids
        else []
    )
    for town in towns:
        if not town.name.startswith(QA_NAME_PREFIX.strip()) or not (
            town.slug.startswith(QA_SLUG_PREFIX)
        ):
            raise QaPurgeRefused(
                f"Town {town.slug!r} owns a QA postal code but is not a QA "
                "town ([QA] name and qa- slug). Refusing."
            )
    if town_ids and await _count(
        db,
        TownPostalCode,
        TownPostalCode.town_id.in_(town_ids),
        TownPostalCode.postal_code.notin_(postal_codes),
    ):
        raise QaPurgeRefused(
            "A QA town owns postal codes outside 9999x. Refusing."
        )

    # ── Scope: accounts ───────────────────────────────────────────────
    users = [
        u
        for u in await _all(db, select(User).where(User.email.like(QA_EMAIL_LIKE)))
        if is_qa_email(u.email)
    ]
    if everything:
        if postal_codes:
            seen = {u.id for u in users}
            # Whoever lives in a QA town is test data, whatever the email.
            users += [
                u
                for u in await _all(
                    db, select(User).where(User.postal_code.in_(postal_codes))
                )
                if u.id not in seen
            ]
    else:
        users = [
            u
            for u in users
            if u.email not in QA_FIXTURE_EMAILS
            and _older_than(u.created_at, cutoff)
        ]
    _require_fake(users, "account(s)")
    user_ids = [u.id for u in users]
    emails = [u.email for u in users]

    # ── Scope: shops ──────────────────────────────────────────────────
    shops: list[Shop] = []
    if town_ids:
        shops = await _all(db, select(Shop).where(Shop.town_id.in_(town_ids)))
        if not everything:
            shops = [
                s
                for s in shops
                if s.id not in QA_FIXTURE_SHOP_IDS
                and _older_than(s.created_at, cutoff)
            ]
    _require_fake(shops, "shop(s)")
    shop_ids = [s.id for s in shops]

    # ── Scope: dependent rows ─────────────────────────────────────────
    links = (
        await _all(
            db,
            select(InvitationLink).where(
                or_(
                    InvitationLink.inviter_user_id.in_(user_ids),
                    InvitationLink.town_id.in_(town_ids if everything else []),
                )
            ),
        )
        if user_ids or (everything and town_ids)
        else []
    )
    link_ids = [link.id for link in links]

    conversions = await _all(
        db,
        select(InvitationConversion).where(
            or_(
                InvitationConversion.invitee_user_id.in_(user_ids),
                InvitationConversion.link_id.in_(link_ids),
                InvitationConversion.shop_id.in_(shop_ids),
            )
        ),
    )
    conv_ids = [c.id for c in conversions]

    redemptions = await _all(
        db,
        select(Redemption).where(
            or_(
                Redemption.user_id.in_(user_ids),
                Redemption.town_id.in_(town_ids if everything else []),
            )
        ),
    )
    _require_fake(redemptions, "redemption(s)")
    red_ids = [r.id for r in redemptions]

    scans = await _all(
        db,
        select(QrScan).where(
            or_(QrScan.user_id.in_(user_ids), QrScan.shop_id.in_(shop_ids))
        ),
    )
    _require_fake(scans, "scan(s)")
    scan_ids = [s.id for s in scans]

    transactions = await _all(
        db,
        select(PointsTransaction).where(
            or_(
                PointsTransaction.user_id.in_(user_ids),
                PointsTransaction.town_id.in_(town_ids if everything else []),
            )
        ),
    )
    _require_fake(transactions, "points movement(s)")

    # Points credited to an inviter we keep (a fixture account) for an
    # invitation we delete: undo the movement and the cached balance.
    kept_tx_ids = [c.points_tx_id for c in conversions if c.points_tx_id]
    in_scope_tx = {t.id for t in transactions}
    orphan_txs = [
        t
        for t in (
            await _all(
                db,
                select(PointsTransaction).where(
                    PointsTransaction.id.in_(kept_tx_ids)
                ),
            )
            if kept_tx_ids
            else []
        )
        if t.id not in in_scope_tx
    ]
    _require_fake(orphan_txs, "invitation reward movement(s)")

    rewards: list[Reward] = []
    actions: list[PointAction] = []
    if everything and town_ids:
        rewards = await _all(
            db, select(Reward).where(Reward.town_id.in_(town_ids))
        )
        actions = await _all(
            db, select(PointAction).where(PointAction.town_id.in_(town_ids))
        )
        _require_fake(rewards, "reward(s)")
        _require_fake(actions, "point action(s)")
        # Nothing outside the scope may still point into the territory.
        outside_user = User.id.notin_(user_ids)
        strays = {
            "redemptions": await _count(
                db,
                Redemption,
                Redemption.town_id.in_(town_ids),
                Redemption.user_id.notin_(user_ids),
            ),
            "points_transactions": await _count(
                db,
                PointsTransaction,
                PointsTransaction.town_id.in_(town_ids),
                PointsTransaction.user_id.notin_(user_ids),
            ),
            "qr_scans": await _count(
                db,
                QrScan,
                QrScan.shop_id.in_(shop_ids),
                QrScan.user_id.notin_(user_ids),
            ),
            "users_with_qa_shop": await _count(
                db, User, User.shop_id.in_(shop_ids), outside_user
            ),
        }
        found = {k: v for k, v in strays.items() if v}
        if found:
            raise QaPurgeRefused(
                "Accounts outside the QA territory have activity in it "
                f"({found}). Clean those up by hand first. Refusing."
            )

    counts = report.counts
    counts["users"] = len(user_ids)
    counts["otp_codes"] = await _count(db, OtpCode, OtpCode.email.in_(emails))
    counts["points_transactions"] = len(transactions) + len(orphan_txs)
    counts["qr_scans"] = len(scan_ids)
    counts["redemptions"] = len(red_ids)
    counts["invitation_links"] = len(link_ids)
    counts["invitation_conversions"] = len(conv_ids)
    counts["shops"] = len(shop_ids)
    if everything:
        counts["rewards"] = len(rewards)
        counts["point_actions"] = len(actions)
        counts["towns"] = len(town_ids)

    if dry_run:
        return report

    # Same order as a rehearsal cleanup. Orphan invitation rewards are
    # undone here because a fixture account can outlive the invitation.
    await erase_account_graph(
        db,
        user_ids=user_ids,
        emails=emails,
        shop_ids=shop_ids,
        redemption_ids=red_ids,
        scan_ids=scan_ids,
        link_ids=link_ids,
        conversion_ids=conv_ids,
        transaction_ids=[t.id for t in transactions],
        orphan_transactions=orphan_txs,
    )

    if everything and town_ids:
        reward_ids = [r.id for r in rewards]
        await db.execute(
            delete(RewardShop).where(RewardShop.reward_id.in_(reward_ids))
        )
        await db.execute(
            delete(RewardMedia).where(RewardMedia.reward_id.in_(reward_ids))
        )
        await db.execute(delete(Reward).where(Reward.id.in_(reward_ids)))
        await db.execute(
            delete(PointAction).where(
                PointAction.id.in_([a.id for a in actions])
            )
        )
        await db.execute(
            delete(ShopPayment).where(ShopPayment.town_id.in_(town_ids))
        )
        await db.execute(
            delete(TownMedia).where(TownMedia.town_id.in_(town_ids))
        )
        # Postal codes and shops point at the localities: free them first.
        await db.execute(
            update(TownPostalCode)
            .where(TownPostalCode.town_id.in_(town_ids))
            .values(locality_id=None)
        )
        await db.execute(delete(Locality).where(Locality.town_id.in_(town_ids)))
        await db.execute(
            delete(TownPostalCode).where(TownPostalCode.town_id.in_(town_ids))
        )
        await db.execute(delete(Town).where(Town.id.in_(town_ids)))

    await db.flush()
    return report
