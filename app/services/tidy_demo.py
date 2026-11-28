"""Make the demonstration presentable. Demo rows only.

Never touches a real municipality or an ``is_fake=False`` row. Shop
logos are not invented: that waits on a decision about which pictures
may be used. Hiding the administrator and the merchant from the
resident list would change a screen, so it is reported and left.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.rewards import upsert_demo_reward_images
from app.demo import (
    DEMO_ADMIN_EMAIL,
    DEMO_MERCHANT_EMAIL,
    DEMO_RESIDENT_EMAIL,
    DEMO_TOWN_SLUG,
)
from app.models import (
    PointsTransaction,
    Promotion,
    QrScan,
    Redemption,
    RedemptionEvent,
    Reward,
    Shop,
    Town,
    User,
)
from app.services.pilot_points import set_pilot_points
from app.services.points import apply_points
from app.services.voucher_codes import allocate_voucher_code

WELCOME = 50
SCAN = 100
TARGET_LOW = 250
TARGET_HIGH = 400


@dataclass
class TidyReport:
    changes: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        body = [f"change: {line}" for line in self.changes]
        body += [f"unchanged: {line}" for line in self.unchanged]
        body += [f"note: {line}" for line in self.notes]
        return body


def _test_shop(name: str) -> bool:
    plain = name.strip()
    if plain.upper().startswith("[DEMO]"):
        plain = plain[6:].strip()
    lowered = plain.lower()
    return lowered.startswith("test") or lowered.startswith("qa")


async def tidy_demo(db: AsyncSession, *, apply: bool) -> TidyReport:
    """Plan or write. Caller commits when ``apply`` is true."""
    report = TidyReport()
    demo = (
        await db.execute(select(Town).where(Town.slug == DEMO_TOWN_SLUG))
    ).scalars().first()
    if demo is None:
        report.notes.append("No está la población de demo. No se ha tocado nada.")
        return report

    await _hide_test_shops(db, demo.id, apply, report)
    pilot = await set_pilot_points(db, demo, apply=apply)
    for change in pilot.changes:
        report.changes.append(f"{change.what}: {change.before} -> {change.after}")
    if not pilot.changes:
        report.unchanged.append("acciones y puntos del piloto")

    await _resident_history(db, demo.id, apply, report)
    await _merchant_panel(db, demo.id, apply, report)
    await _reward_images(db, demo.id, apply, report)
    await _count_demo_mark(db, demo.id, report)
    report.notes.append(
        "Logotipos de comercios: saltado. Falta que Albert elija las "
        "imágenes (permiso de un comercio, propias, o un banco con licencia)."
    )
    report.notes.append(
        "Demo Admin y Demo Merchant siguen en la lista de vecinos: la lista "
        "enseña a quien es vecino. Ocultarlos cambia una pantalla y va al prototipo."
    )
    return report


async def _hide_test_shops(db, town_id: str, apply: bool, report: TidyReport) -> None:
    shops = list(
        (
            await db.execute(
                select(Shop).where(Shop.town_id == town_id, Shop.is_fake.is_(True))
            )
        ).scalars().all()
    )
    for shop in shops:
        if not _test_shop(shop.name):
            continue
        if shop.status == "inactive":
            report.unchanged.append(f"comercio de prueba ya oculto: {shop.name}")
            continue
        report.changes.append(f"ocultar comercio de prueba: {shop.name}")
        if apply:
            shop.status = "inactive"


async def _resident_history(db, town_id: str, apply: bool, report: TidyReport) -> None:
    resident = await _user(db, DEMO_RESIDENT_EMAIL)
    if resident is None or resident.town_id != town_id or not resident.is_fake:
        report.notes.append("El vecino de demo no está en la población de demo.")
        return
    txs = await _txs(db, resident.id)
    trial = [
        tx
        for tx in txs
        if tx.points == 1200 or "bono 5" in (tx.description or "").lower()
    ]
    if trial:
        report.changes.append(
            f"quitar {len(trial)} movimiento(s) de prueba del vecino de demo"
        )
        if apply:
            for tx in trial:
                resident.points -= tx.points
                await db.delete(tx)
            await db.flush()
    projected = (
        resident.points if apply else resident.points - sum(tx.points for tx in trial)
    )
    remaining = [tx for tx in txs if tx not in trial]
    if projected != 0 or remaining:
        report.unchanged.append(
            f"historial del vecino de demo ({resident.points} puntos)"
        )
        return

    shops = await _showcase_shops(db, town_id)
    merchant = await _user(db, DEMO_MERCHANT_EMAIL)
    if merchant is not None and merchant.shop_id:
        shops.sort(key=lambda shop: shop.id != merchant.shop_id)
    rewards = await _rewards(db, town_id)
    scan_n, reward = _story(len(shops), rewards)
    if scan_n == 0:
        report.notes.append(
            "El vecino de demo sigue a 0: no hay comercios de demo para escanear."
        )
        return
    final = WELCOME + SCAN * scan_n - (reward.points_required if reward else 0)
    label = (
        f"historial del vecino: +{WELCOME} y {scan_n} escaneos"
        + (f" y un canje de {reward.points_required}" if reward else " sin canje")
        + f" → {final} puntos"
    )
    report.changes.append(label)
    if reward is None:
        report.notes.append(
            "Ningún premio deja el saldo entre 250 y 400, así que no hay canje."
        )
    if not apply:
        return

    await apply_points(
        db,
        user=resident,
        points=WELCOME,
        type="welcome",
        town_id=town_id,
        ref_id=resident.id,
        description="Registre",
    )
    today = datetime.now(timezone.utc).date()
    for index, shop in enumerate(shops[:scan_n]):
        when = today - timedelta(days=scan_n - index)
        scan = QrScan(
            user_id=resident.id,
            shop_id=shop.id,
            points=SCAN,
            scan_date=when,
            is_fake=True,
        )
        db.add(scan)
        await db.flush()
        await apply_points(
            db,
            user=resident,
            points=SCAN,
            type="scan",
            town_id=town_id,
            ref_id=scan.id,
            description=shop.name,
        )
    if reward is not None:
        await _redeem(
            db,
            user=resident,
            reward=reward,
            town_id=town_id,
            shop_id=shops[0].id,
            when=datetime.now(timezone.utc),
        )


def _story(shop_count: int, rewards: list[Reward]) -> tuple[int, Reward | None]:
    """Three or four scans, then a redemption that lands in the range."""
    for scan_n in (4, 3):
        if shop_count < scan_n:
            continue
        base = WELCOME + SCAN * scan_n
        for reward in rewards:
            final = base - reward.points_required
            if TARGET_LOW <= final <= TARGET_HIGH:
                return scan_n, reward
    scan_n = min(4, shop_count)
    return scan_n, None


async def _merchant_panel(db, town_id: str, apply: bool, report: TidyReport) -> None:
    merchant = await _user(db, DEMO_MERCHANT_EMAIL)
    if merchant is None or not merchant.shop_id or not merchant.is_fake:
        report.notes.append("El comercio de demo no tiene tienda. Su panel no se ha sembrado.")
        return
    shop = await db.get(Shop, merchant.shop_id)
    if shop is None or shop.town_id != town_id or not shop.is_fake:
        report.notes.append("La tienda del comercio de demo no es de la demo.")
        return

    scans = int(
        await db.scalar(
            select(func.count()).select_from(QrScan).where(QrScan.shop_id == shop.id)
        )
        or 0
    )
    if scans >= 4:
        report.unchanged.append(f"visitas del comercio de demo ({scans})")
    else:
        visitors = await _other_residents(db, town_id, merchant.id)
        needed = min(4 - scans, len(visitors))
        if needed:
            report.changes.append(f"añadir {needed} visita(s) al comercio de demo")
            if apply:
                today = datetime.now(timezone.utc).date()
                for index, visitor in enumerate(visitors[:needed]):
                    await _scan(db, visitor, shop, town_id, today - timedelta(days=index + 1))
        if scans + needed < 4:
            report.notes.append(
                "No hay bastantes vecinos de demo para cuatro visitas del comercio."
            )

    used = int(
        await db.scalar(
            select(func.count())
            .select_from(Redemption)
            .where(
                Redemption.shop_id == shop.id,
                Redemption.status == "used",
                Redemption.is_fake.is_(True),
            )
        )
        or 0
    )
    reward = await _cheap_reward(db, town_id)
    if used >= 4:
        report.unchanged.append(f"vales validados del comercio de demo ({used})")
    elif reward is None:
        report.notes.append("No hay un premio de demo para los vales del comercio.")
    else:
        payers = [
            user
            for user in await _other_residents(db, town_id, merchant.id)
            if user.points >= reward.points_required
        ]
        adding = min(4 - used, len(payers))
        if adding:
            report.changes.append(f"añadir {adding} vale(s) validado(s)")
            if apply:
                for index, payer in enumerate(payers[:adding]):
                    await _redeem(
                        db,
                        user=payer,
                        reward=reward,
                        town_id=town_id,
                        shop_id=shop.id,
                        when=datetime.now(timezone.utc) - timedelta(days=index + 1),
                        code=await allocate_voucher_code(db),
                    )
        if used + adding < 4:
            report.notes.append(
                "No caben cuatro vales sin dejar a un vecino en negativo."
            )

    promos = list(
        (
            await db.execute(select(Promotion).where(Promotion.shop_id == shop.id))
        ).scalars().all()
    )
    if len(promos) >= 3:
        active = [p for p in promos if p.active]
        inactive = [p for p in promos if not p.active]
        if len(active) >= 2 and inactive:
            report.unchanged.append("tres promociones del comercio de demo")
        else:
            report.changes.append("dejar dos promociones activas y una apagada")
            if apply:
                ordered = promos[:3]
                for promo, flag in zip(ordered, (True, True, False)):
                    promo.active = flag
    else:
        report.changes.append(
            f"crear {3 - len(promos)} promoción(es); dos activas y una apagada"
        )
        if apply:
            titles = ("Pa del dia", "Cafe de mitja tarda", "Menú de nit")
            for index, title in enumerate(titles):
                if index < len(promos):
                    continue
                db.add(
                    Promotion(
                        shop_id=shop.id,
                        type="special_price",
                        title=title,
                        label="demo",
                        active=index < 2,
                        is_fake=True,
                    )
                )
            await db.flush()


async def _reward_images(db, town_id: str, apply: bool, report: TidyReport) -> None:
    missing_before = await _rewards_without_image(db, town_id)
    if not missing_before:
        report.unchanged.append("premios de demo con imagen")
        return
    if apply:
        await upsert_demo_reward_images(db, town_id=town_id)
    missing_after = missing_before if not apply else await _rewards_without_image(db, town_id)
    attached = [name for name in missing_before if name not in missing_after]
    if attached:
        report.changes.append("imagen en: " + ", ".join(attached))
    still = missing_after if apply else missing_before
    if still:
        report.notes.append(
            "Premios de demo sin imagen (no se inventa): " + ", ".join(still)
        )


async def _count_demo_mark(db, town_id: str, report: TidyReport) -> None:
    shops = list(
        (
            await db.execute(
                select(Shop.name).where(
                    Shop.town_id == town_id, Shop.is_fake.is_(True)
                )
            )
        ).scalars().all()
    )
    marked = [name for name in shops if "[DEMO]" in name.upper()]
    report.notes.append(
        f"{len(marked)} comercio(s) de demo llevan «[DEMO]» en el nombre. No se cambia."
    )


async def _scan(db, user: User, shop: Shop, town_id: str, when: date) -> None:
    row = QrScan(
        user_id=user.id,
        shop_id=shop.id,
        points=SCAN,
        scan_date=when,
        is_fake=True,
    )
    db.add(row)
    await db.flush()
    await apply_points(
        db,
        user=user,
        points=SCAN,
        type="scan",
        town_id=town_id,
        ref_id=row.id,
        description=shop.name,
    )


async def _redeem(
    db,
    *,
    user: User,
    reward: Reward,
    town_id: str,
    shop_id: str,
    when: datetime,
    code: str | None = None,
) -> None:
    redemption = Redemption(
        town_id=town_id,
        user_id=user.id,
        reward_id=reward.id,
        flow="voucher_qr",
        points_spent=reward.points_required,
        status="used",
        code=code,
        shop_id=shop_id,
        used_at=when,
        requested_at=when,
        is_fake=True,
    )
    db.add(redemption)
    await db.flush()
    db.add(
        RedemptionEvent(
            redemption_id=redemption.id,
            status="used",
            note="Validated",
            is_fake=True,
        )
    )
    await apply_points(
        db,
        user=user,
        points=-reward.points_required,
        type="redemption",
        town_id=town_id,
        ref_id=redemption.id,
        description=reward.name,
    )
    if reward.stock is not None:
        reward.stock = max(0, reward.stock - 1)
        if reward.stock == 0 and reward.status == "active":
            reward.status = "sold_out"


async def _user(db, email: str) -> User | None:
    return (
        await db.execute(select(User).where(func.lower(User.email) == email))
    ).scalars().first()


async def _txs(db, user_id: str) -> list[PointsTransaction]:
    return list(
        (
            await db.execute(
                select(PointsTransaction).where(PointsTransaction.user_id == user_id)
            )
        ).scalars().all()
    )


async def _showcase_shops(db, town_id: str) -> list[Shop]:
    rows = list(
        (
            await db.execute(
                select(Shop).where(
                    Shop.town_id == town_id,
                    Shop.is_fake.is_(True),
                    Shop.status == "active",
                )
            )
        ).scalars().all()
    )
    return [shop for shop in rows if not _test_shop(shop.name)]


async def _rewards(db, town_id: str) -> list[Reward]:
    rows = list(
        (
            await db.execute(
                select(Reward)
                .where(
                    Reward.town_id == town_id,
                    Reward.is_fake.is_(True),
                    Reward.status == "active",
                    Reward.points_required > 0,
                )
                .order_by(Reward.points_required)
            )
        ).scalars().all()
    )
    return rows


async def _cheap_reward(db, town_id: str) -> Reward | None:
    rows = await _rewards(db, town_id)
    return rows[0] if rows else None


async def _other_residents(db, town_id: str, merchant_id: str) -> list[User]:
    rows = list(
        (
            await db.execute(
                select(User).where(
                    User.is_fake.is_(True),
                    User.is_resident.is_(True),
                    User.id != merchant_id,
                    User.email.notin_(
                        [DEMO_RESIDENT_EMAIL, DEMO_ADMIN_EMAIL, DEMO_MERCHANT_EMAIL]
                    ),
                )
            )
        ).scalars().all()
    )
    return [user for user in rows if user.town_id == town_id]


async def _rewards_without_image(db, town_id: str) -> list[str]:
    from app.models import RewardMedia

    rows = list(
        (
            await db.execute(
                select(Reward).where(
                    Reward.town_id == town_id, Reward.is_fake.is_(True)
                )
            )
        ).scalars().all()
    )
    missing = []
    for reward in rows:
        media = await db.scalar(
            select(func.count())
            .select_from(RewardMedia)
            .where(RewardMedia.reward_id == reward.id)
        )
        if not media and not reward.image_url:
            missing.append(reward.name)
    return missing
