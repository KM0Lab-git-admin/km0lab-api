"""Invitation circuit: last-click, conversions, rewards, public shop signup."""

from __future__ import annotations

import pytest

from app.models import PointAction, Shop, Town, TownPostalCode, User
from app.roles import flags_from_roles
from app.security import create_access_token
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio


async def _town(db_session, name="InviteTown", postal_code="08380"):
    town = Town(
        name=name,
        slug=slugify(name) + postal_code,
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{slugify(name)}.cat",
        manager_name="Admin",
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(
            postal_code=postal_code, town_id=town.id, is_primary=True
        )
    )
    await db_session.flush()
    return town, postal_code


async def _signup(client, capture_otp, email, *, postal_code=None, invite_code=None):
    body = {"email": email}
    if postal_code:
        body["postal_code"] = postal_code
    if invite_code:
        body["invite_code"] = invite_code
    await client.post("/api/v1/auth/request-otp", json=body)
    code = capture_otp()
    verify = {"email": email, "code": code}
    if postal_code:
        verify["postal_code"] = postal_code
    if invite_code:
        verify["invite_code"] = invite_code
    r = await client.post("/api/v1/auth/verify-otp", json=verify)
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_guest_share_awards_no_points(client, capture_otp, db_session):
    town, cp = await _town(db_session)
    await db_session.commit()
    data = await _signup(client, capture_otp, "guest@test.cat", postal_code=cp)
    assert data["user"]["points"] == 100
    token = data["access_token"]
    r = await client.get("/api/v1/invites/me/summary", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["persons_registered"] == 0
    assert r.json()["points_earned"] == 0


async def test_person_web_signup_awards_inviter_once(
    client, capture_otp, db_session
):
    town, cp = await _town(db_session, "PersonTown", "08410")
    db_session.add(
        PointAction(
            town_id=town.id,
            type="invite_person",
            name="Invita veí",
            points=100,
            active=True,
            visible_home=False,
            is_fake=False,
        )
    )
    await db_session.commit()

    inviter = await _signup(
        client, capture_otp, "inviter@test.cat", postal_code=cp
    )
    token = inviter["access_token"]
    r = await client.get(
        "/api/v1/invites/me/link",
        params={"kind": "person"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    code = r.json()["public_code"]

    r = await client.post("/api/v1/invites/resolve", json={"code": code})
    assert r.status_code == 200
    assert r.json()["valid"] is True
    assert r.json()["kind"] == "person"

    invitee = await _signup(
        client,
        capture_otp,
        "invitee@test.cat",
        postal_code=cp,
        invite_code=code,
    )
    assert invitee["user"]["points"] == 100

    r = await client.get("/api/v1/invites/me/summary", headers=_auth(token))
    body = r.json()
    assert body["persons_registered"] == 1
    assert body["points_earned"] == 100

    r = await client.get("/api/v1/users/me", headers=_auth(token))
    assert r.json()["points"] == 200  # welcome 100 + invite 100


async def test_existing_account_login_does_not_convert(
    client, capture_otp, db_session
):
    town, cp = await _town(db_session, "ExistTown", "08411")
    await db_session.commit()
    first = await _signup(
        client, capture_otp, "already@test.cat", postal_code=cp
    )
    inviter = await _signup(
        client, capture_otp, "host@test.cat", postal_code=cp
    )
    r = await client.get(
        "/api/v1/invites/me/link",
        params={"kind": "person"},
        headers=_auth(inviter["access_token"]),
    )
    code = r.json()["public_code"]
    await _signup(
        client,
        capture_otp,
        "already@test.cat",
        postal_code=cp,
        invite_code=code,
    )
    r = await client.get(
        "/api/v1/invites/me/summary",
        headers=_auth(inviter["access_token"]),
    )
    assert r.json()["persons_registered"] == 0
    assert first["user"]["id"]


async def test_last_click_wins(client, capture_otp, db_session):
    town, cp = await _town(db_session, "ClickTown", "08412")
    await db_session.commit()
    a = await _signup(client, capture_otp, "a@test.cat", postal_code=cp)
    b = await _signup(client, capture_otp, "b@test.cat", postal_code=cp)
    code_a = (
        await client.get(
            "/api/v1/invites/me/link",
            params={"kind": "person"},
            headers=_auth(a["access_token"]),
        )
    ).json()["public_code"]
    code_b = (
        await client.get(
            "/api/v1/invites/me/link",
            params={"kind": "person"},
            headers=_auth(b["access_token"]),
        )
    ).json()["public_code"]

    await client.post(
        "/api/v1/auth/request-otp",
        json={"email": "last@test.cat", "invite_code": code_a, "postal_code": cp},
    )
    otp = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp",
        json={
            "email": "last@test.cat",
            "code": otp,
            "invite_code": code_b,
            "postal_code": cp,
        },
    )
    assert r.status_code == 200, r.text
    summary_a = (
        await client.get(
            "/api/v1/invites/me/summary", headers=_auth(a["access_token"])
        )
    ).json()
    summary_b = (
        await client.get(
            "/api/v1/invites/me/summary", headers=_auth(b["access_token"])
        )
    ).json()
    assert summary_a["persons_registered"] == 0
    assert summary_b["persons_registered"] == 1


async def test_self_referral_ignored(client, capture_otp, db_session):
    town, cp = await _town(db_session, "SelfTown", "08413")
    await db_session.commit()
    me = await _signup(client, capture_otp, "self@test.cat", postal_code=cp)
    code = (
        await client.get(
            "/api/v1/invites/me/link",
            params={"kind": "person"},
            headers=_auth(me["access_token"]),
        )
    ).json()["public_code"]
    await _signup(
        client,
        capture_otp,
        "self@test.cat",
        postal_code=cp,
        invite_code=code,
    )
    r = await client.get(
        "/api/v1/invites/me/summary", headers=_auth(me["access_token"])
    )
    assert r.json()["persons_registered"] == 0
    r = await client.get("/api/v1/users/me", headers=_auth(me["access_token"]))
    assert r.json()["points"] == 100


async def test_invalid_code_resolve(client):
    r = await client.post("/api/v1/invites/resolve", json={"code": "nope000000"})
    assert r.status_code == 200
    assert r.json()["valid"] is False


async def test_verify_otp_repeat_does_not_double_grant(
    client, capture_otp, db_session
):
    town, cp = await _town(db_session, "RepeatTown", "08414")
    await db_session.commit()
    inviter = await _signup(
        client, capture_otp, "rep-host@test.cat", postal_code=cp
    )
    code = (
        await client.get(
            "/api/v1/invites/me/link",
            params={"kind": "person"},
            headers=_auth(inviter["access_token"]),
        )
    ).json()["public_code"]
    await _signup(
        client,
        capture_otp,
        "rep-guest@test.cat",
        postal_code=cp,
        invite_code=code,
    )
    await _signup(
        client,
        capture_otp,
        "rep-guest@test.cat",
        postal_code=cp,
        invite_code=code,
    )
    r = await client.get(
        "/api/v1/invites/me/summary", headers=_auth(inviter["access_token"])
    )
    assert r.json()["persons_registered"] == 1
    assert r.json()["points_earned"] == 100


async def test_town_mismatch_skips_reward(client, capture_otp, db_session):
    town_a, cp_a = await _town(db_session, "TownA", "08415")
    _town_b, cp_b = await _town(db_session, "TownB", "08416")
    await db_session.commit()
    inviter = await _signup(
        client, capture_otp, "town-a@test.cat", postal_code=cp_a
    )
    code = (
        await client.get(
            "/api/v1/invites/me/link",
            params={"kind": "person"},
            headers=_auth(inviter["access_token"]),
        )
    ).json()["public_code"]
    await _signup(
        client,
        capture_otp,
        "town-b@test.cat",
        postal_code=cp_b,
        invite_code=code,
    )
    r = await client.get(
        "/api/v1/invites/me/summary", headers=_auth(inviter["access_token"])
    )
    assert r.json()["persons_registered"] == 0


async def test_preview_bot_does_not_convert(client, capture_otp, db_session):
    town, cp = await _town(db_session, "BotTown", "08417")
    await db_session.commit()
    inviter = await _signup(
        client, capture_otp, "bot-host@test.cat", postal_code=cp
    )
    code = (
        await client.get(
            "/api/v1/invites/me/link",
            params={"kind": "person"},
            headers=_auth(inviter["access_token"]),
        )
    ).json()["public_code"]
    r = await client.post(
        "/api/v1/invites/resolve",
        json={"code": code},
        headers={"User-Agent": "facebookexternalhit/1.1"},
    )
    assert r.json()["valid"] is True
    r = await client.get(
        "/api/v1/invites/me/summary", headers=_auth(inviter["access_token"])
    )
    assert r.json()["persons_registered"] == 0


async def test_business_public_signup_and_otp(
    client, capture_otp, db_session
):
    town, cp = await _town(db_session, "BizTown", "08418")
    db_session.add(
        PointAction(
            town_id=town.id,
            type="invite_business",
            name="Invita comerç",
            points=500,
            active=True,
            visible_home=False,
            is_fake=False,
        )
    )
    await db_session.commit()
    inviter = await _signup(
        client, capture_otp, "biz-host@test.cat", postal_code=cp
    )
    code = (
        await client.get(
            "/api/v1/invites/me/link",
            params={"kind": "business"},
            headers=_auth(inviter["access_token"]),
        )
    ).json()["public_code"]

    r = await client.post(
        "/api/v1/shops/public-signup",
        json={
            "name": "Forn Nou",
            "tax_id": "B12345678",
            "categories": [],
            "contact_email": "forn@test.cat",
            "postal_code": cp,
            "invite_code": code,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["needs_otp"] is True
    assert r.json()["status"] == "pending"

    merchant = await _signup(
        client, capture_otp, "forn@test.cat", postal_code=cp
    )
    assert "merchant" in merchant["user"]["roles"]
    r = await client.get(
        "/api/v1/invites/me/summary", headers=_auth(inviter["access_token"])
    )
    assert r.json()["businesses_registered"] == 1
    assert r.json()["points_earned"] == 500


async def test_resident_not_merchant_activates_own_shop(
    client, capture_otp, db_session
):
    town, cp = await _town(db_session, "ResBiz", "08419")
    await db_session.commit()
    inviter = await _signup(
        client, capture_otp, "res-host@test.cat", postal_code=cp
    )
    code = (
        await client.get(
            "/api/v1/invites/me/link",
            params={"kind": "business"},
            headers=_auth(inviter["access_token"]),
        )
    ).json()["public_code"]
    resident = await _signup(
        client, capture_otp, "resident-biz@test.cat", postal_code=cp
    )
    r = await client.post(
        "/api/v1/shops/public-signup",
        json={
            "name": "Bar Resident",
            "tax_id": "B87654321",
            "contact_email": "resident-biz@test.cat",
            "postal_code": cp,
            "invite_code": code,
        },
        headers=_auth(resident["access_token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["needs_otp"] is False
    assert r.json()["status"] == "active"
    r = await client.get(
        "/api/v1/invites/me/summary", headers=_auth(inviter["access_token"])
    )
    assert r.json()["businesses_registered"] == 1


async def test_already_merchant_not_eligible(client, capture_otp, db_session):
    town, cp = await _town(db_session, "MerchTown", "08420")
    shop = Shop(
        town_id=town.id,
        name="Old Shop",
        contact_email="old@test.cat",
        status="active",
        is_fake=False,
    )
    db_session.add(shop)
    await db_session.flush()
    merchant = User(
        email="old-merch@test.cat",
        slug="old-merch",
        postal_code=cp,
        shop_id=shop.id,
        points=0,
        **flags_from_roles(["resident", "merchant"]),
    )
    db_session.add(merchant)
    await db_session.commit()
    token = create_access_token(
        merchant.id, roles=["resident", "merchant"], town_id=town.id, shop_id=shop.id
    )
    r = await client.post(
        "/api/v1/shops/public-signup",
        json={
            "name": "Second Shop",
            "tax_id": "B00000001",
            "contact_email": "old-merch@test.cat",
            "postal_code": cp,
        },
        headers=_auth(token),
    )
    assert r.status_code == 400


async def test_admin_retry_reward_idempotent(client, capture_otp, db_session):
    town, cp = await _town(db_session, "AdminTown", "08421")
    await db_session.commit()
    inviter = await _signup(
        client, capture_otp, "adm-host@test.cat", postal_code=cp
    )
    code = (
        await client.get(
            "/api/v1/invites/me/link",
            params={"kind": "person"},
            headers=_auth(inviter["access_token"]),
        )
    ).json()["public_code"]
    await _signup(
        client,
        capture_otp,
        "adm-guest@test.cat",
        postal_code=cp,
        invite_code=code,
    )
    admin = User(
        email="town-admin@test.cat",
        slug="town-admin",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()
    token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    listed = await client.get("/api/v1/admin/invites", headers=_auth(token))
    assert listed.status_code == 200, listed.text
    conv = listed.json()["conversions"][0]
    before = (
        await client.get("/api/v1/users/me", headers=_auth(inviter["access_token"]))
    ).json()["points"]
    r = await client.post(
        f"/api/v1/admin/invites/conversions/{conv['id']}/retry-reward",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    after = (
        await client.get("/api/v1/users/me", headers=_auth(inviter["access_token"]))
    ).json()["points"]
    assert after == before


async def test_link_reused_per_kind(client, capture_otp, db_session):
    town, cp = await _town(db_session, "ReuseTown", "08422")
    await db_session.commit()
    inviter = await _signup(
        client, capture_otp, "reuse@test.cat", postal_code=cp
    )
    headers = _auth(inviter["access_token"])
    a = await client.get(
        "/api/v1/invites/me/link", params={"kind": "person"}, headers=headers
    )
    b = await client.get(
        "/api/v1/invites/me/link", params={"kind": "person"}, headers=headers
    )
    assert a.json()["public_code"] == b.json()["public_code"]
    biz = await client.get(
        "/api/v1/invites/me/link", params={"kind": "business"}, headers=headers
    )
    assert biz.json()["public_code"] != a.json()["public_code"]
