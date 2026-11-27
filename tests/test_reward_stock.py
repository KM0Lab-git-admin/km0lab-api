"""Stock of a reward in one municipality (scripts/set_reward_stock)."""

import pytest

from app.catalog.rewards import sync_catalog_rewards
from app.models import Reward, User
from app.security import create_access_token
from app.services.reward_stock import StockRefused, set_reward_stock
from tests._municipalities import API, baix_montseny, catalog, malgrat, rewards_of

pytestmark = pytest.mark.asyncio


async def _two_municipalities(db):
    await catalog(db)
    mal = await malgrat(db)
    baix = await baix_montseny(db)
    await sync_catalog_rewards(db, town_id=mal.id)
    await sync_catalog_rewards(db, town_id=baix.id)
    await db.commit()
    return mal, baix


async def test_sets_the_stock_of_one_municipality_only(db_session):
    mal, baix = await _two_municipalities(db_session)
    before = (await rewards_of(db_session, baix))["Bono 50 €"].stock

    report = await set_reward_stock(
        db_session, town=mal, reward="Bono 50 €", stock=5
    )
    await db_session.commit()

    assert (report.old_stock, report.new_stock) == (before, 5)
    assert (await rewards_of(db_session, mal))["Bono 50 €"].stock == 5
    # The same reward in the other municipality, and the catalog, untouched.
    assert (await rewards_of(db_session, baix))["Bono 50 €"].stock == before
    # Points stay the catalog's.
    assert (await rewards_of(db_session, mal))["Bono 50 €"].points_required == 500


async def test_finds_the_reward_by_any_of_its_names(db_session):
    mal, _ = await _two_municipalities(db_session)
    cap = (await rewards_of(db_session, mal))["Gorra KM0 LAB"]
    cap.name_i18n = {"ca": "Gorra KM0 LAB", "es": "Gorra de KM0", "en": "KM0 cap"}
    await db_session.commit()

    for name in ("gorra km0 lab", "  Gorra de KM0 ", "KM0 CAP", cap.id):
        report = await set_reward_stock(
            db_session, town=mal, reward=name, stock=7
        )
        assert report.reward == "Gorra KM0 LAB"


async def test_zero_sells_out_and_topping_up_brings_it_back(client, db_session):
    mal, _ = await _two_municipalities(db_session)
    resident = User(
        email="veina@test.cat", slug="veina", postal_code="08380", points=5000
    )
    db_session.add(resident)
    await db_session.commit()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(resident.id, roles=["resident"])
    }
    bono = (await rewards_of(db_session, mal))["Bono 10 €"]

    report = await set_reward_stock(
        db_session, town=mal, reward="Bono 10 €", stock=0
    )
    await db_session.commit()
    assert (report.old_status, report.new_status) == ("active", "sold_out")
    r = await client.post(
        f"{API}/redemptions", json={"reward_id": bono.id}, headers=headers
    )
    assert r.status_code in (400, 404)

    report = await set_reward_stock(
        db_session, town=mal, reward="Bono 10 €", stock=1
    )
    await db_session.commit()
    assert (report.old_status, report.new_status) == ("sold_out", "active")
    r = await client.post(
        f"{API}/redemptions", json={"reward_id": bono.id}, headers=headers
    )
    assert r.status_code == 201, r.text
    # The cap holds: the only unit is gone.
    r = await client.post(
        f"{API}/redemptions", json={"reward_id": bono.id}, headers=headers
    )
    assert r.status_code in (400, 404)
    fresh = (await rewards_of(db_session, mal))["Bono 10 €"]
    assert (fresh.stock, fresh.status) == (0, "sold_out")


async def test_a_reward_the_admin_switched_off_stays_off(db_session):
    mal, _ = await _two_municipalities(db_session)
    cap = (await rewards_of(db_session, mal))["Gorra KM0 LAB"]
    cap.status = "inactive"
    await db_session.commit()

    report = await set_reward_stock(
        db_session, town=mal, reward="Gorra KM0 LAB", stock=20
    )

    assert (report.new_stock, report.new_status) == (20, "inactive")
    assert any("stays inactive" in line for line in report.lines())


async def test_refuses_instead_of_guessing(db_session):
    mal, _ = await _two_municipalities(db_session)
    demo_only = await catalog(db_session)

    with pytest.raises(StockRefused, match="no reward called"):
        await set_reward_stock(db_session, town=mal, reward="Bicicleta", stock=1)
    with pytest.raises(StockRefused, match="negative"):
        await set_reward_stock(db_session, town=mal, reward="Bono 10 €", stock=-1)
    # The catalog itself is not a municipality's stock.
    with pytest.raises(StockRefused, match="no rewards of its own"):
        await set_reward_stock(
            db_session, town=demo_only, reward="Bono 10 €", stock=1
        )

    # Two rewards with the same visible name: it asks for the id.
    db_session.add(
        Reward(
            town_id=mal.id,
            name="Bono 10 €",
            type="balance",
            points_required=100,
            status="active",
        )
    )
    await db_session.commit()
    with pytest.raises(StockRefused, match="several rewards"):
        await set_reward_stock(db_session, town=mal, reward="Bono 10 €", stock=1)
