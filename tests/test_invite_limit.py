"""A person is rewarded for a limited number of friends.

The limit is the "uses per user" of the municipality's invitation action:
three in the pilot, and each municipality changes it from the backoffice.
"""

import pytest
from sqlalchemy import select

from app.models import InvitationConversion, PointAction
from app.services.pilot_points import set_pilot_points
from tests._municipalities import API, admin_headers, malgrat, single_town

pytestmark = pytest.mark.asyncio


async def _signup(client, capture_otp, email, postal_code, invite_code=None) -> dict:
    body = {"email": email}
    if invite_code:
        body["invite_code"] = invite_code
    await client.post(f"{API}/auth/request-otp", json=body)
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={**body, "code": capture_otp(), "postal_code": postal_code},
    )
    assert r.status_code == 200, r.text
    session = r.json()
    session["headers"] = {"Authorization": f"Bearer {session['access_token']}"}
    return session


async def _link(client, session: dict) -> str:
    r = await client.get(
        f"{API}/invites/me/link", headers=session["headers"], params={"kind": "person"}
    )
    assert r.status_code == 200, r.text
    return r.json()["public_code"]


async def _summary(client, session: dict) -> dict:
    return (
        await client.get(f"{API}/invites/me/summary", headers=session["headers"])
    ).json()


async def _points(client, session: dict) -> int:
    return (await client.get(f"{API}/users/me", headers=session["headers"])).json()[
        "points"
    ]


async def _pilot_town(db):
    town = await malgrat(db)
    await set_pilot_points(db, town, apply=True)
    await db.commit()
    return town


async def test_three_friends_are_rewarded_and_the_fourth_is_not(
    client, db_session, capture_otp
):
    await _pilot_town(db_session)
    anna = await _signup(client, capture_otp, "anna@test.cat", "08380")
    code = await _link(client, anna)
    assert await _summary(client, anna) == {
        "persons_registered": 0,
        "businesses_registered": 0,
        "points_earned": 0,
        "points_pending": 0,
        "friend_limit": 3,
        "friends_rewarded": 0,
    }

    for n in range(3):
        await _signup(client, capture_otp, f"amic{n}@test.cat", "08380", code)
    assert await _points(client, anna) == 50 + 3 * 50
    assert (await _summary(client, anna))["friends_rewarded"] == 3

    # The fourth friend joins like anyone else, and Anna earns nothing more.
    fourth = await _signup(client, capture_otp, "amic3@test.cat", "08380", code)
    assert fourth["user"]["points"] == 50
    assert await _points(client, anna) == 200
    summary = await _summary(client, anna)
    assert summary["persons_registered"] == 4
    assert summary["friends_rewarded"] == 3
    assert summary["points_earned"] == 150
    assert summary["points_pending"] == 0
    rows = (
        await db_session.execute(
            select(InvitationConversion.reward_points).order_by(
                InvitationConversion.created_at, InvitationConversion.reward_points.desc()
            )
        )
    ).scalars().all()
    assert sorted(rows, reverse=True) == [50, 50, 50, 0]


async def test_each_municipality_sets_its_own_limit(client, db_session, capture_otp):
    town = await _pilot_town(db_session)
    admin = await admin_headers(db_session, town, "08380")
    action = (
        await db_session.execute(
            select(PointAction).where(
                PointAction.town_id == town.id, PointAction.type == "invite_person"
            )
        )
    ).scalars().one()

    r = await client.patch(
        f"{API}/actions/{action.id}", headers=admin, json={"per_user_limit": 1}
    )
    assert r.status_code == 200, r.text

    anna = await _signup(client, capture_otp, "anna@test.cat", "08380")
    code = await _link(client, anna)
    assert (await _summary(client, anna))["friend_limit"] == 1
    await _signup(client, capture_otp, "amic0@test.cat", "08380", code)
    await _signup(client, capture_otp, "amic1@test.cat", "08380", code)
    assert await _points(client, anna) == 50 + 50


async def test_without_a_limit_every_friend_pays(client, db_session, capture_otp):
    """A municipality that leaves the field empty keeps today's behaviour."""
    town = await _pilot_town(db_session)
    action = (
        await db_session.execute(
            select(PointAction).where(
                PointAction.town_id == town.id, PointAction.type == "invite_person"
            )
        )
    ).scalars().one()
    action.per_user_limit = None
    await db_session.commit()

    anna = await _signup(client, capture_otp, "anna@test.cat", "08380")
    code = await _link(client, anna)
    assert (await _summary(client, anna))["friend_limit"] is None
    for n in range(5):
        await _signup(client, capture_otp, f"amic{n}@test.cat", "08380", code)
    assert await _points(client, anna) == 50 + 5 * 50


async def test_the_limit_counts_friends_of_this_municipality(
    client, db_session, capture_otp
):
    """Moving to another town starts a new count there: the link follows its
    owner and the limit is the one of the town they are in."""
    await _pilot_town(db_session)
    blanes = await single_town(db_session, "Blanes", "17300")
    await set_pilot_points(db_session, blanes, apply=True)
    await db_session.commit()

    anna = await _signup(client, capture_otp, "anna@test.cat", "08380")
    code = await _link(client, anna)
    for n in range(3):
        await _signup(client, capture_otp, f"amic{n}@test.cat", "08380", code)
    assert (await _summary(client, anna))["friends_rewarded"] == 3

    r = await client.patch(
        f"{API}/users/me", headers=anna["headers"], json={"postal_code": "17300"}
    )
    assert r.status_code == 200, r.text
    assert (await _summary(client, anna))["friends_rewarded"] == 0
