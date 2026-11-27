"""Admin on-behalf of a shop via X-Acting-Shop-Id."""

import pytest

from app.models import Shop, Town, TownPostalCode, User
from app.roles import flags_from_roles
from app.security import create_access_token
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio


async def _town_with_shops(db_session, *, name="ActTown", postal_code="08700"):
    town = Town(
        name=name,
        slug=slugify(name),
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{slugify(name)}.cat",
        manager_name="Admin",
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(postal_code=postal_code, town_id=town.id, is_primary=True)
    )
    shop = Shop(
        town_id=town.id,
        name="Shop Act",
        contact_email=f"shop-{postal_code}@test.cat",
        status="active",
        qr_code=f"ACT-QR-{postal_code}",
        is_fake=False,
    )
    db_session.add(shop)
    await db_session.flush()
    return town, postal_code, shop


async def test_admin_acting_get_me(client, db_session):
    town, cp, shop = await _town_with_shops(db_session)
    admin = User(
        email="admin-act@test.cat",
        slug="admin-act",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Acting-Shop-Id": shop.id,
    }
    r = await client.get("/api/v1/shops/me", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == shop.id
    assert r.json()["name"] == "Shop Act"

    r = await client.patch(
        "/api/v1/shops/me",
        headers=headers,
        json={"description": "Edited by admin on behalf"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "Edited by admin on behalf"


async def test_admin_acting_requires_header(client, db_session):
    town, cp, shop = await _town_with_shops(
        db_session, name="ActTown2", postal_code="08701"
    )
    admin = User(
        email="admin-act2@test.cat",
        slug="admin-act2",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()
    token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    r = await client.get(
        "/api/v1/shops/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


async def test_admin_acting_other_town_forbidden(client, db_session):
    town_a, cp_a, shop_a = await _town_with_shops(
        db_session, name="TownAAct", postal_code="08702"
    )
    town_b, cp_b, shop_b = await _town_with_shops(
        db_session, name="TownBAct", postal_code="08703"
    )
    admin = User(
        email="admin-scope@test.cat",
        slug="admin-scope",
        postal_code=cp_a,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()
    token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town_a.id
    )
    r = await client.get(
        "/api/v1/shops/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Acting-Shop-Id": shop_b.id,
        },
    )
    assert r.status_code == 403


async def test_merchant_cannot_act_as_other_shop(client, db_session):
    town, cp, shop = await _town_with_shops(
        db_session, name="MerchTown", postal_code="08704"
    )
    other = Shop(
        town_id=town.id,
        name="Other Shop",
        contact_email="other@test.cat",
        status="active",
        qr_code="OTHER-QR-08704",
        is_fake=False,
    )
    merchant = User(
        email="merch-act@test.cat",
        slug="merch-act",
        postal_code=cp,
        shop_id=shop.id,
        points=0,
        **flags_from_roles(["merchant", "resident"]),
    )
    db_session.add_all([other, merchant])
    await db_session.commit()

    token = create_access_token(
        merchant.id,
        roles=["merchant", "resident"],
        town_id=town.id,
        shop_id=shop.id,
    )
    r = await client.get(
        "/api/v1/shops/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Acting-Shop-Id": other.id,
        },
    )
    assert r.status_code == 403

    r = await client.get(
        "/api/v1/shops/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["id"] == shop.id
