"""A shop joins: the administrator registers it, the owner logs in, prints
the QR and a resident scans it.

Registering a shop with someone's email is the invitation: nothing is sent,
and the first time that person logs in the shop is theirs. These tests fix
the ways that used to go wrong in the backoffice.
"""

import pytest

from app.config import get_settings
from app.models import ShopMedia, User
from app.services.shop_qr import build_scan_url, render_qr_png
from tests._municipalities import API, admin_headers, malgrat, single_town

pytestmark = pytest.mark.asyncio

OWNER = "forn@test.cat"
PNG = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]) + b"0" * 32


async def _login(client, capture_otp, email: str) -> dict:
    r = await client.post(f"{API}/auth/request-otp", json={"email": email})
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{API}/auth/verify-otp", json={"email": email, "code": capture_otp()}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


async def _register(client, admin: dict, email: str = OWNER, name: str = "Forn Nou"):
    r = await client.post(
        f"{API}/shops",
        headers=admin,
        json={"name": name, "contact_email": email, "categories": ["bakery"]},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _set_status(client, admin: dict, shop: dict, status: str) -> None:
    r = await client.patch(
        f"{API}/shops/{shop['id']}", headers=admin, json={"status": status}
    )
    assert r.status_code == 200, r.text


# ── From the registration to the first points ─────────────────────────


async def test_owner_logs_in_prints_the_qr_and_a_resident_scans_it(
    client, db_session, capture_otp
):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    shop = await _register(client, admin)
    assert shop["status"] == "pending"

    # Nobody can collect a visit before the owner has come in.
    resident = _bearer(await _login(client, capture_otp, "veina@test.cat"))
    r = await client.post(
        f"{API}/scans", headers=resident, json={"qr_code": shop["qr_code"]}
    )
    assert r.status_code == 404

    owner = await _login(client, capture_otp, OWNER)
    assert set(owner["user"]["roles"]) == {"resident", "merchant"}
    assert owner["user"]["shop_id"] == shop["id"]

    r = await client.get(f"{API}/shops/me/qr", headers=_bearer(owner))
    assert r.status_code == 200, r.text
    qr = r.json()
    assert qr["scan_url"].endswith(f"?c={shop['qr_code']}")
    png = await client.get(qr["png_url"], headers=_bearer(owner))
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert png.content == render_qr_png(qr["scan_url"])

    r = await client.post(
        f"{API}/scans", headers=resident, json={"qr_code": shop["qr_code"]}
    )
    assert r.status_code == 201, r.text
    assert r.json()["points"] == town.default_visit_points


# ── What the administrator may do before the owner comes in ───────────


async def test_switching_the_shop_on_first_does_not_lock_the_owner_out(
    client, db_session, capture_otp
):
    """A new shop looks switched off in the backoffice; flipping the switch
    is the obvious thing to do, and it must not cost the owner the shop."""
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    shop = await _register(client, admin)
    await _set_status(client, admin, shop, "active")

    owner = await _login(client, capture_otp, OWNER)
    assert "merchant" in owner["user"]["roles"]
    assert owner["user"]["shop_id"] == shop["id"]


async def test_a_shop_switched_off_is_given_to_nobody(
    client, db_session, capture_otp
):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    shop = await _register(client, admin)
    await _set_status(client, admin, shop, "inactive")

    owner = await _login(client, capture_otp, OWNER)
    assert owner["user"]["roles"] == ["resident"]
    assert owner["user"]["shop_id"] is None

    # Switched back on, the next login gets it.
    await _set_status(client, admin, shop, "active")
    owner = await _login(client, capture_otp, OWNER)
    assert owner["user"]["shop_id"] == shop["id"]


async def test_administrator_using_their_own_email_can_still_log_in(
    client, db_session, capture_otp
):
    """It used to answer 400 for ever: the administrator was locked out."""
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    admin_email = "admin-malgrat-de-mar@test.cat"
    shop = await _register(client, admin, email=admin_email)

    session = await _login(client, capture_otp, admin_email)
    assert "admin" in session["user"]["roles"]
    assert "merchant" not in session["user"]["roles"]
    r = await client.get(f"{API}/shops/{shop['id']}", headers=_bearer(session))
    assert r.json()["status"] == "pending"


async def test_an_owner_is_not_moved_to_a_second_shop(
    client, db_session, capture_otp
):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    first = await _register(client, admin, name="Forn Nou")
    owner = await _login(client, capture_otp, OWNER)
    assert owner["user"]["shop_id"] == first["id"]

    await _register(client, admin, name="Forn Nou 2")
    owner = await _login(client, capture_otp, OWNER)
    assert owner["user"]["shop_id"] == first["id"]


async def test_a_shop_with_its_owner_is_not_given_to_someone_else(
    client, db_session, capture_otp
):
    """Changing the contact email of a running shop hands it to nobody."""
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    shop = await _register(client, admin)
    await _login(client, capture_otp, OWNER)

    r = await client.patch(
        f"{API}/shops/{shop['id']}",
        headers=admin,
        json={"contact_email": "altre@test.cat"},
    )
    assert r.status_code == 200, r.text
    other = await _login(client, capture_otp, "altre@test.cat")
    assert other["user"]["roles"] == ["resident"]
    owners = (
        await db_session.execute(
            User.__table__.select().where(User.shop_id == shop["id"])
        )
    ).all()
    assert [row.email for row in owners] == [OWNER]


# ── Who may hold the picture of the QR ───────────────────────────────


async def test_qr_picture_is_only_for_the_shop_and_its_administrator(
    client, db_session, capture_otp
):
    """The picture is the scan code: with it, the visit is collected from
    home. The shop's id is public (it is in the list of shops), so the
    picture must not be."""
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    shop = await _register(client, admin)
    owner = _bearer(await _login(client, capture_otp, OWNER))
    url = (await client.get(f"{API}/shops/me/qr", headers=owner)).json()["png_url"]

    assert (await client.get(url, headers=owner)).status_code == 200
    assert (await client.get(url, headers=admin)).status_code == 200

    resident = _bearer(await _login(client, capture_otp, "veina@test.cat"))
    other_town = await single_town(db_session, "Blanes", "17300")
    other_admin = await admin_headers(db_session, other_town, "17300")
    await _register(client, other_admin, email="altra@test.cat", name="Altra")
    other_owner = _bearer(await _login(client, capture_otp, "altra@test.cat"))
    for nobody in ({}, resident, other_admin, other_owner):
        r = await client.get(f"{API}/shops/{shop['id']}/media/qr", headers=nobody)
        assert r.status_code == 404

    # The logo stays public: the app shows it without a session.
    r = await client.put(
        f"{API}/shops/me/media/logo",
        headers=owner,
        files={"file": ("logo.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert (await client.get(f"{API}/shops/{shop['id']}/media/logo")).status_code == 200


# ── The address inside the QR ─────────────────────────────────────────


async def test_qr_is_redrawn_when_its_address_changes(
    client, db_session, capture_otp, monkeypatch
):
    """Shops registered before ``QR_SCAN_BASE_URL`` was set must not keep
    handing out a QR to the old address."""
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    shop = await _register(client, admin)
    owner = _bearer(await _login(client, capture_otp, OWNER))
    before = (await client.get(f"{API}/shops/me/qr", headers=owner)).json()

    monkeypatch.setattr(
        get_settings(), "qr_scan_base_url", "https://app.uat.km0lab.com/scan"
    )
    after = (await client.get(f"{API}/shops/me/qr", headers=owner)).json()

    assert after["qr_code"] == before["qr_code"] == shop["qr_code"]
    assert after["scan_url"] == f"https://app.uat.km0lab.com/scan?c={shop['qr_code']}"
    assert after["scan_url"] == build_scan_url(shop["qr_code"])
    # A new picture, under a new address so no browser shows the old one.
    assert after["png_url"] != before["png_url"]
    png = await client.get(after["png_url"], headers=owner)
    assert png.content == render_qr_png(after["scan_url"])
    rows = (
        await db_session.execute(
            ShopMedia.__table__.select().where(
                ShopMedia.shop_id == shop["id"], ShopMedia.kind == "qr"
            )
        )
    ).all()
    assert len(rows) == 1
