"""An account does not carry points between the demo and a real town
(``app/services/residency.py``).

The app sends the device's postal code every time someone logs in. Before,
that moved the account: points earned scanning make-believe shops became
real ones in Malgrat, and a real resident who peeked at the demo left town.
"""

import pytest
from sqlalchemy import select

from app.models import InvitationLink, PointsTransaction, Shop, User
from app.roles import flags_from_roles
from app.security import create_access_token
from app.services.points import apply_points
from app.services.residency import TX_DEMO_EXIT
from tests._municipalities import API, catalog, malgrat, single_town

pytestmark = pytest.mark.asyncio

DEMO_CP = "00000"


async def _signup(client, capture_otp, email: str, postal_code: str) -> dict:
    r = await client.post(f"{API}/auth/request-otp", json={"email": email})
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": email, "code": capture_otp(), "postal_code": postal_code},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


async def _move(client, headers: dict, postal_code: str | None) -> dict:
    r = await client.patch(
        f"{API}/users/me", headers=headers, json={"postal_code": postal_code}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _earn(db, email: str, points: int) -> None:
    user = (await db.execute(select(User).where(User.email == email))).scalars().one()
    await apply_points(db, user=user, points=points, type="scan", ref_id="demo-scan")
    await db.commit()


async def _ledger(db, email: str) -> list[tuple[str, int, bool]]:
    rows = (
        await db.execute(
            select(PointsTransaction)
            .join(User, User.id == PointsTransaction.user_id)
            .where(User.email == email)
        )
    ).scalars().all()
    return [(tx.type, tx.points, tx.is_fake) for tx in rows]


# ── Who is a demo account ─────────────────────────────────────────────


async def test_signing_up_in_the_demo_makes_a_demo_account(
    client, db_session, capture_otp
):
    await malgrat(db_session)
    await catalog(db_session)
    await db_session.commit()

    session = await _signup(client, capture_otp, "amiga@test.cat", DEMO_CP)

    assert session["user"]["postal_code"] == DEMO_CP
    assert session["user"]["is_fake"] is True


# ── From the demo to a real town: yes, with nothing in the pocket ─────


async def test_leaving_the_demo_empties_the_balance(client, db_session, capture_otp):
    await malgrat(db_session)
    await catalog(db_session)
    await db_session.commit()
    session = await _signup(client, capture_otp, "amiga@test.cat", DEMO_CP)
    await _earn(db_session, "amiga@test.cat", 500)
    welcome = session["user"]["points"]

    moved = await _move(client, _bearer(session), "08380")

    assert moved["postal_code"] == "08380"
    assert moved["is_fake"] is False
    assert moved["points"] == 0
    # Every point has its movement, and the exit is written on the demo side.
    ledger = await _ledger(db_session, "amiga@test.cat")
    assert (TX_DEMO_EXIT, -(welcome + 500), True) in ledger
    assert sum(points for _type, points, _fake in ledger) == 0


async def test_a_real_resident_cannot_go_back_to_the_demo(
    client, db_session, capture_otp
):
    await malgrat(db_session)
    await catalog(db_session)
    await db_session.commit()
    session = await _signup(client, capture_otp, "amiga@test.cat", DEMO_CP)
    await _move(client, _bearer(session), "08380")

    back = await _move(client, _bearer(session), DEMO_CP)

    assert back["postal_code"] == "08380" and back["is_fake"] is False


# ── From a real town to the demo: never ───────────────────────────────


async def test_a_real_resident_does_not_enter_the_demo(
    client, db_session, capture_otp
):
    """The app in demo mode sends 00000 when a real resident logs in."""
    await malgrat(db_session)
    await catalog(db_session)
    await db_session.commit()
    session = await _signup(client, capture_otp, "vei@test.cat", "08380")
    points = session["user"]["points"]
    assert points > 0

    same = await _move(client, _bearer(session), DEMO_CP)

    assert same["postal_code"] == "08380"
    assert same["is_fake"] is False
    assert same["points"] == points


async def test_looking_at_the_demo_does_not_change_the_account(
    client, db_session, capture_otp
):
    """The list of shops used to flip the account to the side of the town
    it was asked about."""
    await malgrat(db_session)
    demo = await catalog(db_session)
    db_session.add(
        Shop(
            town_id=demo.id,
            name="[DEMO] Forn",
            contact_email="forn-demo@test.cat",
            status="active",
            is_fake=True,
            qr_code="demo-token",
        )
    )
    await db_session.commit()
    session = await _signup(client, capture_otp, "vei@test.cat", "08380")
    headers = _bearer(session)

    r = await client.get(
        f"{API}/shops/for-me", headers=headers, params={"postal_code": DEMO_CP}
    )
    assert r.status_code == 200 and r.json() == []
    r = await client.post(
        f"{API}/scans", headers=headers, json={"qr_code": "demo-token"}
    )
    assert r.status_code == 404
    me = (await client.get(f"{API}/users/me", headers=headers)).json()
    assert (me["postal_code"], me["is_fake"]) == ("08380", False)


# ── What stays as it was ──────────────────────────────────────────────


async def test_moving_between_real_towns_keeps_the_points(
    client, db_session, capture_otp
):
    await malgrat(db_session)
    await single_town(db_session, "Blanes", "17300")
    await db_session.commit()
    session = await _signup(client, capture_otp, "vei@test.cat", "08380")
    points = session["user"]["points"]

    moved = await _move(client, _bearer(session), "17300")

    assert moved["postal_code"] == "17300"
    assert moved["points"] == points > 0


async def test_a_postal_code_is_not_cleared(client, db_session, capture_otp):
    """Clearing it was the way round: real -> none -> demo."""
    await malgrat(db_session)
    await catalog(db_session)
    await db_session.commit()
    session = await _signup(client, capture_otp, "vei@test.cat", "08380")

    cleared = await _move(client, _bearer(session), None)
    assert cleared["postal_code"] == "08380"
    still = await _move(client, _bearer(session), DEMO_CP)
    assert still["postal_code"] == "08380"


async def test_an_account_without_a_town_can_pick_either(
    client, db_session, capture_otp
):
    await malgrat(db_session)
    await catalog(db_session)
    await db_session.commit()
    await client.post(f"{API}/auth/request-otp", json={"email": "nou@test.cat"})
    r = await client.post(
        f"{API}/auth/verify-otp", json={"email": "nou@test.cat", "code": capture_otp()}
    )
    session = r.json()
    assert session["user"]["postal_code"] is None

    placed = await _move(client, _bearer(session), DEMO_CP)
    assert placed["postal_code"] == DEMO_CP and placed["is_fake"] is True


async def test_whoever_runs_a_demo_shop_stays_in_the_demo(client, db_session):
    await malgrat(db_session)
    demo = await catalog(db_session)
    shop = Shop(
        town_id=demo.id,
        name="[DEMO] Forn",
        contact_email="forn-demo@test.cat",
        status="active",
        is_fake=True,
    )
    db_session.add(shop)
    await db_session.flush()
    owner = User(
        email="forn-demo@test.cat",
        slug="forn-demo",
        postal_code=DEMO_CP,
        shop_id=shop.id,
        points=300,
        is_fake=True,
        **flags_from_roles(["resident", "merchant"]),
    )
    db_session.add(owner)
    await db_session.commit()
    token = create_access_token(
        owner.id, roles=["resident", "merchant"], town_id=demo.id, shop_id=shop.id
    )

    same = await _move(client, {"Authorization": f"Bearer {token}"}, "08380")

    assert same["postal_code"] == DEMO_CP and same["points"] == 300


async def test_the_invitation_link_follows_its_owner(client, db_session, capture_otp):
    """It rewards within one municipality: left behind in the demo, the
    friends invited from the real town would count for nobody."""
    town = await malgrat(db_session)
    await catalog(db_session)
    await db_session.commit()
    session = await _signup(client, capture_otp, "amiga@test.cat", DEMO_CP)
    headers = _bearer(session)
    r = await client.get(
        f"{API}/invites/me/link", headers=headers, params={"kind": "person"}
    )
    assert r.status_code == 200, r.text

    await _move(client, headers, "08380")

    link = (await db_session.execute(select(InvitationLink))).scalars().one()
    await db_session.refresh(link)
    assert link.town_id == town.id
