"""Localities: towns inside a municipality, and grouping them."""

import pytest
from sqlalchemy import func, select

from app.models import (
    Locality,
    LocalityMedia,
    PointAction,
    Reward,
    Shop,
    Town,
    TownMedia,
    TownPostalCode,
    User,
)
from app.security import create_access_token
from app.services.localities import (
    GroupRefused,
    ensure_default_locality,
    group_towns,
)
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


async def _town(db, name: str, postal_code: str, *, art: bool = False) -> Town:
    """A municipality that is a single town, as ``scripts/add_town`` leaves it."""
    town = Town(name=name, slug=slugify(name), default_visit_points=15)
    db.add(town)
    await db.flush()
    db.add(TownPostalCode(postal_code=postal_code, town_id=town.id, is_primary=True))
    if art:
        db.add(
            TownMedia(
                town_id=town.id,
                kind="art",
                content_type="image/png",
                data=PNG + name.encode(),
                byte_size=len(PNG) + len(name),
            )
        )
    await db.flush()
    await ensure_default_locality(db, town)
    return town


async def _three(db) -> None:
    await _town(db, "Breda", "17400", art=True)
    await _town(db, "Hostalric", "17450", art=True)
    await _town(db, "Riells i Viabrea", "17404")
    await db.commit()


async def _count(db, model, *clauses) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*clauses))


async def _public(client, postal_code: str) -> dict:
    r = await client.get(f"{API}/towns/public", params={"postal_code": postal_code})
    assert r.status_code == 200, r.text
    return r.json()


# ── A single-town municipality behaves exactly as before ─────────────


async def test_single_town_keeps_its_public_card(client, db_session):
    town = await _town(db_session, "Malgrat de Mar", "08380", art=True)
    await db_session.commit()

    card = await _public(client, "08380")

    assert card["id"] == town.id
    assert card["name"] == "Malgrat de Mar"
    assert card["postal_codes"] == ["08380"]
    assert card["art_url"].startswith(f"/api/v1/towns/{town.id}/media/art")
    assert card["default_visit_points"] == 15
    # New, additive fields.
    assert card["municipality_id"] == town.id
    assert card["municipality_name"] == "Malgrat de Mar"
    assert [loc["name"] for loc in card["localities"]] == ["Malgrat de Mar"]
    assert card["locality_id"] == card["localities"][0]["id"]


async def test_town_created_without_locality_still_answers(client, db_session):
    """Rows older than localities: the card falls back to the municipality."""
    town = Town(name="Poble Antic", slug="poble-antic")
    db_session.add(town)
    await db_session.flush()
    db_session.add(TownPostalCode(postal_code="08001", town_id=town.id))
    await db_session.commit()

    card = await _public(client, "08001")

    assert card["name"] == "Poble Antic"
    assert card["locality_id"] is None
    assert card["localities"] == []


# ── Grouping ──────────────────────────────────────────────────────────


async def test_group_dry_run_changes_nothing(db_session):
    await _three(db_session)
    report = await group_towns(
        db_session,
        name="Baix Montseny",
        postal_codes=["17400", "17450", "17404"],
        dry_run=True,
    )
    await db_session.rollback()

    assert report.created_municipality is True
    assert report.localities == ["Breda", "Hostalric", "Riells i Viabrea"]
    assert report.moved_art == 2
    assert await _count(db_session, Town) == 3
    assert await _count(db_session, Town, Town.slug == "baix-montseny") == 0


async def test_grouped_towns_keep_name_and_art_and_share_the_scope(
    client, db_session
):
    await _three(db_session)
    shop = Shop(
        town_id=(await _public(client, "17450"))["id"],
        name="Forn d'Hostalric",
        status="active",
        postal_code="17450",
    )
    db_session.add(shop)
    await db_session.commit()

    await group_towns(
        db_session,
        name="Baix Montseny",
        postal_codes=["17400", "17450", "17404"],
        dry_run=False,
    )
    await db_session.commit()

    breda = await _public(client, "17400")
    hostalric = await _public(client, "17450")
    riells = await _public(client, "17404")

    # One municipality for the three; the app never shows its name.
    assert breda["id"] == hostalric["id"] == riells["id"]
    assert breda["municipality_name"] == "Baix Montseny"
    # Each postal code still answers with ITS town.
    assert breda["name"] == "Breda" and breda["postal_codes"] == ["17400"]
    assert hostalric["name"] == "Hostalric"
    assert riells["name"] == "Riells i Viabrea"
    # ... and lists the neighbours.
    names = [loc["name"] for loc in breda["localities"]]
    assert names == ["Breda", "Hostalric", "Riells i Viabrea"]
    # Each town keeps its own illustration; Riells has none.
    assert breda["art_url"].startswith("/api/v1/towns/localities/")
    assert breda["art_url"] != hostalric["art_url"]
    assert riells["art_url"] is None
    art = await client.get(breda["art_url"])
    assert art.status_code == 200 and art.content.endswith(b"Breda")

    # The emptied municipalities are gone, the default actions exist once.
    assert await _count(db_session, Town) == 1
    assert await _count(db_session, Locality) == 3
    assert await _count(db_session, LocalityMedia) == 2
    assert await _count(db_session, TownMedia) == 0
    assert await _count(db_session, PointAction, PointAction.town_id == breda["id"]) > 0
    assert await _count(db_session, TownPostalCode, TownPostalCode.is_primary) == 1

    # The shop moved with its town and says where it is.
    await db_session.refresh(shop)
    assert shop.town_id == breda["id"]
    listed = await client.get(f"{API}/shops/public", params={"postal_code": "17400"})
    assert listed.status_code == 200
    assert [s["town_name"] for s in listed.json()] == ["Hostalric"]
    assert listed.json()[0]["locality_id"] == hostalric["locality_id"]

    # The public list offers the three towns, not the municipality.
    towns = (await client.get(f"{API}/towns")).json()
    assert [t["name"] for t in towns] == ["Breda", "Hostalric", "Riells i Viabrea"]

    # Running it again finds nothing left to do.
    again = await group_towns(
        db_session,
        name="Baix Montseny",
        postal_codes=["17400", "17450", "17404"],
        dry_run=False,
    )
    assert again.removed_towns == [] and again.created_municipality is False


async def test_resident_sees_their_town_not_the_municipality(client, db_session):
    await _three(db_session)
    await group_towns(
        db_session,
        name="Baix Montseny",
        postal_codes=["17400", "17450", "17404"],
        dry_run=False,
    )
    user = User(email="veina@test.cat", slug="veina", postal_code="17450")
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user.id, roles=["resident"])
    r = await client.get(
        f"{API}/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert r.json()["town_name"] == "Hostalric"
    assert r.json()["town_id"] == (await _public(client, "17400"))["id"]


async def test_group_refuses_a_town_with_its_own_activity(db_session):
    await _three(db_session)
    breda = (
        await db_session.execute(select(Town).where(Town.slug == "breda"))
    ).scalars().one()
    db_session.add(
        Reward(town_id=breda.id, name="Val", type="discount", points_required=10)
    )
    await db_session.commit()

    with pytest.raises(GroupRefused):
        await group_towns(
            db_session,
            name="Baix Montseny",
            postal_codes=["17400", "17450", "17404"],
            dry_run=False,
        )
    await db_session.rollback()
    assert await _count(db_session, Town) == 3


async def test_group_refuses_unknown_or_partial_postal_codes(db_session):
    town = await _town(db_session, "Blanes", "17300")
    db_session.add(TownPostalCode(postal_code="17301", town_id=town.id))
    await db_session.commit()

    with pytest.raises(GroupRefused):
        await group_towns(
            db_session, name="X", postal_codes=["17300", "99000"], dry_run=False
        )
    # A town is moved whole: all its postal codes must be listed.
    with pytest.raises(GroupRefused):
        await group_towns(db_session, name="X", postal_codes=["17300"], dry_run=False)
    await db_session.rollback()
    assert await _count(db_session, Town) == 1
