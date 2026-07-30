"""Town public rules + admin PATCH persistence for point config."""

import pytest

from app.models import Town, TownPostalCode, User
from app.roles import flags_from_roles
from app.security import create_access_token
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio


async def _create_town(db_session, name="ConfigTown", postal_code="08550"):
    town = Town(
        name=name,
        slug=slugify(name),
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{slugify(name)}.cat",
        manager_name="Admin",
        points_per_euro=200,
        default_visit_points=10,
        default_lang="ca",
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(postal_code=postal_code, town_id=town.id, is_primary=True)
    )
    await db_session.flush()
    return town, postal_code


async def test_towns_public_by_postal_code(client, db_session):
    town, cp = await _create_town(db_session, "PublicRules", "08551")
    town.points_per_euro = 150
    town.default_visit_points = 12
    town.default_lang = "es"
    town.expiry_months = None
    await db_session.commit()

    r = await client.get("/api/v1/towns/public", params={"postal_code": cp})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == town.id
    assert body["name"] == "PublicRules"
    assert body["points_per_euro"] == 150
    assert body["default_visit_points"] == 12
    assert body["default_lang"] == "es"
    assert body["expiry_months"] is None
    assert "has_logo" in body


async def test_towns_public_unknown_postal_code(client):
    r = await client.get(
        "/api/v1/towns/public", params={"postal_code": "99999"}
    )
    assert r.status_code == 404


async def test_admin_patch_persists_point_rules(client, db_session):
    town, cp = await _create_town(db_session, "PatchTown", "08552")
    await db_session.commit()

    admin = User(
        email="admin-patch@test.cat",
        slug="admin-patch",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.patch(
        f"/api/v1/towns/{town.id}",
        headers=headers,
        json={
            "points_per_euro": 250,
            "default_visit_points": 15,
            "expiry_months": 12,
            "default_lang": "en",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["points_per_euro"] == 250
    assert body["default_visit_points"] == 15
    assert body["expiry_months"] == 12
    assert body["default_lang"] == "en"

    # Public endpoint reflects the same persisted values.
    r = await client.get("/api/v1/towns/public", params={"postal_code": cp})
    assert r.status_code == 200
    pub = r.json()
    assert pub["points_per_euro"] == 250
    assert pub["default_visit_points"] == 15
    assert pub["default_lang"] == "en"
    assert pub["expiry_months"] == 12
