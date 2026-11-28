"""How many friends pay depends on how the inviter joined.

Ring 0 (joined alone) is rewarded for 3. Ring 1 (invited by a ring 0) for
1. Ring 2 and further for none. Empty ring columns keep today's single
limit. Saving the action from the panel does not clear the new columns.
"""

import pytest
from sqlalchemy import select

from app.models import PointAction
from tests._municipalities import API, admin_headers
from tests.test_invite_limit import _link, _pilot_town, _points, _signup, _summary

pytestmark = pytest.mark.asyncio


async def _invite_action(db, town) -> PointAction:
    return (
        await db.execute(
            select(PointAction).where(
                PointAction.town_id == town.id, PointAction.type == "invite_person"
            )
        )
    ).scalars().one()


async def test_the_chain_pays_three_then_one_then_nothing(
    client, db_session, capture_otp
):
    await _pilot_town(db_session)

    anna = await _signup(client, capture_otp, "anna@test.cat", "08380")
    assert (await _summary(client, anna))["friend_limit"] == 3
    code_a = await _link(client, anna)

    bea = await _signup(client, capture_otp, "bea@test.cat", "08380", code_a)
    assert await _points(client, anna) == 50 + 50
    assert (await _summary(client, bea))["friend_limit"] == 1
    code_b = await _link(client, bea)

    clara = await _signup(client, capture_otp, "clara@test.cat", "08380", code_b)
    assert await _points(client, bea) == 50 + 50
    assert (await _summary(client, clara))["friend_limit"] == 0
    code_c = await _link(client, clara)

    # Clara is ring 2: Dina joins and gets the welcome, Clara earns nothing.
    dina = await _signup(client, capture_otp, "dina@test.cat", "08380", code_c)
    assert dina["user"]["points"] == 50
    assert await _points(client, clara) == 50

    # Bea already used her one rewarded friend.
    elia = await _signup(client, capture_otp, "elia@test.cat", "08380", code_b)
    assert elia["user"]["points"] == 50
    assert await _points(client, bea) == 100
    assert (await _summary(client, bea))["friends_rewarded"] == 1

    # Anna already has Bea. Two more pay; the fourth friend does not.
    before = await _points(client, anna)
    await _signup(client, capture_otp, "faina@test.cat", "08380", code_a)
    await _signup(client, capture_otp, "gala@test.cat", "08380", code_a)
    assert await _points(client, anna) == before + 100
    hero = await _signup(client, capture_otp, "hero@test.cat", "08380", code_a)
    assert hero["user"]["points"] == 50
    assert await _points(client, anna) == before + 100
    assert (await _summary(client, anna))["friends_rewarded"] == 3


async def test_empty_ring_columns_keep_one_limit_for_everyone(
    client, db_session, capture_otp
):
    town = await _pilot_town(db_session)
    action = await _invite_action(db_session, town)
    action.per_user_limit_ring1 = None
    action.per_user_limit_ring2 = None
    await db_session.commit()

    anna = await _signup(client, capture_otp, "anna@test.cat", "08380")
    code = await _link(client, anna)
    bea = await _signup(client, capture_otp, "bea@test.cat", "08380", code)
    assert (await _summary(client, bea))["friend_limit"] == 3
    code_b = await _link(client, bea)
    for n in range(3):
        await _signup(client, capture_otp, f"amic{n}@test.cat", "08380", code_b)
    assert await _points(client, bea) == 50 + 3 * 50


async def test_saving_the_action_keeps_the_ring_columns(client, db_session):
    town = await _pilot_town(db_session)
    action = await _invite_action(db_session, town)
    admin = await admin_headers(db_session, town, "08380")
    r = await client.patch(
        f"{API}/actions/{action.id}",
        headers=admin,
        json={"per_user_limit": 2, "points": 50},
    )
    assert r.status_code == 200, r.text
    await db_session.refresh(action)
    assert (
        action.per_user_limit,
        action.per_user_limit_ring1,
        action.per_user_limit_ring2,
    ) == (2, 1, 0)
