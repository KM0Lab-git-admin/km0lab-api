"""The points of the pilot (``app/services/pilot_points.py``)."""

import pytest
from sqlalchemy import select

from app.catalog.point_actions import ensure_town_point_actions
from app.models import PointAction, Reward, Shop, Town
from app.services.pilot_points import (
    euros_of,
    pilot_towns,
    reward_points_for,
    set_pilot_points,
)
from app.services.qa_territory import ensure_qa_territory
from tests._municipalities import API, catalog, malgrat

pytestmark = pytest.mark.asyncio


async def _malgrat_as_today(db) -> Town:
    """A municipality as they are before the pilot: default actions, a shop
    and rewards on the old scale (10 points per euro)."""
    town = await malgrat(db)
    await ensure_town_point_actions(db, town.id, is_fake=False)
    db.add(
        Shop(
            town_id=town.id,
            name="Forn",
            contact_email="forn@test.cat",
            visit_points=15,
            status="active",
        )
    )
    for name, type_, points, value in (
        ("Bono 5 €", "balance", 50, "5€"),
        ("Bono 50 €", "balance", 500, "50 €"),
        ("Samarreta KM0 LAB", "merchandise", 300, None),
        ("10% de descompte", "discount", 1000, "10%"),
        ("Gorra KM0 LAB", "merchandise", 180, "1 unitat"),
        ("Bossa de regal de KMLab super chula de la muerte", "merchandise", 120, None),
        ("Pa de pagès", "product", 60, None),
    ):
        db.add(
            Reward(
                town_id=town.id,
                name=name,
                type=type_,
                points_required=points,
                value=value,
            )
        )
    await db.commit()
    return town


async def _actions(db, town: Town) -> dict[str, PointAction]:
    rows = (
        await db.execute(
            select(PointAction)
            .where(PointAction.town_id == town.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return {a.type: a for a in rows}


async def _rewards(db, town: Town) -> dict[str, int]:
    rows = (
        await db.execute(
            select(Reward)
            .where(Reward.town_id == town.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return {r.name: r.points_required for r in rows}


def test_price_of_a_reward():
    assert euros_of("5€") == 5 and euros_of(" 12,50 € ") == 12.5
    assert euros_of("10%") is None and euros_of("500 ml") is None
    assert euros_of(None) is None
    assert reward_points_for("[DEMO] Bono 20 €", "20€") == 2000
    assert reward_points_for("[DEMO] Samarreta KM0 LAB", None) == 1000
    assert reward_points_for("[DEMO] Gorra KM0 LAB", "1 unitat") == 1800
    assert reward_points_for("Pa de pagès", None) is None


async def test_rehearsal_reports_and_touches_nothing(db_session):
    town = await _malgrat_as_today(db_session)

    report = await set_pilot_points(db_session, town, apply=False)
    await db_session.rollback()

    assert report.changes and not db_session.dirty
    await db_session.refresh(town)
    assert town.default_visit_points == 15
    assert (await _actions(db_session, town))["signup"].points == 100
    assert (await _rewards(db_session, town))["Bono 5 €"] == 50


async def test_three_ways_to_earn_and_one_scale(db_session):
    town = await _malgrat_as_today(db_session)

    report = await set_pilot_points(db_session, town, apply=True)
    await db_session.commit()

    await db_session.refresh(town)
    assert (town.default_visit_points, town.points_per_euro) == (100, 100)
    actions = await _actions(db_session, town)
    earning = {t: a.points for t, a in actions.items() if a.active}
    assert earning == {"signup": 50, "qr_scan": 100, "invite_person": 50}
    assert not actions["birthday"].active and not actions["invite_business"].active
    # Each shop pays a resident once: a year, longer than the pilot.
    assert actions["qr_scan"].cooldown_days == 365 == report.scan_cooldown_days

    shop = (await db_session.execute(select(Shop))).scalars().one()
    await db_session.refresh(shop)
    assert shop.visit_points == 100

    assert await _rewards(db_session, town) == {
        "Bono 5 €": 500,
        "Bono 50 €": 5000,
        "Samarreta KM0 LAB": 1000,
        "Gorra KM0 LAB": 1800,
        # The test name is gone, and the bag has its price.
        "Bossa KM0 LAB": 1200,
        # A discount in percent keeps its points and is switched off.
        "10% de descompte": 1000,
        # Covered by no rule: untouched, and said so.
        "Pa de pagès": 60,
    }
    assert {u.name for u in report.undecided} == {"Pa de pagès"}
    rows = (
        await db_session.execute(
            select(Reward).execution_options(populate_existing=True)
        )
    ).scalars().all()
    status = {r.name: r.status for r in rows}
    assert status["10% de descompte"] == "inactive"
    assert status["Bossa KM0 LAB"] == status["Bono 5 €"] == "active"
    bag = next(r for r in rows if r.name == "Bossa KM0 LAB")
    assert bag.name_i18n == {
        "ca": "Bossa KM0 LAB",
        "es": "Bolsa KM0 LAB",
        "en": "KM0 LAB bag",
    }


async def test_running_it_again_changes_nothing(db_session):
    town = await _malgrat_as_today(db_session)
    await set_pilot_points(db_session, town, apply=True)
    await db_session.commit()

    again = await set_pilot_points(db_session, town, apply=True)
    await db_session.commit()

    assert again.changes == []
    assert (await _rewards(db_session, town))["Bono 5 €"] == 500


async def test_a_municipality_without_the_action_gets_it(db_session):
    """Without its row an invitation would pay the 100 of the settings."""
    town = await malgrat(db_session)
    await db_session.commit()

    await set_pilot_points(db_session, town, apply=True)
    await db_session.commit()

    actions = await _actions(db_session, town)
    assert {t: a.points for t, a in actions.items()} == {
        "signup": 50,
        "qr_scan": 100,
        "invite_person": 50,
    }


async def test_the_app_is_paid_what_the_script_set(client, db_session, capture_otp):
    town = await _malgrat_as_today(db_session)
    await set_pilot_points(db_session, town, apply=True)
    await db_session.commit()

    await client.post(f"{API}/auth/request-otp", json={"email": "nova@test.cat"})
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": "nova@test.cat", "code": capture_otp(), "postal_code": "08380"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["points"] == 50
    assert r.json()["points_awarded"] == 50


async def test_demo_is_included_and_the_qa_territory_is_not(db_session):
    await malgrat(db_session)
    demo = await catalog(db_session)
    await ensure_qa_territory(db_session)
    await db_session.commit()

    towns = await pilot_towns(db_session)
    assert {t.name for t in towns} == {"Malgrat de Mar", demo.name}

    report = await set_pilot_points(db_session, demo, apply=True)
    await db_session.commit()
    prices = await _rewards(db_session, demo)
    assert prices["[DEMO] Bono 5 €"] == 500
    assert prices["[DEMO] Samarreta KM0 LAB"] == 1000
    assert prices["[DEMO] Gorra KM0 LAB"] == 1800
    assert prices["[DEMO] Entrada de cinema"] == 2000
    # In the catalog itself nothing is "own": it is the catalog.
    assert not any(u.own for u in report.undecided)
