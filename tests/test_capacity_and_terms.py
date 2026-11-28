"""A municipality admits a limited number of accounts, and each account
keeps proof of the terms it accepted (``app/services/capacity.py``)."""

from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import Shop, User
from app.services.capacity import CURRENT_TERMS_VERSION, residents_count
from app.services.pilot_points import set_pilot_points
from tests._municipalities import API, admin_headers, catalog, malgrat, single_town

pytestmark = pytest.mark.asyncio

FULL = {"code": "pilot_full", "message": "El pilot d'aquesta població està complet."}


async def _ask(client, email: str, postal_code: str | None = "08380", **extra):
    body = {"email": email, **extra}
    if postal_code:
        body["postal_code"] = postal_code
    return await client.post(f"{API}/auth/request-otp", json=body)


async def _enter(client, capture_otp, email: str, postal_code: str | None = "08380", **extra):
    body = {"email": email, **extra}
    if postal_code:
        body["postal_code"] = postal_code
    r = await client.post(f"{API}/auth/request-otp", json=body)
    assert r.status_code == 200, r.text
    return await client.post(
        f"{API}/auth/verify-otp", json={**body, "code": capture_otp()}
    )


async def _town_with_room_for(db, places: int):
    town = await malgrat(db)
    town.max_residents = places
    await db.commit()
    return town


# ── Capacity ──────────────────────────────────────────────────────────


async def test_without_a_limit_anyone_can_register(client, db_session, capture_otp):
    await malgrat(db_session)
    await db_session.commit()
    for n in range(4):
        r = await _enter(client, capture_otp, f"vei{n}@test.cat")
        assert r.status_code == 200, r.text


async def test_a_full_pilot_says_so_before_sending_a_code(
    client, db_session, capture_otp
):
    town = await _town_with_room_for(db_session, 2)
    for n in range(2):
        assert (await _enter(client, capture_otp, f"vei{n}@test.cat")).status_code == 200
    assert await residents_count(db_session, town.id) == 2
    last_code_sent = capture_otp()

    r = await _ask(client, "tard@test.cat")

    assert r.status_code == 409
    assert r.json()["detail"] == FULL
    # No account was created, and nobody was sent a code.
    assert capture_otp() == last_code_sent
    assert await db_session.scalar(select(User).where(User.email == "tard@test.cat")) is None


async def test_the_last_place_is_decided_when_the_code_is_entered(
    client, db_session, capture_otp
):
    """Two people ask while there is one place: both get a code, one gets in."""
    await _town_with_room_for(db_session, 1)
    assert (await _ask(client, "a@test.cat")).status_code == 200
    code_a = capture_otp()
    assert (await _ask(client, "b@test.cat")).status_code == 200
    code_b = capture_otp()

    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": "a@test.cat", "code": code_a, "postal_code": "08380"},
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": "b@test.cat", "code": code_b, "postal_code": "08380"},
    )
    assert r.status_code == 409 and r.json()["detail"] == FULL
    assert await db_session.scalar(select(User).where(User.email == "b@test.cat")) is None


async def test_whoever_is_in_can_always_log_in(client, db_session, capture_otp):
    await _town_with_room_for(db_session, 1)
    assert (await _enter(client, capture_otp, "vei@test.cat")).status_code == 200

    again = await _enter(client, capture_otp, "vei@test.cat")

    assert again.status_code == 200, again.text
    assert again.json()["user"]["postal_code"] == "08380"


async def test_the_demo_and_other_towns_are_not_affected(
    client, db_session, capture_otp
):
    await _town_with_room_for(db_session, 1)
    await single_town(db_session, "Blanes", "17300")
    await catalog(db_session)
    await db_session.commit()
    assert (await _enter(client, capture_otp, "vei@test.cat")).status_code == 200

    # The demonstration never fills up, and its accounts take no real place.
    for n in range(3):
        r = await _enter(client, capture_otp, f"demo{n}@test.cat", "00000")
        assert r.status_code == 200, r.text
    assert (await _enter(client, capture_otp, "blanes@test.cat", "17300")).status_code == 200
    assert (await _ask(client, "tard@test.cat")).status_code == 409


async def test_a_full_town_takes_no_arrivals_from_elsewhere(
    client, db_session, capture_otp
):
    """Neither a resident of another town nor a demo account that wants to
    become a real one: both would take a place."""
    await _town_with_room_for(db_session, 1)
    await single_town(db_session, "Blanes", "17300")
    await catalog(db_session)
    await db_session.commit()
    assert (await _enter(client, capture_otp, "vei@test.cat")).status_code == 200
    blanes = (await _enter(client, capture_otp, "blanes@test.cat", "17300")).json()
    demo = (await _enter(client, capture_otp, "demo@test.cat", "00000")).json()

    for session, body in (
        (blanes, {"postal_code": "08380"}),
        (demo, {"postal_code": "08380", "leave_demo": True}),
    ):
        r = await client.patch(
            f"{API}/users/me",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json=body,
        )
        assert r.status_code == 200, r.text
        assert r.json()["postal_code"] == session["user"]["postal_code"]
        assert r.json()["points"] == session["user"]["points"]


async def test_a_shop_the_administrator_registered_gets_in_anyway(
    client, db_session, capture_otp
):
    town = await _town_with_room_for(db_session, 1)
    admin = await admin_headers(db_session, town, "08380")
    r = await client.post(
        f"{API}/shops",
        headers=admin,
        json={"name": "Forn", "contact_email": "forn@test.cat", "categories": ["bakery"]},
    )
    assert r.status_code == 201, r.text
    # The administrator already fills the only place.
    assert (await _ask(client, "tard@test.cat")).status_code == 409

    owner = await _enter(client, capture_otp, "forn@test.cat")

    assert owner.status_code == 200, owner.text
    assert "merchant" in owner.json()["user"]["roles"]
    shop = (await db_session.execute(select(Shop))).scalars().one()
    assert owner.json()["user"]["shop_id"] == shop.id


async def test_the_administrator_sees_and_changes_the_limit(client, db_session):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")

    me = (await client.get(f"{API}/towns/me", headers=admin)).json()
    assert (me["max_residents"], me["residents_count"]) == (None, 1)

    r = await client.patch(
        f"{API}/towns/{town.id}", headers=admin, json={"max_residents": 200}
    )
    assert r.status_code == 200 and r.json()["max_residents"] == 200
    r = await client.patch(
        f"{API}/towns/{town.id}", headers=admin, json={"max_residents": None}
    )
    assert r.status_code == 200 and r.json()["max_residents"] is None
    r = await client.patch(
        f"{API}/towns/{town.id}", headers=admin, json={"max_residents": 0}
    )
    assert r.status_code == 422


async def test_the_pilot_script_sets_200_and_leaves_the_demo_open(db_session):
    town = await malgrat(db_session)
    demo = await catalog(db_session)
    await db_session.commit()

    for each in (town, demo):
        await set_pilot_points(db_session, each, apply=True)
    await db_session.commit()

    await db_session.refresh(town)
    await db_session.refresh(demo)
    assert town.max_residents == 200
    assert demo.max_residents is None


# ── Terms ─────────────────────────────────────────────────────────────


async def test_a_new_account_keeps_what_it_accepted_and_when(
    client, db_session, capture_otp
):
    await malgrat(db_session)
    await db_session.commit()

    r = await _enter(client, capture_otp, "vei@test.cat", terms_version=CURRENT_TERMS_VERSION)

    user = r.json()["user"]
    assert user["terms_version"] == CURRENT_TERMS_VERSION == "2"
    assert user["terms_accepted_at"] is not None

    # Logging in again does not move the date.
    again = await _enter(client, capture_otp, "vei@test.cat", terms_version=CURRENT_TERMS_VERSION)
    assert again.json()["user"]["terms_accepted_at"] == user["terms_accepted_at"]


async def test_an_app_that_sends_no_version_records_nothing(
    client, db_session, capture_otp
):
    """The app published today does not send it: the account is created as
    before, with nothing recorded, and accepts later."""
    await malgrat(db_session)
    await db_session.commit()

    r = await _enter(client, capture_otp, "vei@test.cat")
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["terms_version"] is None and user["terms_accepted_at"] is None

    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    # A version that is not the one in force proves nothing.
    r = await client.patch(f"{API}/users/me", headers=headers, json={"terms_version": "0"})
    assert r.json()["terms_version"] is None
    r = await client.patch(f"{API}/users/me", headers=headers, json={"terms_version": CURRENT_TERMS_VERSION})
    assert r.json()["terms_version"] == CURRENT_TERMS_VERSION
    assert r.json()["terms_accepted_at"] is not None


async def test_whoever_accepted_the_previous_version_accepts_the_new_one_once(
    client, db_session, capture_otp
):
    """The terms went from version 1 to 2 (28-11-2026): the old acceptance
    stays on record until the person accepts the new text, once."""
    await malgrat(db_session)
    await db_session.commit()
    r = await _enter(client, capture_otp, "vei@test.cat")
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    user = await db_session.get(User, r.json()["user"]["id"])
    user.terms_version = "1"
    user.terms_accepted_at = datetime(2026, 11, 27, 9, 0, 0)
    await db_session.commit()

    me = (await client.get(f"{API}/users/me", headers=headers)).json()
    assert me["terms_version"] == "1"
    # An app that still sends the old version changes nothing.
    r = await client.patch(f"{API}/users/me", headers=headers, json={"terms_version": "1"})
    assert r.json()["terms_version"] == "1"
    assert r.json()["terms_accepted_at"].startswith("2026-11-27T09:00:00")

    r = await client.patch(
        f"{API}/users/me", headers=headers, json={"terms_version": CURRENT_TERMS_VERSION}
    )
    assert r.json()["terms_version"] == CURRENT_TERMS_VERSION
    assert not r.json()["terms_accepted_at"].startswith("2026-11-27T09:00:00")
