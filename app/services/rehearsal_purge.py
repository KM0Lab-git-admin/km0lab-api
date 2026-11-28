"""Remove one rehearsal from a municipality, and nothing else.

The list of emails is the whole scope: those accounts, the shops they own,
and the rows that belong to them. Anyone outside the list who scanned a
shop, redeemed there, or shares an invitation with the list stops the run
before the first delete. Stock taken by the vouchers comes back. The
municipality's account cap is left as it is and reported, because the
rehearsal may have lowered it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InvitationConversion,
    InvitationLink,
    OtpCode,
    PointsTransaction,
    Promotion,
    QrScan,
    Redemption,
    Reward,
    RewardShop,
    Shop,
    ShopMedia,
    ShopPayment,
    User,
    UserIdentity,
    VoucherAttempt,
)
from app.services.account_erasure import erase_account_graph
from app.services.towns import find_municipality

NOTHING = "nada que borrar"


class RehearsalRefused(RuntimeError):
    """A safety check failed; nothing was deleted."""


@dataclass
class StockReturn:
    reward: str
    before: int
    after: int
    status: str


@dataclass
class RehearsalReport:
    town: str
    max_residents: int | None
    dry_run: bool
    nothing: bool = False
    accounts: dict[str, dict[str, int]] = field(default_factory=dict)
    shops: dict[str, dict[str, int]] = field(default_factory=dict)
    stock: list[StockReturn] = field(default_factory=list)

    def lines(self) -> list[str]:
        if self.nothing:
            body = [NOTHING]
        else:
            body = [f"{self.town}: rehearsal accounts"]
            for email, counts in self.accounts.items():
                detail = ", ".join(f"{n} {kind}" for kind, n in counts.items() if n)
                body.append(f"  {email}: {detail or 'no rows of their own'}")
            for name, counts in self.shops.items():
                detail = ", ".join(f"{n} {kind}" for kind, n in counts.items() if n)
                body.append(f"  shop {name}: {detail or 'no rows of its own'}")
            for row in self.stock:
                body.append(
                    f"  stock '{row.reward}': {row.before} -> {row.after} ({row.status})"
                )
        cap = "unlimited" if self.max_residents is None else str(self.max_residents)
        body.append(
            f"Aforo actual de {self.town}: {cap}. El script no lo toca. "
            "Para dejarlo en 200 (el piloto): «Configuració» del panel, o "
            f"python -m scripts.set_pilot_points --town \"{self.town}\"."
        )
        return body


def _emails(raw: list[str]) -> list[str]:
    seen: list[str] = []
    for item in raw:
        email = item.strip().lower()
        if email and email not in seen:
            seen.append(email)
    return seen


async def _count(db: AsyncSession, model, *clauses) -> int:
    if not clauses:
        return 0
    return int(
        await db.scalar(select(func.count()).select_from(model).where(*clauses))
        or 0
    )


async def purge_rehearsal(
    db: AsyncSession,
    *,
    town: str,
    emails: list[str],
    dry_run: bool = True,
) -> RehearsalReport:
    """Plan or delete. Caller commits when ``dry_run`` is false.

    A second run, once the accounts are gone, reports that there is
    nothing to delete. A list that only partly matches refuses.
    """
    wanted = _emails(emails)
    if not wanted:
        raise RehearsalRefused("La lista de correos está vacía.")
    municipality = await find_municipality(db, town)
    if municipality is None:
        raise RehearsalRefused(f"No hay una población que coincida con '{town}'.")
    report = RehearsalReport(
        town=municipality.name,
        max_residents=municipality.max_residents,
        dry_run=dry_run,
    )

    users = list(
        (
            await db.execute(
                select(User).where(func.lower(User.email).in_(wanted))
            )
        ).scalars().all()
    )
    found = {u.email.lower(): u for u in users}
    missing = [email for email in wanted if email not in found]
    if not found:
        report.nothing = True
        return report
    if missing:
        raise RehearsalRefused(
            "Estas cuentas no existen: " + ", ".join(missing) + "."
        )

    outside_town = [
        email
        for email, user in found.items()
        if user.postal_ref is None or user.postal_ref.town_id != municipality.id
    ]
    if outside_town:
        raise RehearsalRefused(
            f"Estas cuentas no están en {municipality.name}: "
            + ", ".join(outside_town)
            + "."
        )
    blocked = [
        email
        for email, user in found.items()
        if user.is_admin or not (user.is_resident or user.is_merchant)
    ]
    if blocked:
        raise RehearsalRefused(
            "Estas cuentas no son solo vecino o comercio: " + ", ".join(blocked) + "."
        )

    user_ids = [u.id for u in users]
    shop_ids = [u.shop_id for u in users if u.shop_id]
    shops = (
        list(
            (
                await db.execute(select(Shop).where(Shop.id.in_(shop_ids)))
            ).scalars().all()
        )
        if shop_ids
        else []
    )
    wrong_shop = [s.name for s in shops if s.town_id != municipality.id]
    if wrong_shop:
        raise RehearsalRefused(
            "Estos comercios no son de "
            f"{municipality.name}: "
            + ", ".join(wrong_shop)
            + "."
        )

    await _refuse_outsiders(db, user_ids=user_ids, shop_ids=shop_ids)

    links = list(
        (
            await db.execute(
                select(InvitationLink).where(
                    InvitationLink.inviter_user_id.in_(user_ids)
                )
            )
        ).scalars().all()
    )
    link_ids = [link.id for link in links]
    conversion_clauses = [InvitationConversion.invitee_user_id.in_(user_ids)]
    if link_ids:
        conversion_clauses.append(InvitationConversion.link_id.in_(link_ids))
    if shop_ids:
        conversion_clauses.append(InvitationConversion.shop_id.in_(shop_ids))
    conversions = list(
        (
            await db.execute(
                select(InvitationConversion).where(or_(*conversion_clauses))
            )
        ).scalars().all()
    )
    redemptions = list(
        (
            await db.execute(
                select(Redemption).where(Redemption.user_id.in_(user_ids))
            )
        ).scalars().all()
    )
    scans = list(
        (
            await db.execute(
                select(QrScan).where(
                    or_(
                        QrScan.user_id.in_(user_ids),
                        *([QrScan.shop_id.in_(shop_ids)] if shop_ids else []),
                    )
                )
            )
        ).scalars().all()
    )
    transactions = list(
        (
            await db.execute(
                select(PointsTransaction).where(
                    PointsTransaction.user_id.in_(user_ids)
                )
            )
        ).scalars().all()
    )

    for user in users:
        email = user.email.lower()
        report.accounts[email] = {
            "identidades": await _count(
                db, UserIdentity, UserIdentity.user_id == user.id
            ),
            "códigos": await _count(db, OtpCode, OtpCode.email == user.email),
            "puntos": sum(1 for tx in transactions if tx.user_id == user.id),
            "escaneos": sum(1 for scan in scans if scan.user_id == user.id),
            "vales": sum(1 for row in redemptions if row.user_id == user.id),
            "invitaciones": sum(1 for link in links if link.inviter_user_id == user.id),
            "conversiones": sum(
                1
                for row in conversions
                if row.invitee_user_id == user.id
                or any(link.id == row.link_id and link.inviter_user_id == user.id for link in links)
            ),
        }
    for shop in shops:
        report.shops[shop.name] = {
            "promociones": await _count(db, Promotion, Promotion.shop_id == shop.id),
            "premios": await _count(db, RewardShop, RewardShop.shop_id == shop.id),
            "pagos": await _count(db, ShopPayment, ShopPayment.shop_id == shop.id),
            "fotos": await _count(db, ShopMedia, ShopMedia.shop_id == shop.id),
            "intentos": await _count(
                db, VoucherAttempt, VoucherAttempt.shop_id == shop.id
            ),
            "escaneos": sum(1 for scan in scans if scan.shop_id == shop.id),
        }
    report.stock = await _stock_plan(db, redemptions, write=not dry_run)

    if dry_run:
        return report

    await erase_account_graph(
        db,
        user_ids=user_ids,
        emails=[user.email for user in users],
        shop_ids=[shop.id for shop in shops],
        redemption_ids=[row.id for row in redemptions],
        scan_ids=[scan.id for scan in scans],
        link_ids=link_ids,
        conversion_ids=[row.id for row in conversions],
        transaction_ids=[tx.id for tx in transactions],
    )
    return report


async def _refuse_outsiders(
    db: AsyncSession, *, user_ids: list[str], shop_ids: list[str]
) -> None:
    reasons: list[str] = []
    if shop_ids:
        scans = await _count(
            db,
            QrScan,
            QrScan.shop_id.in_(shop_ids),
            QrScan.user_id.notin_(user_ids),
        )
        if scans:
            reasons.append(f"{scans} escaneo(s) de alguien de fuera")
        vouchers = await _count(
            db,
            Redemption,
            Redemption.shop_id.in_(shop_ids),
            Redemption.user_id.notin_(user_ids),
        )
        if vouchers:
            reasons.append(f"{vouchers} vale(s) de alguien de fuera")
        owners = await _count(
            db, User, User.shop_id.in_(shop_ids), User.id.notin_(user_ids)
        )
        if owners:
            reasons.append(f"{owners} cuenta(s) de fuera ligadas al comercio")

    # The other way around: a listed person spent a voucher at a shop we are
    # not deleting, or the town has already paid that voucher.
    if shop_ids:
        shop_outside = and_(
            Redemption.shop_id.is_not(None),
            Redemption.shop_id.notin_(shop_ids),
        )
    else:
        shop_outside = Redemption.shop_id.is_not(None)
    leaked = await _count(
        db,
        Redemption,
        Redemption.user_id.in_(user_ids),
        or_(shop_outside, Redemption.payment_id.is_not(None)),
    )
    if leaked:
        reasons.append(
            f"{leaked} vale(s) de un comercio de fuera o ya pagado(s)"
        )

    rows = (
        await db.execute(
            select(InvitationConversion, InvitationLink)
            .join(InvitationLink, InvitationLink.id == InvitationConversion.link_id)
            .where(
                or_(
                    InvitationConversion.invitee_user_id.in_(user_ids),
                    InvitationLink.inviter_user_id.in_(user_ids),
                    *(
                        [InvitationConversion.shop_id.in_(shop_ids)]
                        if shop_ids
                        else []
                    ),
                )
            )
        )
    ).all()
    crossed = 0
    for conversion, link in rows:
        inviter_in = link.inviter_user_id in user_ids
        invitee_in = conversion.invitee_user_id in user_ids
        # A shop conversion is "in" when its shop is one we are deleting.
        shop_in = bool(shop_ids) and conversion.shop_id in shop_ids
        if inviter_in and (invitee_in or shop_in):
            continue
        if not inviter_in and not invitee_in and not shop_in:
            continue
        crossed += 1
    if crossed:
        reasons.append(f"{crossed} invitación(es) con alguien de fuera")
    if reasons:
        raise RehearsalRefused(
            "Hay actividad de alguien que no está en la lista: "
            + "; ".join(reasons)
            + ". No se ha borrado nada."
        )


async def _stock_plan(
    db: AsyncSession, redemptions: list[Redemption], *, write: bool
) -> list[StockReturn]:
    """Units a deleted voucher still holds. A cancelled one already gave its back."""
    units: dict[str, int] = {}
    for redemption in redemptions:
        if redemption.status == "cancelled":
            continue
        units[redemption.reward_id] = units.get(redemption.reward_id, 0) + 1
    returned: list[StockReturn] = []
    for reward_id, count in units.items():
        if write:
            locked = await db.get(
                Reward, reward_id, with_for_update=True, populate_existing=True
            )
            if locked is None or locked.stock is None:
                continue
            before = locked.stock
            after = before + count
            status = locked.status
            if after > 0 and status == "sold_out":
                status = "active"
            locked.stock = after
            locked.status = status
            returned.append(
                StockReturn(
                    reward=locked.name, before=before, after=after, status=status
                )
            )
            continue
        reward = await db.get(Reward, reward_id)
        if reward is None or reward.stock is None:
            continue
        before = reward.stock
        after = before + count
        status = reward.status
        if after > 0 and status == "sold_out":
            status = "active"
        returned.append(
            StockReturn(reward=reward.name, before=before, after=after, status=status)
        )
    return returned
