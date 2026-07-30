"""Shop category emoji on list + admin PATCH."""

from __future__ import annotations

import pytest

from app.models import Town, TownPostalCode, User
from app.roles import flags_from_roles
from app.security import create_access_token
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio


async def test_list_shop_categories_includes_emoji(client):
    r = await client.get("/api/v1/shop-categories")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    bakery = next(c for c in rows if c["slug"] == "bakery")
    assert bakery["emoji"] == "🥖"
    assert bakery["label"]


async def test_admin_can_patch_category_emoji(client, db_session):
    town = Town(
        name="EmojiTown",
        slug=slugify("EmojiTown"),
        entity_name="Ajuntament Emoji",
        entity_type="city_council",
        contact_email="admin@emoji.cat",
        manager_name="Admin",
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(postal_code="08880", town_id=town.id, is_primary=True)
    )
    admin = User(
        email="admin-emoji@test.cat",
        slug="admin-emoji",
        postal_code="08880",
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    r = await client.patch(
        "/api/v1/shop-categories/bakery",
        headers={"Authorization": f"Bearer {token}"},
        json={"emoji": "🥐"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["emoji"] == "🥐"
    assert r.json()["slug"] == "bakery"

    listed = await client.get("/api/v1/shop-categories")
    bakery = next(c for c in listed.json() if c["slug"] == "bakery")
    assert bakery["emoji"] == "🥐"
