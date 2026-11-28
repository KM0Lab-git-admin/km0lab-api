"""A physical prize may name the shop where it will be picked up."""

import pytest

from app.models import Reward, Shop, Town, TownPostalCode
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio


async def _town(db, name: str, postal: str):
    town = Town(
        name=name,
        slug=slugify(name),
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{postal}.cat",
        manager_name="Admin",
    )
    db.add(town)
    await db.flush()
    db.add(TownPostalCode(postal_code=postal, town_id=town.id, is_primary=True))
    await db.flush()
    return town, postal


def _shop(town, name: str, *, status: str = "active", is_fake: bool = False, address: str = "Carrer 1"):
    return Shop(
        town_id=town.id,
        name=name,
        categories=[],
        contact_email=f"{slugify(name)}@test.cat",
        visit_points=10,
        status=status,
        address=address,
        qr_code=slugify(name)[:12],
        is_fake=is_fake,
    )


def _reward(town, *, kind: str):
    return Reward(
        town_id=town.id,
        name="Samarreta" if kind == "merchandise" else "Val",
        description="d",
        type=kind,
        points_required=40,
        value="1",
        status="active",
        stock=2,
    )


async def _resident(client, capture_otp, email: str, postal: str) -> dict:
    await client.post("/api/v1/auth/request-otp", json={"email": email})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await client.patch(
        "/api/v1/users/me", headers=headers, json={"postal_code": postal}
    )
    return headers


async def test_a_shop_from_another_town_is_refused(client, db_session, capture_otp):
    town, postal = await _town(db_session, "Blanes", "17300")
    other, _ = await _town(db_session, "Pineda", "08397")
    reward = _reward(town, kind="merchandise")
    shop = _shop(other, "Botiga de Pineda")
    db_session.add_all([reward, shop])
    await db_session.commit()
    headers = await _resident(client, capture_otp, "vei-blanes-pickup@test.cat", postal)

    created = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id, "shop_id": shop.id},
    )
    assert created.status_code == 422
    assert created.json()["detail"] == "invalid_pickup_shop"


async def test_an_inactive_shop_is_refused(client, db_session, capture_otp):
    town, postal = await _town(db_session, "Calella", "08370")
    reward = _reward(town, kind="merchandise")
    shop = _shop(town, "Forn tancat", status="inactive")
    db_session.add_all([reward, shop])
    await db_session.commit()
    headers = await _resident(client, capture_otp, "vei-calella-pickup@test.cat", postal)

    created = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id, "shop_id": shop.id},
    )
    assert created.status_code == 422
    assert created.json()["detail"] == "invalid_pickup_shop"


async def test_a_voucher_drops_the_shop(client, db_session, capture_otp):
    town, postal = await _town(db_session, "Malgrat", "08380")
    reward = _reward(town, kind="discount")
    shop = _shop(town, "Forn del port")
    db_session.add_all([reward, shop])
    await db_session.commit()
    headers = await _resident(client, capture_otp, "vei-malgrat-vale@test.cat", postal)

    created = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id, "shop_id": shop.id, "amount": "5€"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["shop_id"] is None
    assert body["shop_name"] is None


async def test_a_delivery_keeps_a_shop_of_the_same_town(client, db_session, capture_otp):
    town, postal = await _town(db_session, "Tordera", "08490")
    reward = _reward(town, kind="merchandise")
    shop = _shop(town, "Cal Sastre", address="Carrer Major 4")
    db_session.add_all([reward, shop])
    await db_session.commit()
    headers = await _resident(client, capture_otp, "vei-tordera@test.cat", postal)

    created = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id, "shop_id": shop.id},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["shop_id"] == shop.id
    assert body["shop_name"] == "Cal Sastre"
    assert body["shop_address"] == "Carrer Major 4"
    listed = await client.get("/api/v1/redemptions", headers=headers)
    assert listed.json()[0]["shop_name"] == "Cal Sastre"


async def test_a_delivery_without_a_shop_stays_as_before(client, db_session, capture_otp):
    town, postal = await _town(db_session, "Blanes Nord", "17301")
    reward = _reward(town, kind="merchandise")
    db_session.add(reward)
    await db_session.commit()
    headers = await _resident(client, capture_otp, "vei-blanes-nord@test.cat", postal)

    created = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id},
    )
    assert created.status_code == 201, created.text
    assert created.json()["shop_id"] is None
    assert created.json()["status"] == "requested"
