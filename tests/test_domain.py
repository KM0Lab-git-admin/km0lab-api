"""Domain tests: multi-role, postal→town, ledger, QR, redemptions."""

import pytest

from app.models import Reward, Shop, Town, TownPostalCode, User
from app.roles import IncompatibleRolesError, flags_from_roles, normalize_roles
from app.security import create_access_token
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio


async def _create_town(db_session, name="Malgrat de Mar", postal_code="08380"):
    town = Town(
        name=name,
        slug=slugify(name),
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{name.lower().replace(' ', '')}.cat",
        manager_name="Admin",
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(
            postal_code=postal_code,
            town_id=town.id,
            is_primary=True,
        )
    )
    await db_session.flush()
    return town, postal_code


async def test_admin_and_merchant_incompatible():
    with pytest.raises(IncompatibleRolesError):
        normalize_roles(["admin", "merchant"])


async def test_welcome_creates_ledger_entry(client, capture_otp):
    email = "resident1@test.cat"
    await client.post("/api/v1/auth/request-otp", json={"email": email})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code}
    )
    assert r.status_code == 200
    assert r.json()["user"]["points"] == 100
    assert r.json()["user"]["roles"] == ["resident"]


async def test_admin_town_scope(client, db_session):
    town_a, cp_a = await _create_town(db_session, "TownA", "08001")
    town_b, _ = await _create_town(db_session, "TownB", "08002")
    admin = User(
        email="admin-a@test.cat",
        slug="admin-a",
        postal_code=cp_a,
        first_name="Admin",
        last_name="A",
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town_a.id
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.get(f"/api/v1/towns/{town_a.id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "TownA"
    assert any(p["postal_code"] == cp_a for p in r.json()["postal_codes"])

    r = await client.get(f"/api/v1/towns/{town_b.id}", headers=headers)
    assert r.status_code == 403


async def test_postal_code_sets_town_name(client, db_session, capture_otp):
    town, cp = await _create_town(db_session, "Malgrat de Mar", "08380")
    await db_session.commit()

    await client.post("/api/v1/auth/request-otp", json={"email": "cp@test.cat"})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": "cp@test.cat", "code": code}
    )
    token = r.json()["access_token"]
    r = await client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"postal_code": cp},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["postal_code"] == cp
    assert body["town_id"] == town.id
    assert body["town_name"] == "Malgrat de Mar"


async def test_admin_can_use_resident_endpoints(client, db_session, capture_otp):
    town, cp = await _create_town(db_session, postal_code="08381")
    shop = Shop(
        town_id=town.id,
        name="Botiga",
        categories=[],
        contact_email="b@test.cat",
        visit_points=10,
        status="active",
        qr_code="ADMINSCAN",
    )
    admin = User(
        email="admin-app@test.cat",
        slug="admin-app",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add_all([shop, admin])
    await db_session.commit()

    await client.post(
        "/api/v1/auth/request-otp", json={"email": "admin-app@test.cat"}
    )
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "admin-app@test.cat", "code": code},
    )
    assert r.status_code == 200
    assert set(r.json()["user"]["roles"]) == {"admin", "resident"}
    token = r.json()["access_token"]

    r = await client.post(
        "/api/v1/scans",
        headers={"Authorization": f"Bearer {token}"},
        json={"qr_code": "ADMINSCAN"},
    )
    assert r.status_code == 201, r.text


async def test_shop_create_and_merchant_link(client, db_session, capture_otp):
    town, cp = await _create_town(db_session, postal_code="08382")
    admin = User(
        email="admin-shop@test.cat",
        slug="admin-shop",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()

    admin_token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    r = await client.post(
        "/api/v1/shops",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Fleca Nova",
            "contact_email": "fleca@test.cat",
            "categories": ["bakery"],
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
    assert set(r.json()["user"]["roles"]) == {"resident", "merchant"}
    assert r.json()["user"]["shop_id"] == shop["id"]
    assert r.json()["user"]["town_id"] == town.id
    assert r.json()["user"]["postal_code"] == cp
    assert r.json()["user"]["points"] == 100


async def test_existing_resident_becomes_merchant(
    client, db_session, capture_otp
):
    town, cp = await _create_town(db_session, postal_code="08383")
    email = "dual@test.cat"

    await client.post("/api/v1/auth/request-otp", json={"email": email})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code}
    )
    assert r.json()["user"]["roles"] == ["resident"]
    assert r.json()["user"]["points"] == 100

    admin = User(
        email="admin-dual@test.cat",
        slug="admin-dual",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()
    admin_token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    r = await client.post(
        "/api/v1/shops",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Dual Shop",
            "contact_email": email,
            "categories": ["cafe"],
            "visit_points": 10,
        },
    )
    assert r.status_code == 201
    shop_id = r.json()["id"]

    await client.post("/api/v1/auth/request-otp", json={"email": email})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code}
    )
    assert r.status_code == 200
    body = r.json()["user"]
    assert set(body["roles"]) == {"resident", "merchant"}
    assert body["shop_id"] == shop_id
    assert body["points"] == 100


async def test_qr_scan_awards_points_with_cooldown(
    client, db_session, capture_otp
):
    from app.models import PointAction

    town, _ = await _create_town(db_session, postal_code="08384")
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
    db_session.add(
        PointAction(
            town_id=town.id,
            type="qr_scan",
            name="Visita comerç",
            description="Punts per escaneig",
            points=100,
            cooldown_days=90,
            active=True,
            is_fake=False,
        )
    )
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
    body = r.json()
    assert body["points"] == 100
    assert body["shop_name"] == "Botiga"
    assert body["balance"] == balance_before + 100
    assert body["available_at"]

    r = await client.post(
        "/api/v1/scans", headers=headers, json={"qr_code": "TESTQRCODE"}
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "qr_cooldown"
    assert detail["shop_name"] == "Botiga"
    assert detail["available_at"]
    assert detail["cooldown_days"] == 90


async def test_redemption_debits_ledger_and_stock(
    client, db_session, capture_otp
):
    town, cp = await _create_town(db_session, postal_code="08385")
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
    await client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"postal_code": cp},
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
    assert me.json()["points"] == 50

    await db_session.refresh(reward)
    assert reward.stock == 1


async def test_points_history_balance_and_filters(
    client, db_session, capture_otp
):
    from app.models import PointAction

    town, _ = await _create_town(db_session, postal_code="08386")
    shop = Shop(
        town_id=town.id,
        name="Forn Test",
        categories=[],
        contact_email="forn@test.cat",
        visit_points=20,
        status="active",
        qr_code="HISTQR",
    )
    db_session.add(shop)
    db_session.add(
        PointAction(
            town_id=town.id,
            type="qr_scan",
            name="Escaneig d'un comerç",
            description="Visita",
            points=20,
            cooldown_days=1,
            active=True,
            is_fake=False,
        )
    )
    reward = Reward(
        town_id=town.id,
        name="Val 5€",
        description="Cafè",
        type="discount",
        points_required=50,
        stock=5,
        status="active",
    )
    db_session.add(reward)
    await db_session.commit()

    await client.post("/api/v1/auth/request-otp", json={"email": "hist@test.cat"})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": "hist@test.cat", "code": code}
    )
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        "/api/v1/scans", headers=headers, json={"qr_code": "HISTQR"}
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id},
    )
    assert r.status_code == 201, r.text

    r = await client.get("/api/v1/points/me/history", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # welcome 100 + scan 20 - redemption 50 = 70
    assert body["balance"] == 70
    assert body["earned_total"] == 120
    assert body["spent_total"] == 50
    assert len(body["items"]) >= 3
    types = {i["type"] for i in body["items"]}
    assert "welcome" in types
    assert "scan" in types
    assert "redemption" in types
    scan_item = next(i for i in body["items"] if i["type"] == "scan")
    assert scan_item["shop_name"] == "Forn Test"
    assert scan_item["points"] == 20
    red_item = next(i for i in body["items"] if i["type"] == "redemption")
    assert red_item["reward_name"] == "Val 5€"
    assert red_item["points"] == -50

    r = await client.get(
        "/api/v1/points/me/history",
        headers=headers,
        params={"filter": "earned"},
    )
    assert r.status_code == 200
    assert all(i["points"] > 0 for i in r.json()["items"])
    assert r.json()["balance"] == 70  # totals/balance always global

    r = await client.get(
        "/api/v1/points/me/history",
        headers=headers,
        params={"filter": "spent"},
    )
    assert r.status_code == 200
    assert all(i["points"] < 0 for i in r.json()["items"])


async def test_shop_payment_settles_used_vouchers(
    client, db_session, capture_otp
):
    town, cp = await _create_town(db_session, postal_code="08387")
    shop = Shop(
        town_id=town.id,
        name="Cafè del Port",
        categories=[],
        contact_email="cafe-pay@test.cat",
        visit_points=10,
        status="active",
        qr_code="PAYQR",
    )
    reward = Reward(
        town_id=town.id,
        name="Val 10€",
        description="Saldo de 10€",
        type="balance",
        points_required=100,
        value="10€",
        status="active",
    )
    db_session.add_all([shop, reward])
    await db_session.flush()
    admin = User(
        email="admin-pay@test.cat",
        slug="admin-pay",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    merchant = User(
        email="merchant-pay@test.cat",
        slug="merchant-pay",
        postal_code=cp,
        shop_id=shop.id,
        points=0,
        **flags_from_roles(["merchant", "resident"]),
    )
    db_session.add_all([admin, merchant])
    await db_session.commit()

    # Resident redeems a balance voucher.
    await client.post("/api/v1/auth/request-otp", json={"email": "payer@test.cat"})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": "payer@test.cat", "code": code}
    )
    resident_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await client.patch(
        "/api/v1/users/me", headers=resident_headers, json={"postal_code": cp}
    )
    r = await client.post(
        "/api/v1/redemptions",
        headers=resident_headers,
        json={"reward_id": reward.id, "amount": "10€"},
    )
    assert r.status_code == 201, r.text
    redemption_id = r.json()["id"]
    assert r.json()["payment_id"] is None
    voucher_code = r.json()["code"]
    assert voucher_code and len(voucher_code) == 5 and voucher_code.isdigit()

    # Merchant marks the voucher as used.
    merchant_token = create_access_token(
        merchant.id, roles=["merchant", "resident"], town_id=town.id
    )
    r = await client.post(
        f"/api/v1/redemptions/{redemption_id}/use",
        headers={"Authorization": f"Bearer {merchant_token}"},
        json={"amount_applied": "10€"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "used"

    admin_token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Debt shows up aggregated per shop.
    r = await client.get("/api/v1/payments/debts", headers=admin_headers)
    assert r.status_code == 200, r.text
    debts = r.json()
    assert len(debts) == 1
    assert debts[0]["shop_id"] == shop.id
    assert debts[0]["pending_count"] == 1
    assert debts[0]["pending_amount"] == 10.0
    assert debts[0]["paid_total"] == 0.0

    # Admin settles the voucher.
    r = await client.post(
        "/api/v1/payments",
        headers=admin_headers,
        json={
            "shop_id": shop.id,
            "redemption_ids": [redemption_id],
            "note": "Liquidació de prova",
        },
    )
    assert r.status_code == 201, r.text
    payment = r.json()
    assert payment["total_amount"] == 10.0
    assert payment["redemption_ids"] == [redemption_id]
    assert payment["shop_name"] == "Cafè del Port"

    # Paying twice is rejected.
    r = await client.post(
        "/api/v1/payments",
        headers=admin_headers,
        json={"shop_id": shop.id, "redemption_ids": [redemption_id]},
    )
    assert r.status_code == 400

    # Debts reflect the settlement and the voucher carries payment_id.
    r = await client.get("/api/v1/payments/debts", headers=admin_headers)
    debts = r.json()
    assert debts[0]["pending_count"] == 0
    assert debts[0]["pending_amount"] == 0.0
    assert debts[0]["paid_total"] == 10.0

    r = await client.get("/api/v1/redemptions", headers=admin_headers)
    match = next(x for x in r.json() if x["id"] == redemption_id)
    assert match["payment_id"] == payment["id"]

    r = await client.get("/api/v1/payments", headers=admin_headers)
    assert len(r.json()) == 1
    assert r.json()[0]["redemption_ids"] == [redemption_id]


async def test_merchant_validates_voucher_by_code(client, db_session, capture_otp):
    town, cp = await _create_town(db_session, postal_code="08388")
    shop = Shop(
        town_id=town.id,
        name="Fleca Validate",
        categories=[],
        contact_email="fleca-val@test.cat",
        visit_points=10,
        status="active",
        qr_code="VALQR",
    )
    reward = Reward(
        town_id=town.id,
        name="Bono 5€",
        description="Saldo",
        type="balance",
        points_required=50,
        value="5€",
        status="active",
    )
    db_session.add_all([shop, reward])
    await db_session.flush()
    merchant = User(
        email="merchant-val@test.cat",
        slug="merchant-val",
        postal_code=cp,
        shop_id=shop.id,
        points=0,
        **flags_from_roles(["merchant", "resident"]),
    )
    db_session.add(merchant)
    await db_session.commit()

    await client.post("/api/v1/auth/request-otp", json={"email": "val-user@test.cat"})
    otp = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "val-user@test.cat", "code": otp},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await client.patch(
        "/api/v1/users/me", headers=headers, json={"postal_code": cp}
    )
    r = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id, "amount": "5€"},
    )
    assert r.status_code == 201, r.text
    voucher_code = r.json()["code"]
    assert voucher_code and len(voucher_code) == 5
    assert r.json()["status"] == "pending_use"
    assert r.json()["shop_id"] is None

    merchant_token = create_access_token(
        merchant.id, roles=["merchant", "resident"], town_id=town.id
    )
    m_headers = {"Authorization": f"Bearer {merchant_token}"}

    r = await client.post(
        "/api/v1/redemptions/validate",
        headers=m_headers,
        json={"code": voucher_code},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "used"
    assert body["shop_id"] == shop.id
    assert body["amount_applied"] == "5€"
    assert body["code"] == voucher_code

    # Second validate fails as already used.
    r = await client.post(
        "/api/v1/redemptions/validate",
        headers=m_headers,
        json={"code": voucher_code},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "already_used"

    r = await client.post(
        "/api/v1/redemptions/validate",
        headers=m_headers,
        json={"code": "99999"},
    )
    assert r.status_code == 404
