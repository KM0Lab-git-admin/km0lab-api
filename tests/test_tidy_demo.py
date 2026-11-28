"""The demonstration tidy touches demo rows and leaves a real town alone."""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.demo import DEMO_MERCHANT_EMAIL, DEMO_RESIDENT_EMAIL
from app.models import PointsTransaction, Promotion, QrScan, Redemption, Reward, Shop, User
from app.roles import flags_from_roles
from app.services.tidy_demo import tidy_demo
from app.services.towns import ensure_demo_town
from tests._municipalities import single_town

pytestmark = pytest.mark.asyncio


async def _person(db, email: str, postal: str, **flags) -> User:
    user = User(
        email=email,
        slug=email.split("@")[0].replace("+", "-"),
        postal_code=postal,
        points=0,
        is_fake=True,
        **flags_from_roles(flags.get("roles", ["resident"])),
    )
    db.add(user)
    await db.flush()
    return user


async def _shop(db, town_id: str, name: str, *, fake: bool) -> Shop:
    shop = Shop(
        town_id=town_id,
        name=name,
        status="active",
        is_fake=fake,
        visit_points=100,
    )
    db.add(shop)
    await db.flush()
    return shop


async def test_apply_tidies_the_demo_and_a_second_pass_is_quiet(db_session):
    demo = await ensure_demo_town(db_session)
    real = await single_town(db_session, "Tordera", "08490")
    real_shop = await _shop(db_session, real.id, "Test Forn", fake=False)
    test_shop = await _shop(db_session, demo.id, "Test Comerc 191416", fake=True)
    passerby = await _person(db_session, "passada@km0lab.com", "00000")
    db_session.add(
        QrScan(
            user_id=passerby.id,
            shop_id=test_shop.id,
            points=10,
            scan_date=date.today(),
            is_fake=True,
        )
    )
    merchant_shop = await _shop(db_session, demo.id, "[DEMO] Fleca del Port", fake=True)
    await _shop(db_session, demo.id, "[DEMO] Cafè", fake=True)
    await _shop(db_session, demo.id, "[DEMO] Peix", fake=True)
    await _shop(db_session, demo.id, "[DEMO] Fruita", fake=True)
    resident = await _person(db_session, DEMO_RESIDENT_EMAIL, "00000")
    resident.points = 1200
    db_session.add(
        PointsTransaction(
            user_id=resident.id,
            town_id=demo.id,
            type="adjustment",
            points=1200,
            description="prova",
            is_fake=True,
        )
    )
    reward = Reward(
        town_id=demo.id,
        name="Pa de pagès",
        type="product",
        points_required=100,
        status="active",
        is_fake=True,
    )
    db_session.add(reward)
    merchant = await _person(
        db_session, DEMO_MERCHANT_EMAIL, "00000", roles=["resident", "merchant"]
    )
    merchant.shop_id = merchant_shop.id
    for n in range(3):
        await _person(db_session, f"veci{n}@km0lab.com", "00000")
    await db_session.commit()

    test_shop_id = test_shop.id
    real_shop_id = real_shop.id
    resident_id = resident.id
    merchant_shop_id = merchant_shop.id
    preview = await tidy_demo(db_session, apply=False)
    await db_session.rollback()
    assert any("ocultar" in line for line in preview.changes)
    assert (
        await db_session.scalar(select(Shop.status).where(Shop.id == test_shop_id))
        == "active"
    )
    assert (
        await db_session.scalar(select(User.points).where(User.id == resident_id))
        == 1200
    )

    done = await tidy_demo(db_session, apply=True)
    await db_session.commit()
    assert any("Logotipos" in line for line in done.notes)
    assert any("[DEMO]" in line for line in done.notes)
    assert any("prototipo" in line for line in done.notes)

    assert (
        await db_session.scalar(select(Shop.status).where(Shop.id == test_shop_id))
        == "inactive"
    )
    assert (
        await db_session.scalar(select(Shop.status).where(Shop.id == real_shop_id))
        == "active"
    )
    balance = await db_session.scalar(select(User.points).where(User.id == resident_id))
    assert 250 <= balance <= 400
    scans = await db_session.scalar(
        select(func.count()).select_from(QrScan).where(QrScan.user_id == resident_id)
    )
    assert scans in (3, 4)
    redemptions = await db_session.scalar(
        select(func.count())
        .select_from(Redemption)
        .where(Redemption.user_id == resident_id)
    )
    assert redemptions == 1
    trial = await db_session.scalar(
        select(func.count())
        .select_from(PointsTransaction)
        .where(
            PointsTransaction.user_id == resident_id,
            PointsTransaction.points == 1200,
        )
    )
    assert trial == 0
    # The scan that belonged to the hidden shop is still there.
    kept = await db_session.scalar(
        select(func.count()).select_from(QrScan).where(QrScan.shop_id == test_shop_id)
    )
    assert kept == 1
    active_promos = await db_session.scalar(
        select(func.count())
        .select_from(Promotion)
        .where(Promotion.shop_id == merchant_shop_id, Promotion.active.is_(True))
    )
    inactive_promos = await db_session.scalar(
        select(func.count())
        .select_from(Promotion)
        .where(Promotion.shop_id == merchant_shop_id, Promotion.active.is_(False))
    )
    assert active_promos == 2
    assert inactive_promos == 1
    used = await db_session.scalar(
        select(func.count())
        .select_from(Redemption)
        .where(Redemption.shop_id == merchant_shop_id, Redemption.status == "used")
    )
    assert used == 4

    again = await tidy_demo(db_session, apply=True)
    assert again.changes == []


async def test_apply_allocates_a_code_when_the_fixed_one_is_taken(db_session):
    demo = await ensure_demo_town(db_session)
    shop = await _shop(db_session, demo.id, "[DEMO] Fleca", fake=True)
    merchant = await _person(
        db_session, DEMO_MERCHANT_EMAIL, "00000", roles=["resident", "merchant"]
    )
    merchant.shop_id = shop.id
    reward = Reward(
        town_id=demo.id,
        name="Pa",
        type="product",
        points_required=10,
        status="active",
        is_fake=True,
    )
    db_session.add(reward)
    await db_session.flush()
    holder = await _person(db_session, "ocupa@km0lab.com", "00000")
    db_session.add(
        Redemption(
            town_id=demo.id,
            user_id=holder.id,
            reward_id=reward.id,
            flow="voucher_qr",
            points_spent=10,
            status="used",
            code="80000",
            is_fake=True,
        )
    )
    for n in range(4):
        payer = await _person(db_session, f"pagador{n}@km0lab.com", "00000")
        payer.points = 100
    await db_session.commit()

    done = await tidy_demo(db_session, apply=True)
    await db_session.commit()
    assert any("vale" in line for line in done.changes)
    codes = (
        await db_session.execute(
            select(Redemption.code).where(Redemption.shop_id == shop.id)
        )
    ).scalars().all()
    assert len(codes) == 4
    assert len(set(codes)) == 4
    assert "80000" not in codes
