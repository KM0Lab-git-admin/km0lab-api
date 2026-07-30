"""Public point-actions catalog by postal code (i18n-aware)."""

import pytest

from app.models import PointAction, Town, TownPostalCode
from app.utils.slug import slugify


async def _town_with_actions(db_session, *, postal_code="08380", name="Malgrat Pub"):
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
    db_session.add_all(
        [
            # Fixed type → name comes from the catalog, not the stored string.
            PointAction(
                town_id=town.id,
                type="birthday",
                name="ignored-stored-name",
                description="ignored",
                points=10,
                active=True,
                visible_home=True,
                is_fake=False,
            ),
            PointAction(
                town_id=town.id,
                type="signup",
                name="x",
                description="x",
                points=100,
                active=True,
                visible_home=False,
                is_fake=False,
            ),
            PointAction(
                town_id=town.id,
                type="custom",
                name="My Custom Action",
                description="Custom desc",
                points=5,
                active=True,
                visible_home=True,
                is_fake=False,
            ),
            PointAction(
                town_id=town.id,
                type="custom",
                name="Inactive Custom",
                description="x",
                points=5,
                active=False,
                visible_home=True,
                is_fake=False,
            ),
            PointAction(
                town_id=town.id,
                type="web_visit",
                name="demo",
                description="demo",
                points=20,
                active=True,
                visible_home=True,
                is_fake=True,
            ),
        ]
    )
    await db_session.commit()
    return town


@pytest.mark.asyncio
async def test_public_actions_by_postal_home_filter(client, db_session):
    await _town_with_actions(db_session, postal_code="08381")

    home = await client.get(
        "/api/v1/actions/public",
        params={"postal_code": "08381", "visible_home": True},
    )
    assert home.status_code == 200, home.text
    types = {a["type"] for a in home.json()}
    # birthday (fixed, home) + custom (home); inactive custom excluded.
    assert types == {"birthday", "custom"}

    not_home = await client.get(
        "/api/v1/actions/public",
        params={"postal_code": "08381", "visible_home": False},
    )
    assert {a["type"] for a in not_home.json()} == {"signup"}

    all_active = await client.get(
        "/api/v1/actions/public",
        params={"postal_code": "08381"},
    )
    assert {a["type"] for a in all_active.json()} == {
        "birthday",
        "signup",
        "custom",
    }


@pytest.mark.asyncio
async def test_public_actions_i18n_resolution(client, db_session):
    await _town_with_actions(db_session, postal_code="08383", name="I18nTown")

    ca = await client.get(
        "/api/v1/actions/public",
        params={"postal_code": "08383", "lang": "ca", "visible_home": True},
    )
    es = await client.get(
        "/api/v1/actions/public",
        params={"postal_code": "08383", "lang": "es", "visible_home": True},
    )
    en = await client.get(
        "/api/v1/actions/public",
        params={"postal_code": "08383", "lang": "en", "visible_home": True},
    )

    by_type_ca = {a["type"]: a["name"] for a in ca.json()}
    by_type_es = {a["type"]: a["name"] for a in es.json()}
    by_type_en = {a["type"]: a["name"] for a in en.json()}

    # Fixed type birthday is translated from the catalog per lang.
    assert by_type_ca["birthday"] != by_type_es["birthday"]
    assert by_type_es["birthday"] != by_type_en["birthday"]
    # Custom action keeps its stored name across langs (ca fallback).
    assert by_type_ca["custom"] == "My Custom Action"
    assert by_type_es["custom"] == "My Custom Action"


@pytest.mark.asyncio
async def test_public_actions_unknown_postal(client):
    r = await client.get(
        "/api/v1/actions/public",
        params={"postal_code": "00000"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_public_actions_demo_partition(client, db_session):
    await _town_with_actions(db_session, postal_code="08382", name="DemoCP")
    r = await client.get(
        "/api/v1/actions/public",
        params={"postal_code": "08382", "demo": True, "visible_home": True},
    )
    assert r.status_code == 200
    assert {a["type"] for a in r.json()} == {"web_visit"}
