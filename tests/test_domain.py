"""Domain tests: roles/scope, ledger, QR anti-fraud, redemptions."""

import pytest
from sqlalchemy import select

from app.models import PointsTransaction, Town, User
from app.security import create_access_token

pytestmark = pytest.mark.asyncio


async def _create_town(db_session, name="Malgrat de Mar"):
    town = Town(
        name=name,
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{name.lower().replace(' ', '')}.cat",
        manager_name="Admin",
    )
    db_session.add(town)
    await db_session.flush()
    return town


async def test_welcome_creates_ledger_entry(client, capture_otp):
    email = "resident1@test.cat"
    await client.post("/api/v1/auth/request-otp", json={"email": email})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code}
    )
    assert r.status_code == 200
    assert r.json()["user"]["points"] == 100
    assert r.json()["user"]["role"] == "resident"


async def test_admin_town_scope(client, db_session):
    town_a = await _create_town(db_session, "TownA")
    town_b = await _create_town(db_session, "TownB")
    admin = User(
        email="admin-a@test.cat",
        role="admin",
        town_id=town_a.id,
        name="Admin A",
        points=0,
    )
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token(
        admin.id, role="admin", town_id=town_a.id
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.get(f"/api/v1/towns/{town_a.id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "TownA"

    r = await client.get(f"/api/v1/towns/{town_b.id}", headers=headers)
    assert r.status_code == 403


async def test_shop_create_and_merchant_link(client, db_session, capture_otp):
    town = await _create_town(db_session)
    admin = User(
        email="admin-shop@test.cat",
        role="admin",
        town_id=town.id,
        points=0,
    )
    db_session.add(admin)
    await db_session.commit()

    admin_token = create_access_token(admin.id, role="admin", town_id=town.id)
    r = await client.post(
        "/api/v1/shops",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Fleca Nova",
            "contact_email": "fleca@test.cat",
            "categories": ["Fleca"],
            "visit_points": 15,
        },
    )
    assert r.status_code == 201, r.text
    shop = r.json()
    assert shop["status"] == "pending"

    await client.post("/api/v1/auth/request-otp", json={"email": "fleca@test.cat"})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "fleca@test.cat", "code": code},
    )
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "merchant"
    assert r.json()["user"]["shop_id"] == shop["id"]
    assert r.json()["user"]["points"] == 0  # no welcome for merchants


async def test_qr_scan_awards_points_once_per_day(
    client, db_session, capture_otp
):
    town = await _create_town(db_session)
    from app.models import Shop

    shop = Shop(
        town_id=town.id,
        name="Botiga",
        categories=[],
        contact_email="b@test.cat",
        visit_points=20,
        status="active",
        qr_code="TESTQRCODE",
    )
    db_session.add(shop)
    await db_session.commit()

    await client.post("/api/v1/auth/request-otp", json={"email": "scan@test.cat"})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": "scan@test.cat", "code": code}
    )
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    balance_before = r.json()["user"]["points"]

    r = await client.post(
        "/api/v1/scans", headers=headers, json={"qr_code": "TESTQRCODE"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["points"] == 20
    assert r.json()["balance"] == balance_before + 20

    r = await client.post(
        "/api/v1/scans", headers=headers, json={"qr_code": "TESTQRCODE"}
    )
    assert r.status_code == 409


async def test_redemption_debits_ledger_and_stock(
    client, db_session, capture_otp
):
    town = await _create_town(db_session)
    from app.models import Reward

    reward = Reward(
        town_id=town.id,
        name="Descompte",
        description="5e",
        type="discount",
        points_required=50,
        stock=2,
        status="active",
    )
    db_session.add(reward)
    await db_session.commit()

    await client.post("/api/v1/auth/request-otp", json={"email": "redeemer@test.cat"})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "redeemer@test.cat", "code": code},
    )
    token = r.json()["access_token"]
    # Link to town
    await client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"town_id": town.id},
    )

    r = await client.post(
        "/api/v1/redemptions",
        headers={"Authorization": f"Bearer {token}"},
        json={"reward_id": reward.id},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["flow"] == "voucher_qr"
    assert body["status"] == "pending_use"
    assert body["points_spent"] == 50

    me = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.json()["points"] == 50  # 100 welcome - 50

    await db_session.refresh(reward)
    assert reward.stock == 1
