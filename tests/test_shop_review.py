"""A shop that asks to join waits for its municipality's administrator.

Covers the request (who may send it, what the machine refuses), that nothing
of a held shop is public, who decides, the emails and the 30-day deletion.
The payment to whoever invited the shop is in ``test_invites.py``.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.catalog.email_shop_review import (
    ADMIN_NEW,
    APPROVED,
    RECEIVED,
    REJECTED,
    REVIEW_COPY,
    render_review_html,
    render_review_text,
    review_email_subject,
)
from app.config import get_settings
from app.email import send_shop_review_email
from app.models import Shop, ShopMedia, User
from app.qa import QA_POSTAL_CODE
from app.roles import flags_from_roles
from app.security import create_access_token
from app.services.qa_territory import ensure_qa_territory
from app.services.shop_review import names_look_alike, purge_rejected_shops
from app.services.towns import ensure_demo_town
from tests._municipalities import API, admin_headers, baix_montseny, malgrat

pytestmark = pytest.mark.asyncio

PANEL = "https://backoffice.uat.km0lab.com"
KINDS = (RECEIVED, APPROVED, REJECTED, ADMIN_NEW)


async def _person(db, email: str, *, postal_code=None, is_fake=False) -> dict[str, str]:
    """Someone logged in with ``email``: what the code in the email proves."""
    user = User(
        email=email,
        slug=email.split("@")[0].replace("+", "-"),
        postal_code=postal_code,
        points=0,
        is_fake=is_fake,
        **flags_from_roles(["resident"]),
    )
    db.add(user)
    await db.commit()
    token = create_access_token(user.id, roles=["resident"], town_id=None, shop_id=None)
    return {"Authorization": f"Bearer {token}"}


def _request(email: str, **over) -> dict:
    return {
        "name": "Forn de la Plaça",
        "tax_id": "B12345674",
        "contact_email": email,
        "postal_code": "08380",
        "phone": "937000000",
        **over,
    }


async def _ask(client, headers, email: str, **over):
    return await client.post(
        f"{API}/shops/public-signup", json=_request(email, **over), headers=headers
    )


@pytest.fixture
def outbox(monkeypatch):
    """Every email of a request that would have gone out: (kind, to, reason)."""
    sent: list[tuple[str, str, str | None]] = []

    async def fake(kind, to, *, shop_name, town, reason=None, lang=None):
        sent.append((kind, to, reason))
        return True

    monkeypatch.setattr("app.api.shops.send_shop_review_email", fake)
    return sent


# ── The request ───────────────────────────────────────────────────────


async def test_request_carries_the_session_of_whoever_asks(client, db_session, outbox):
    await malgrat(db_session)
    forn = await _person(db_session, "forn@test.cat")

    r = await client.post(f"{API}/shops/public-signup", json=_request("forn@test.cat"))
    assert r.status_code in (401, 403)
    # The contact email is the confirmed one: nobody asks in another's name.
    r = await _ask(client, forn, "altre@test.cat")
    assert r.status_code == 403 and r.json()["detail"] == "email_not_verified"
    assert outbox == []

    r = await _ask(client, forn, "forn@test.cat", tax_id="b-12.345.674")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "review" and r.json()["needs_otp"] is False
    shop = await db_session.get(Shop, r.json()["shop_id"])
    assert shop.tax_id == "B12345674"


async def test_machine_refuses_what_it_can_tell_is_wrong(client, db_session, outbox):
    await malgrat(db_session)
    await baix_montseny(db_session)
    await ensure_demo_town(db_session)
    await ensure_qa_territory(db_session)
    forn = await _person(db_session, "forn@test.cat")
    peix = await _person(db_session, "peix@test.cat")

    r = await _ask(client, forn, "forn@test.cat", tax_id="B12345678")
    assert r.status_code == 422 and r.json()["detail"] == "tax_id_invalid"
    r = await _ask(client, forn, "forn@test.cat", postal_code="46001")
    assert r.status_code == 400 and r.json()["detail"] == "Unknown postal code"
    # Neither Demo nor, for a real account, the test territory.
    for code in ("00000", QA_POSTAL_CODE):
        r = await _ask(client, forn, "forn@test.cat", postal_code=code)
        assert r.status_code == 400 and r.json()["detail"] == "postal_code_not_allowed"
    assert outbox == []

    assert (await _ask(client, forn, "forn@test.cat")).status_code == 200
    # One standing request per email...
    r = await _ask(client, forn, "forn@test.cat", tax_id="A58818501")
    assert r.status_code == 409
    # ...and one per tax id in a municipality.
    r = await _ask(client, peix, "peix@test.cat", name="Peixateria")
    assert r.status_code == 409 and r.json()["detail"] == "tax_id_already_registered"
    # The same company may have a shop in another municipality.
    r = await _ask(client, peix, "peix@test.cat", name="Peixateria", postal_code="17404")
    assert r.status_code == 200, r.text


# ── While it waits ────────────────────────────────────────────────────


async def test_nothing_of_a_held_shop_is_public(client, db_session, outbox):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    forn = await _person(db_session, "forn@test.cat")
    neighbour = await _person(db_session, "veina@test.cat", postal_code="08380")
    shop_id = (await _ask(client, forn, "forn@test.cat")).json()["shop_id"]
    url = f"{API}/shops/{shop_id}"

    # No QR exists, drawn or not.
    shop = await db_session.get(Shop, shop_id)
    assert shop.status == "review" and shop.qr_code is None
    assert (
        await db_session.execute(select(ShopMedia).where(ShopMedia.shop_id == shop_id))
    ).first() is None
    # Not in the list, not by its id — not even for whoever asked.
    listed = await client.get(f"{API}/shops/public", params={"postal_code": "08380"})
    assert listed.json() == []
    for headers in (neighbour, forn):
        assert (await client.get(url, headers=headers)).status_code == 404
    assert (await client.get(f"{url}/media/qr")).status_code in (401, 403, 404)

    # Whoever asked is told where it stands, and has no shop yet.
    me = (await client.get(f"{API}/users/me", headers=forn)).json()
    assert me["shop_request"] == {
        "shop_id": shop_id,
        "name": "Forn de la Plaça",
        "status": "review",
        "reason": None,
    }
    assert "merchant" not in me["roles"] and me["shop_id"] is None

    # The administrator sees it, and can only decide it by approving or
    # rejecting: switching it on by hand would skip all of that.
    waiting = await client.get(f"{API}/shops", params={"status": "review"}, headers=admin)
    assert [s["id"] for s in waiting.json()] == [shop_id]
    assert (await client.get(url, headers=admin)).json()["has_qr"] is False
    r = await client.patch(url, json={"status": "active"}, headers=admin)
    assert r.status_code == 409 and r.json()["detail"] == "shop_in_review"
    r = await client.get(
        f"{API}/shops/me/qr", headers={**admin, "X-Acting-Shop-Id": shop_id}
    )
    assert r.status_code == 409 and r.json()["detail"] == "shop_in_review"
    r = await client.patch(url, json={"phone": "937111111"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "review"


# ── Who decides ───────────────────────────────────────────────────────


async def test_only_the_municipalitys_administrator_decides(client, db_session, outbox):
    mal = await malgrat(db_session)
    baix = await baix_montseny(db_session)
    mal_admin = await admin_headers(db_session, mal, "08380")
    baix_admin = await admin_headers(db_session, baix, "17400")
    fuster = await _person(db_session, "fuster@test.cat")
    r = await _ask(client, fuster, "fuster@test.cat", name="Fusteria", postal_code="17404")
    url = f"{API}/shops/{r.json()['shop_id']}"

    for headers in (mal_admin, fuster):
        assert (await client.get(f"{url}/review", headers=headers)).status_code == 403
        assert (await client.post(f"{url}/approve", headers=headers)).status_code == 403
        r = await client.post(
            f"{url}/reject", json={"reason": "No existeix"}, headers=headers
        )
        assert r.status_code == 403
    assert (await db_session.get(Shop, url.rsplit("/", 1)[-1])).status == "review"

    r = await client.post(f"{url}/approve", headers=baix_admin)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active" and r.json()["has_qr"] is True
    assert r.json()["town_name"] == "Riells i Viabrea"
    # Now it is public, and its owner's.
    listed = await client.get(f"{API}/shops/public", params={"postal_code": "17404"})
    assert [s["name"] for s in listed.json()] == ["Fusteria"]
    me = (await client.get(f"{API}/users/me", headers=fuster)).json()
    assert "merchant" in me["roles"] and me["shop_id"] == r.json()["id"]
    assert me["shop_request"] is None
    # Decided once.
    for step, body in (("approve", None), ("reject", {"reason": "Tard"})):
        r = await client.post(f"{url}/{step}", json=body, headers=baix_admin)
        assert r.status_code == 409 and r.json()["detail"] == "shop_not_in_review"


async def test_rejecting_needs_a_reason_and_frees_the_email(client, db_session, outbox):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    forn = await _person(db_session, "forn@test.cat")
    first = (await _ask(client, forn, "forn@test.cat")).json()["shop_id"]
    url = f"{API}/shops/{first}"

    assert (await client.post(f"{url}/reject", json={}, headers=admin)).status_code == 422
    r = await client.post(f"{url}/reject", json={"reason": " "}, headers=admin)
    assert r.status_code == 422

    r = await client.post(
        f"{url}/reject", json={"reason": "No hem trobat el comerç."}, headers=admin
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    me = (await client.get(f"{API}/users/me", headers=forn)).json()
    assert me["shop_request"]["status"] == "rejected" and me["shop_id"] is None
    # The shop reads why on its screen, not only in the email.
    assert me["shop_request"]["reason"] == "No hem trobat el comerç."
    assert r.json()["review_note"] == "No hem trobat el comerç."
    listed = await client.get(f"{API}/shops/public", params={"postal_code": "08380"})
    assert listed.json() == []
    # A rejected request is left as it was until it is deleted.
    r = await client.patch(url, json={"phone": "937111111"}, headers=admin)
    assert r.status_code == 409 and r.json()["detail"] == "shop_rejected"

    # Whoever was rejected may ask again, with the same email and tax id.
    again = await _ask(client, forn, "forn@test.cat")
    assert again.status_code == 200, again.text
    me = (await client.get(f"{API}/users/me", headers=forn)).json()
    assert me["shop_request"]["shop_id"] == again.json()["shop_id"]
    assert me["shop_request"]["status"] == "review"
    assert me["shop_request"]["reason"] is None


async def test_checks_tell_the_administrator_what_to_look_at(client, db_session, outbox):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    r = await client.post(
        f"{API}/shops",
        json={"name": "Forn Pere", "contact_email": "pere@test.cat"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    nou = await _person(db_session, "nou@test.cat")
    r = await _ask(client, nou, "nou@test.cat", name="FORN  PERE, S.L.")

    checks = await client.get(f"{API}/shops/{r.json()['shop_id']}/review", headers=admin)
    assert checks.status_code == 200, checks.text
    assert checks.json() == {
        "status": "review",
        "tax_id_valid": True,
        "postal_code_in_town": True,
        "email_verified": True,
        "same_tax_id": [],
        # A warning, not a refusal: only a person knows if it is the same.
        "similar_names": ["Forn Pere"],
        "invited_by": None,
        "invite_points": 0,
    }


def test_names_that_look_the_same_to_a_person():
    assert names_look_alike("Forn Pere", "FORN  PERE, S.L.")
    assert names_look_alike("Peixateria Núria", "peixateria nuria")
    assert not names_look_alike("Forn Pere", "Forn Joan")
    assert not names_look_alike("Bar", "Barberia Sol")


# ── Emails ────────────────────────────────────────────────────────────


async def test_each_step_tells_who_has_to_know(client, db_session, outbox):
    mal = await malgrat(db_session)
    baix = await baix_montseny(db_session)
    await admin_headers(db_session, mal, "08380")
    baix_admin = await admin_headers(db_session, baix, "17400")
    fuster = await _person(db_session, "fuster@test.cat")
    forn = await _person(db_session, "forn@test.cat")

    r = await _ask(client, fuster, "fuster@test.cat", name="Fusteria", postal_code="17404")
    # Whoever asked, and the administrator of that municipality only.
    assert outbox == [
        (RECEIVED, "fuster@test.cat", None),
        (ADMIN_NEW, "admin-baix-montseny@test.cat", None),
    ]
    outbox.clear()
    await client.post(f"{API}/shops/{r.json()['shop_id']}/approve", headers=baix_admin)
    assert outbox == [(APPROVED, "fuster@test.cat", None)]
    outbox.clear()

    r = await _ask(
        client, forn, "forn@test.cat", tax_id="A58818501", postal_code="17400"
    )
    outbox.clear()
    await client.post(
        f"{API}/shops/{r.json()['shop_id']}/reject",
        json={"reason": "  Ja hi ha un altre forn amb aquest nom.  "},
        headers=baix_admin,
    )
    assert outbox == [(REJECTED, "forn@test.cat", "Ja hi ha un altre forn amb aquest nom.")]


async def test_test_shops_are_told_nothing(client, db_session, outbox):
    await ensure_qa_territory(db_session)
    qa = await _person(
        db_session, "qa+alta@km0lab.com", postal_code=QA_POSTAL_CODE, is_fake=True
    )
    r = await _ask(
        client, qa, "qa+alta@km0lab.com", name="[QA] Alta", postal_code=QA_POSTAL_CODE
    )
    assert r.status_code == 200, r.text
    assert (await db_session.get(Shop, r.json()["shop_id"])).is_fake is True
    assert outbox == []


async def test_a_failed_email_does_not_undo_the_step(client, db_session, monkeypatch):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    forn = await _person(db_session, "forn@test.cat")

    async def broken(*args, **kwargs):
        raise RuntimeError("resend is down")

    monkeypatch.setattr("app.api.shops.send_shop_review_email", broken)
    r = await _ask(client, forn, "forn@test.cat")
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/shops/{r.json()['shop_id']}/approve", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "active"


@pytest.mark.parametrize("lang", ["ca", "es", "en"])
def test_every_language_has_the_four_emails(lang):
    assert set(REVIEW_COPY[lang]) == set(KINDS)
    for kind in KINDS:
        assert set(REVIEW_COPY[lang][kind]) == set(REVIEW_COPY["ca"][kind])
        for key, text in REVIEW_COPY[lang][kind].items():
            assert text.strip(), (kind, key)
            # The panel's address always comes from configuration.
            assert "http" not in text


@pytest.mark.parametrize("lang", ["ca", "es", "en"])
@pytest.mark.parametrize("kind", KINDS)
def test_emails_render_whole_in_text_and_html(kind, lang):
    parts = dict(
        shop_name="Forn de la Plaça",
        town="Malgrat de Mar",
        reason="No hem trobat el comerç.",
        panel_url=PANEL,
        lang=lang,
    )
    text = render_review_text(kind, **parts)
    html = render_review_html(kind, **parts)
    for body in (text, html):
        assert "Forn de la Plaça" in body and "Malgrat de Mar" in body
        assert "{" not in body.split("</style>")[-1] and "${" not in body
    assert f'<html lang="{lang}"' in html
    # A button only where there is somewhere to go.
    has_button = kind in (APPROVED, ADMIN_NEW)
    assert (PANEL in text) is has_button
    assert (f'href="{PANEL}"' in html) is has_button
    assert ("No hem trobat el comerç." in text) is (kind == REJECTED)
    assert ("No hem trobat el comerç." in html) is (kind == REJECTED)


def test_the_reason_is_shown_as_written_and_never_run():
    reason = 'No és <b>aquí</b>.\nMira "això" & torna.'
    html = render_review_html(
        REJECTED, shop_name="<Forn>", town="Malgrat", reason=reason, lang="ca"
    )
    assert "No és &lt;b&gt;aquí&lt;/b&gt;.<br>Mira \"això\" &amp; torna." in html
    assert "&lt;Forn&gt;" in html and "<Forn>" not in html
    text = render_review_text(
        REJECTED, shop_name="Forn", town="Malgrat", reason=reason, lang="ca"
    )
    assert "El motiu:\n" + reason in text
    assert "T'expliquem el motiu." in html
    assert review_email_subject(ADMIN_NEW, "ca", shop_name="Forn") == (
        "Nova sol·licitud de comerç: Forn"
    )


async def test_emails_with_a_button_wait_for_the_panels_address(monkeypatch):
    delivered: list[str] = []

    async def fake_deliver(to, subject, text, html_body):
        delivered.append(subject)
        return True

    monkeypatch.setattr("app.email._deliver", fake_deliver)
    monkeypatch.setattr(get_settings(), "backoffice_url", "")
    parts = dict(shop_name="Forn", town="Malgrat", lang="ca")

    assert await send_shop_review_email(APPROVED, "forn@test.cat", **parts) is False
    assert await send_shop_review_email(ADMIN_NEW, "admin@test.cat", **parts) is False
    # The ones without a button need nothing else.
    assert await send_shop_review_email(RECEIVED, "forn@test.cat", **parts) is True
    assert (
        await send_shop_review_email(REJECTED, "forn@test.cat", reason="No", **parts)
        is True
    )
    assert delivered == [
        "Hem rebut la teva sol·licitud",
        "No hem pogut validar el teu comerç",
    ]
    monkeypatch.setattr(get_settings(), "backoffice_url", PANEL)
    assert await send_shop_review_email(APPROVED, "forn@test.cat", **parts) is True


# ── Deletion after 30 days ────────────────────────────────────────────


async def test_rejected_requests_are_deleted_after_thirty_days(db_session):
    town = await malgrat(db_session)

    def shop(name: str, status: str, days_ago: int) -> Shop:
        row = Shop(
            town_id=town.id,
            name=name,
            contact_email=f"{name.lower()}@test.cat",
            status=status,
            updated_at=datetime.utcnow() - timedelta(days=days_ago),
        )
        db_session.add(row)
        return row

    shop("Vell", "rejected", 31)
    shop("Recent", "rejected", 29)
    shop("Esperant", "review", 90)
    shop("Viu", "active", 90)
    await db_session.commit()

    async def names() -> set[str]:
        return set((await db_session.execute(select(Shop.name))).scalars().all())

    # Without apply it only says what it would delete.
    report = await purge_rejected_shops(db_session, apply=False)
    assert [name for name, _ in report] == ["Vell"]
    assert await names() == {"Vell", "Recent", "Esperant", "Viu"}

    report = await purge_rejected_shops(db_session, apply=True)
    await db_session.commit()
    assert [name for name, _ in report] == ["Vell"]
    assert await names() == {"Recent", "Esperant", "Viu"}
    assert await purge_rejected_shops(db_session, apply=True) == []
