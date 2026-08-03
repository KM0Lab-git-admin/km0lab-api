"""GET /shops/for-me — resident catalog with per-user scan status."""

from datetime import date

import pytest

from app.models import QrScan, Shop, Town, TownPostalCode, User
from app.roles import flags_from_roles
from app.security import create_access_token
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio


async def _seed(db_session, *, postal_code="08600", name="VisitTown"):
    town = Town(
        name=name,
        slug=slugify(name),
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{slugify(name)}.cat",
        manager_name="Admin",
        default_visit_points=10,
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(postal_code=postal_code, town_id=town.id, is_primary=True)
    )
    shop_a = Shop(
        town_id=town.id,
        name="Botiga A",
        contact_email="a@test.cat",
        status="active",
        qr_code="QR-A",
        is_fake=False,
    )
    shop_b = Shop(
        town_id=town.id,
        name="Botiga B",
        contact_email="b@test.cat",
        status="active",
        qr_code="QR-B",
        is_fake=False,
    )
    shop_pending = Shop(
        town_id=town.id,
        name="Pendent",
        contact_email="p@test.cat",
        status="pending",
        is_fake=False,
    )
    db_session.add_all([shop_a, shop_b, shop_pending])
    await db_session.flush()
    return town, postal_code, shop_a, shop_b


async def test_shops_for_me_requires_auth(client, db_session):
    await _seed(db_session)
    await db_session.commit()
    r = await client.get("/api/v1/shops/for-me", params={"postal_code": "08600"})
    assert r.status_code in (401, 403)


async def test_shops_for_me_marks_scanned(client, db_session, capture_otp):
    town, cp, shop_a, shop_b = await _seed(db_session)
    await db_session.commit()

    await client.post("/api/v1/auth/request-otp", json={"email": "visitor@test.cat"})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "visitor@test.cat", "code": code},
    )
    token = r.json()["access_token"]
    user_id = r.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    db_session.add(
        QrScan(
            user_id=user_id,
            shop_id=shop_a.id,
            points=10,
            scan_date=date.today(),
            is_fake=False,
        )
    )
    await db_session.commit()

    r = await client.get(
        "/api/v1/shops/for-me",
        headers=headers,
        params={"postal_code": cp, "lang": "ca"},
    )
    assert r.status_code == 200, r.text
    rows = {s["name"]: s for s in r.json()}
    assert set(rows) == {"Botiga A", "Botiga B"}
    assert rows["Botiga A"]["scanned"] is True
    assert rows["Botiga A"]["scan_available"] is False
    assert rows["Botiga A"]["available_at"]
    assert rows["Botiga A"]["last_scanned_at"]
    assert rows["Botiga B"]["scanned"] is False
    assert rows["Botiga B"]["scan_available"] is True
    assert rows["Botiga B"]["available_at"] is None


async def test_shops_for_me_uses_user_postal_code(client, db_session):
    town, cp, shop_a, shop_b = await _seed(
        db_session, postal_code="08601", name="VisitTown2"
    )
    user = User(
        email="cp-user@test.cat",
        slug="cp-user",
        postal_code=cp,
        points=0,
        **flags_from_roles(["resident"]),
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user.id, roles=["resident"], town_id=town.id)
    r = await client.get(
        "/api/v1/shops/for-me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert {s["name"] for s in r.json()} == {"Botiga A", "Botiga B"}


async def test_shops_for_me_demo_cp_heals_is_fake(client, db_session):
    """Normal email + CP 00000 must see is_fake shops (heal user.is_fake)."""
    town = Town(
        name="Demo KM0",
        slug="demo-km0-for-me",
        entity_name="KM0 LAB Demo",
        entity_type="private",
        contact_email="demo@km0lab.com",
        manager_name="Demo",
        default_visit_points=10,
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(postal_code="00000", town_id=town.id, is_primary=True)
    )
    fake_shop = Shop(
        town_id=town.id,
        name="[DEMO] Fleca",
        contact_email="fleca@demo.cat",
        status="active",
        qr_code="DEMO-QR",
        is_fake=True,
    )
    real_shop = Shop(
        town_id=town.id,
        name="Real Only",
        contact_email="real@demo.cat",
        status="active",
        qr_code="REAL-QR",
        is_fake=False,
    )
    user = User(
        email="albert@test.cat",
        slug="albert-demo",
        postal_code="00000",
        points=0,
        is_fake=False,  # bug state after normal OTP signup
        **flags_from_roles(["resident"]),
    )
    db_session.add_all([fake_shop, real_shop, user])
    await db_session.commit()

    token = create_access_token(user.id, roles=["resident"], town_id=town.id)
    r = await client.get(
        "/api/v1/shops/for-me",
        headers={"Authorization": f"Bearer {token}"},
        params={"postal_code": "00000"},
    )
    assert r.status_code == 200, r.text
    names = {s["name"] for s in r.json()}
    assert names == {"[DEMO] Fleca"}
    assert "Real Only" not in names

    await db_session.refresh(user)
    assert user.is_fake is True


async def test_patch_me_demo_postal_sets_is_fake(client, db_session):
    town = Town(
        name="Demo KM0 Patch",
        slug="demo-km0-patch",
        entity_name="KM0 LAB Demo",
        entity_type="private",
        contact_email="demo2@km0lab.com",
        manager_name="Demo",
    )
    other = Town(
        name="Other Town",
        slug="other-town-patch",
        entity_name="Ajuntament",
        entity_type="city_council",
        contact_email="other@test.cat",
        manager_name="Admin",
    )
    db_session.add_all([town, other])
    await db_session.flush()
    db_session.add(
        TownPostalCode(postal_code="00000", town_id=town.id, is_primary=True)
    )
    db_session.add(
        TownPostalCode(postal_code="08699", town_id=other.id, is_primary=True)
    )
    user = User(
        email="patch-demo@test.cat",
        slug="patch-demo",
        postal_code="08699",
        points=0,
        is_fake=False,
        **flags_from_roles(["resident"]),
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user.id, roles=["resident"], town_id=other.id)
    headers = {"Authorization": f"Bearer {token}"}
    r = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"postal_code": "00000"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["postal_code"] == "00000"
    assert r.json()["is_fake"] is True

    r = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"postal_code": "08699"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_fake"] is False
