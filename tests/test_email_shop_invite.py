"""The email a shop gets when the administrator registers it."""

import re

import pytest

from app.catalog.email_shop_invite import (
    INVITE_COPY,
    render_shop_invite_html,
    render_shop_invite_text,
    shop_invite_subject,
)
from app.config import get_settings
from app.services.qa_territory import ensure_qa_territory
from tests._municipalities import API, admin_headers, baix_montseny, malgrat

PANEL = "https://backoffice.uat.km0lab.com"
PARTS = dict(
    shop_name="Forn de la Plaça", town="Malgrat de Mar", entity="Ajuntament de Malgrat"
)


# ── What it says ──────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["ca", "es", "en"])
def test_every_language_has_every_text_and_no_address(lang):
    assert set(INVITE_COPY[lang]) == set(INVITE_COPY["ca"])
    for key, text in INVITE_COPY[lang].items():
        assert text.strip(), key
        # The panel's address always comes from configuration.
        assert "http" not in text and "km0lab.com/" not in text


def test_catalan_text_keeps_the_words_of_the_shop_sheet():
    text = render_shop_invite_text(**PARTS, panel_url=PANEL, lang="ca")

    assert text.startswith("El teu comerç ja és a KM0 LAB\n")
    assert (
        "Som KM0 LAB. El teu comerç, Forn de la Plaça, ja està donat d'alta a "
        "Malgrat de Mar, a proposta de Ajuntament de Malgrat." in text
    )
    assert "1. Entra al panell amb aquest mateix correu." in text
    assert "   Si no veus el codi, mira a «correu no desitjat»." in text
    assert "3. Imprimeix el cartell amb el teu codi QR i posa'l al taulell." in text
    # The button, as a line of its own with the address.
    assert f"\nEntrar al panell: {PANEL}\n" in text
    assert text.rstrip().endswith("KM0 LAB")


def test_without_an_entity_the_intro_does_not_name_one():
    for entity in (None, "", "   "):
        text = render_shop_invite_text(
            shop_name="Forn", town="Blanes", entity=entity, panel_url=PANEL, lang="es"
        )
        assert "Tu comercio, Forn, ya está dado de alta en Blanes." in text
        assert "a propuesta de" not in text
        assert "{" not in text


def test_html_is_the_same_card_with_steps_and_one_button():
    page = render_shop_invite_html(**PARTS, panel_url=PANEL, lang="ca")

    assert 'lang="ca"' in page and "KM0&nbsp;LAB" in page
    # No code box, no expiry warning: this is not the access-code email.
    assert "bg-code" not in page and "t-warn" not in page
    assert re.findall(r">([123])</div>", page) == ["1", "2", "3"]
    buttons = re.findall(r'<a [^>]*href="([^"]+)"[^>]*>([^<]+)</a>', page)
    assert buttons == [(PANEL, "Entrar al panell")]
    assert "min-height:48px" in page and "border-radius:999px" in page
    assert "$" not in page and "{shop_name}" not in page


def test_names_cannot_inject_markup():
    page = render_shop_invite_html(
        shop_name='<b>Forn</b> "Bo" & Fills',
        town="Malgrat",
        entity="<script>x</script>",
        panel_url=PANEL + '/?a="1"',
        lang="ca",
    )
    assert "<b>Forn</b>" not in page and "<script>" not in page
    assert "&lt;b&gt;Forn&lt;/b&gt;" in page
    assert 'href="https://backoffice.uat.km0lab.com/?a=&quot;1&quot;"' in page


def test_unknown_language_falls_back_to_catalan():
    assert shop_invite_subject("fr") == shop_invite_subject(None) == INVITE_COPY["ca"]["subject"]
    assert shop_invite_subject("en") == "Your shop is now on KM0 LAB"


# ── When it is sent ───────────────────────────────────────────────────


@pytest.fixture
def outbox(monkeypatch):
    """What would have gone out, instead of sending it."""
    sent: list[dict] = []

    async def deliver(to, subject, text, html_body):
        sent.append({"to": to, "subject": subject, "text": text, "html": html_body})
        return True

    monkeypatch.setattr("app.email._deliver", deliver)
    monkeypatch.setattr(get_settings(), "backoffice_url", PANEL)
    return sent


async def _register(client, admin, **over):
    body = {"name": "Forn Nou", "contact_email": "forn@test.cat", "categories": ["bakery"]}
    return await client.post(f"{API}/shops", headers=admin, json={**body, **over})


@pytest.mark.asyncio
async def test_registering_a_shop_tells_the_shop(client, db_session, outbox):
    town = await malgrat(db_session)
    town.entity_name = "Ajuntament de Malgrat de Mar"
    await db_session.commit()
    admin = await admin_headers(db_session, town, "08380")

    r = await _register(client, admin)

    assert r.status_code == 201, r.text
    assert len(outbox) == 1
    mail = outbox[0]
    assert mail["to"] == "forn@test.cat"
    assert mail["subject"] == "El teu comerç ja és a KM0 LAB"
    assert "Forn Nou, ja està donat d'alta a Malgrat de Mar" in mail["text"]
    assert "a proposta de Ajuntament de Malgrat de Mar." in mail["text"]
    assert f'href="{PANEL}"' in mail["html"]


@pytest.mark.asyncio
async def test_a_shop_of_a_grouped_municipality_is_told_its_own_town(
    client, db_session, outbox
):
    """The shop knows "Hostalric", not the name of the municipality."""
    town = await baix_montseny(db_session)
    await db_session.commit()
    admin = await admin_headers(db_session, town, "17400")

    r = await _register(client, admin, postal_code="17450")

    assert r.status_code == 201, r.text
    # Its town, and no "at the suggestion of" a name that is only a place.
    assert "Forn Nou, ja està donat d'alta a Hostalric.\n" in outbox[0]["text"]
    assert "Baix Montseny" not in outbox[0]["text"]


@pytest.mark.asyncio
async def test_make_believe_shops_are_told_nothing(client, db_session, outbox):
    """The nightly tests register shops in the QA territory."""
    await ensure_qa_territory(db_session)
    await db_session.commit()
    r = await client.post(
        f"{API}/auth/verify-otp", json={"email": "qa+admin@km0lab.com", "code": "123456"}
    )
    admin = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = await _register(client, admin, contact_email="qa+botiga@km0lab.com")

    assert r.status_code == 201, r.text
    assert outbox == []


@pytest.mark.asyncio
async def test_without_the_panel_address_nothing_is_sent(client, db_session, outbox, monkeypatch):
    monkeypatch.setattr(get_settings(), "backoffice_url", "")
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")

    r = await _register(client, admin)

    assert r.status_code == 201, r.text
    assert outbox == []


@pytest.mark.asyncio
async def test_a_failed_email_does_not_undo_the_registration(
    client, db_session, monkeypatch
):
    async def broken(*_args):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.email._deliver", broken)
    monkeypatch.setattr(get_settings(), "backoffice_url", PANEL)
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")

    r = await _register(client, admin)

    assert r.status_code == 201, r.text
    listed = (await client.get(f"{API}/shops", headers=admin)).json()
    assert [s["name"] for s in listed] == ["Forn Nou"]
