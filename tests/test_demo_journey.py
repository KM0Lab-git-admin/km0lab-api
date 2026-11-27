"""The demonstration from start to finish, as friends would try it.

Albert's example (27-11-2026): someone does the demo with friends. They
sign up, scan QRs, earn points and invite each other. Everything works
except collecting the reward; and none of it reaches a real municipality.
"""

import re

import pytest
from sqlalchemy import func, select

from app.models import Shop, User
from app.services.pilot_points import set_pilot_points
from app.services.shop_qr import ensure_shop_qr
from tests._municipalities import API, admin_headers, catalog, malgrat

pytestmark = pytest.mark.asyncio

DEMO_CP = "00000"


async def _demo_as_in_uat(db):
    """Malgrat and Demo KM0 with six make-believe shops, on the pilot's
    points (signing up 50, scanning 100, inviting 50)."""
    town = await malgrat(db)
    demo = await catalog(db)
    for n in range(6):
        shop = Shop(
            town_id=demo.id,
            name=f"[DEMO] Comerç {n}",
            contact_email=f"demo{n}@test.cat",
            status="active",
            is_fake=True,
        )
        db.add(shop)
        await db.flush()
        await ensure_shop_qr(db, shop)
    for each in (town, demo):
        await set_pilot_points(db, each, apply=True)
    await db.commit()
    return town, demo


async def _signup(client, capture_otp, email: str, invite: str | None = None) -> dict:
    body = {"email": email}
    if invite:
        body["invite_code"] = invite
    r = await client.post(f"{API}/auth/request-otp", json=body)
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={**body, "code": capture_otp(), "postal_code": DEMO_CP},
    )
    assert r.status_code == 200, r.text
    session = r.json()
    session["headers"] = {"Authorization": f"Bearer {session['access_token']}"}
    return session


async def _points(client, session: dict) -> int:
    r = await client.get(f"{API}/users/me", headers=session["headers"])
    return r.json()["points"]


async def test_friends_do_the_whole_demo_and_nothing_leaks(
    client, db_session, capture_otp
):
    town, demo = await _demo_as_in_uat(db_session)
    malgrat_admin = await admin_headers(db_session, town, "08380")

    # 1. Anna signs up from the demo: 50 points, a demo account.
    anna = await _signup(client, capture_otp, "anna@test.cat")
    assert anna["user"]["is_fake"] is True
    assert await _points(client, anna) == 50

    # 2. She scans the QRs of the sheet with the app: 100 each, once each.
    sheet = (await client.get(f"{API}/demo/qr")).text
    assert len(re.findall(r"<figure>", sheet)) == 5
    shops = (
        await client.get(f"{API}/shops/for-me", headers=anna["headers"])
    ).json()
    assert len(shops) == 6
    codes = (
        await db_session.execute(
            select(Shop.qr_code).where(Shop.town_id == demo.id).order_by(Shop.name)
        )
    ).scalars().all()
    for code in codes[:2]:
        r = await client.post(
            f"{API}/scans", headers=anna["headers"], json={"qr_code": code}
        )
        assert r.status_code == 201 and r.json()["points"] == 100
    again = await client.post(
        f"{API}/scans", headers=anna["headers"], json={"qr_code": codes[0]}
    )
    assert again.status_code == 409
    assert again.json()["detail"]["cooldown_days"] == 365
    assert await _points(client, anna) == 250

    # 3. She invites Pol. Sharing pays nothing; his signup pays her 50.
    link = (
        await client.get(
            f"{API}/invites/me/link", headers=anna["headers"], params={"kind": "person"}
        )
    ).json()
    assert await _points(client, anna) == 250
    pol = await _signup(client, capture_otp, "pol@test.cat", invite=link["public_code"])
    assert await _points(client, pol) == 50
    assert await _points(client, anna) == 300

    # 4. Pol scans too, and both see offers and rewards of the demo.
    r = await client.post(
        f"{API}/scans", headers=pol["headers"], json={"qr_code": codes[0]}
    )
    assert r.status_code == 201
    rewards = (
        await client.get(f"{API}/rewards/public", params={"postal_code": DEMO_CP})
    ).json()
    cheapest = next(r for r in rewards if r["name"].endswith("Bono 5 €"))
    assert cheapest["points_required"] == 500  # 100 points = 1 EUR

    # 5. Anna cannot afford it yet; with three more scans she redeems it.
    r = await client.post(
        f"{API}/redemptions", headers=anna["headers"], json={"reward_id": cheapest["id"]}
    )
    assert r.status_code >= 400
    for code in codes[2:5]:
        await client.post(
            f"{API}/scans", headers=anna["headers"], json={"qr_code": code}
        )
    r = await client.post(
        f"{API}/redemptions", headers=anna["headers"], json={"reward_id": cheapest["id"]}
    )
    assert r.status_code == 201, r.text
    assert await _points(client, anna) == 100

    # ── None of it exists for a real municipality ─────────────────────
    residents = (await client.get(f"{API}/residents", headers=malgrat_admin)).json()
    listed = residents["items"] if isinstance(residents, dict) else residents
    # (The administrator is a resident of their own town: only they are there.)
    assert [r["email"] for r in listed] == ["admin-malgrat-de-mar@test.cat"]
    real_accounts = await db_session.scalar(
        select(func.count()).select_from(User).where(
            User.is_fake.is_(False), User.email.in_(["anna@test.cat", "pol@test.cat"])
        )
    )
    assert real_accounts == 0

    # ── And the points do not travel ──────────────────────────────────
    # Logging in from a phone set to Malgrat does not move him by itself.
    r = await client.patch(
        f"{API}/users/me", headers=pol["headers"], json={"postal_code": "08380"}
    )
    assert r.json()["postal_code"] == DEMO_CP and r.json()["points"] == 150
    # His town joins the pilot and he says yes: same email, a real resident
    # with the welcome of Malgrat and nothing of what he earned playing.
    r = await client.patch(
        f"{API}/users/me",
        headers=pol["headers"],
        json={"postal_code": "08380", "leave_demo": True},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["is_fake"], r.json()["points"]) == (False, 50)
    # A demo QR is worth nothing to him now.
    r = await client.post(
        f"{API}/scans", headers=pol["headers"], json={"qr_code": codes[1]}
    )
    assert r.status_code == 404
