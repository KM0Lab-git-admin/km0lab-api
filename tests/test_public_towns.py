"""The towns the app reads without a session: few queries, and fresh enough.

Every query is a round trip to the database, and these two reads are on
every resident's path. The counts below are the contract: if one grows,
the list is slow again.
"""

import pytest
from sqlalchemy import event

from app.models import Town, TownPostalCode
from app.services import public_towns
from app.services.localities import ensure_default_locality
from tests._municipalities import (
    API,
    admin_headers,
    baix_montseny,
    malgrat,
    single_town,
)

pytestmark = pytest.mark.asyncio

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
# Towns, postal codes, localities, town images, locality illustrations.
QUERIES_TO_BUILD = 5


@pytest.fixture
def queries(engine):
    """Counts the SQL statements sent while the test runs."""
    seen: list[str] = []

    def _count(_conn, _cursor, statement, *_rest):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _count)
    yield seen
    event.remove(engine.sync_engine, "before_cursor_execute", _count)


async def _list(client) -> list[dict]:
    r = await client.get(f"{API}/towns")
    assert r.status_code == 200, r.text
    return r.json()


async def _card(client, postal_code: str):
    return await client.get(f"{API}/towns/public", params={"postal_code": postal_code})


# ── How many queries ──────────────────────────────────────────────────


async def test_list_costs_the_same_with_one_municipality_or_many(
    client, db_session, queries
):
    await malgrat(db_session)
    await db_session.commit()
    queries.clear()
    assert [t["name"] for t in await _list(client)] == ["Malgrat de Mar"]
    with_one = len(queries)

    await single_town(db_session, "Blanes", "17300")
    await single_town(db_session, "Lloret de Mar", "17310")
    await baix_montseny(db_session)
    await db_session.commit()
    public_towns.invalidate()
    queries.clear()
    names = [t["name"] for t in await _list(client)]
    with_many = len(queries)

    assert len(names) == 6
    assert with_one == with_many == QUERIES_TO_BUILD


async def test_once_read_the_list_and_the_cards_cost_nothing(
    client, db_session, queries
):
    await malgrat(db_session)
    await baix_montseny(db_session)
    await db_session.commit()

    queries.clear()
    first = await _card(client, "17450")
    assert first.json()["name"] == "Hostalric"
    assert len(queries) == QUERIES_TO_BUILD  # the first read builds everything

    queries.clear()
    assert (await _card(client, "17450")).json() == first.json()
    assert (await _card(client, "08380")).json()["name"] == "Malgrat de Mar"
    assert len(await _list(client)) == 4
    assert queries == []


async def test_unknown_postal_code_costs_one_query(client, db_session, queries):
    await malgrat(db_session)
    await db_session.commit()
    await _list(client)

    queries.clear()
    r = await _card(client, "12345")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown postal code"
    assert len(queries) == 1


# ── How fresh ─────────────────────────────────────────────────────────


async def test_backoffice_changes_show_at_once(client, db_session):
    town = await malgrat(db_session)
    headers = await admin_headers(db_session, town, "08380")
    before = (await _card(client, "08380")).json()
    assert (before["default_visit_points"], before["has_logo"]) == (15, False)

    r = await client.patch(
        f"{API}/towns/{town.id}", json={"default_visit_points": 40}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert (await _card(client, "08380")).json()["default_visit_points"] == 40

    r = await client.put(
        f"{API}/towns/{town.id}/media/logo",
        files={"file": ("logo.png", PNG, "image/png")},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert (await _card(client, "08380")).json()["has_logo"] is True
    assert (await _list(client))[0]["has_logo"] is True

    r = await client.delete(f"{API}/towns/{town.id}/media/logo", headers=headers)
    assert r.status_code == 204
    assert (await _card(client, "08380")).json()["has_logo"] is False


async def test_a_change_from_a_script_shows_within_the_ttl(
    client, db_session, monkeypatch
):
    """A script runs in another process: it cannot clear this memory."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(public_towns.time, "monotonic", lambda: clock["now"])
    town = await malgrat(db_session)
    await db_session.commit()
    assert (await _card(client, "08380")).json()["default_visit_points"] == 15

    # As a script would: straight into the database.
    (await db_session.get(Town, town.id)).default_visit_points = 99
    await db_session.commit()

    clock["now"] += public_towns.TTL_SECONDS - 1
    assert (await _card(client, "08380")).json()["default_visit_points"] == 15
    clock["now"] += 2
    assert (await _card(client, "08380")).json()["default_visit_points"] == 99


async def test_a_town_added_by_a_script_answers_straight_away(
    client, db_session, queries
):
    await malgrat(db_session)
    await db_session.commit()
    assert len(await _list(client)) == 1

    # ``scripts/add_town.py``, in another process.
    blanes = Town(name="Blanes", slug="blanes", default_visit_points=10)
    db_session.add(blanes)
    await db_session.flush()
    db_session.add(
        TownPostalCode(postal_code="17300", town_id=blanes.id, is_primary=True)
    )
    await db_session.flush()
    await ensure_default_locality(db_session, blanes)
    await db_session.commit()

    # Its postal code is not in memory: looked up, found, everything re-read.
    queries.clear()
    r = await _card(client, "17300")
    assert r.status_code == 200 and r.json()["name"] == "Blanes"
    assert len(queries) == 1 + QUERIES_TO_BUILD
    assert [t["name"] for t in await _list(client)] == ["Blanes", "Malgrat de Mar"]
