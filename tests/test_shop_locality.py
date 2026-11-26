"""A shop belongs to one town of its municipality."""

import pytest

from app.models import Shop, User
from app.security import create_access_token
from tests._municipalities import (
    API,
    admin_headers,
    baix_montseny,
    locality,
    malgrat,
)

pytestmark = pytest.mark.asyncio


def _shop(name: str, **extra) -> dict:
    return {"name": name, "contact_email": f"{name.lower()}@test.cat", **extra}


async def test_single_town_assigns_its_only_town(client, db_session):
    town = await malgrat(db_session)
    headers = await admin_headers(db_session, town, "08380")

    # Exactly what the backoffice sends today: no town, postal code optional.
    for body in (_shop("Forn"), _shop("Peix", postal_code="08380")):
        r = await client.post(f"{API}/shops", json=body, headers=headers)
        assert r.status_code == 201, r.text
        assert r.json()["town_name"] == "Malgrat de Mar"
        assert r.json()["locality_id"] == (await locality(db_session, "Malgrat de Mar")).id


async def test_grouped_municipality_needs_to_know_the_town(client, db_session):
    await malgrat(db_session)
    baix = await baix_montseny(db_session)
    headers = await admin_headers(db_session, baix, "17400")
    riells = await locality(db_session, "Riells i Viabrea")
    outsider = await locality(db_session, "Malgrat de Mar")

    # Neither hint: it is not guessed.
    r = await client.post(f"{API}/shops", json=_shop("Forn"), headers=headers)
    assert r.status_code == 422 and r.json()["detail"] == "locality_required"
    # A postal code of another municipality says nothing either.
    r = await client.post(
        f"{API}/shops", json=_shop("Forn", postal_code="08380"), headers=headers
    )
    assert r.status_code == 422 and r.json()["detail"] == "locality_required"
    # A town of another municipality is refused.
    r = await client.post(
        f"{API}/shops", json=_shop("Forn", locality_id=outsider.id), headers=headers
    )
    assert r.status_code == 422 and r.json()["detail"] == "locality_not_in_town"

    # The shop's postal code is enough...
    r = await client.post(
        f"{API}/shops", json=_shop("Forn", postal_code="17450"), headers=headers
    )
    assert r.status_code == 201, r.text
    assert r.json()["town_name"] == "Hostalric"
    assert r.json()["town_id"] == baix.id
    # ... and naming the town wins over it.
    r = await client.post(
        f"{API}/shops",
        json=_shop("Peix", postal_code="17450", locality_id=riells.id),
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["town_name"] == "Riells i Viabrea"
    assert r.json()["locality_id"] == riells.id


async def test_admin_moves_a_shop_between_towns_of_the_municipality(
    client, db_session
):
    await malgrat(db_session)
    baix = await baix_montseny(db_session)
    headers = await admin_headers(db_session, baix, "17400")
    breda = await locality(db_session, "Breda")
    outsider = await locality(db_session, "Malgrat de Mar")
    created = await client.post(
        f"{API}/shops", json=_shop("Forn", postal_code="17450"), headers=headers
    )
    url = f"{API}/shops/{created.json()['id']}"

    r = await client.patch(url, json={"locality_id": breda.id}, headers=headers)
    assert r.status_code == 200 and r.json()["town_name"] == "Breda"
    # A postal code of another town of the municipality moves it there.
    r = await client.patch(url, json={"postal_code": "17404"}, headers=headers)
    assert r.status_code == 200 and r.json()["town_name"] == "Riells i Viabrea"
    # Any other change leaves it where it is.
    r = await client.patch(url, json={"phone": "600000000"}, headers=headers)
    assert r.status_code == 200 and r.json()["town_name"] == "Riells i Viabrea"
    # Never to a town of another municipality.
    r = await client.patch(url, json={"locality_id": outsider.id}, headers=headers)
    assert r.status_code == 422 and r.json()["detail"] == "locality_not_in_town"


async def test_public_signup_lands_in_the_town_of_its_postal_code(
    client, db_session
):
    baix = await baix_montseny(db_session)
    await db_session.commit()

    r = await client.post(
        f"{API}/shops/public-signup",
        json={
            "name": "Fusteria Riells",
            "tax_id": "B12345678",
            "contact_email": "fusteria@test.cat",
            "postal_code": "17404",
        },
    )
    assert r.status_code == 200, r.text
    shop = await db_session.get(Shop, r.json()["shop_id"])
    assert shop.town_id == baix.id
    assert shop.locality_id == (await locality(db_session, "Riells i Viabrea")).id


async def test_admin_sees_the_towns_of_their_municipality(client, db_session):
    mal = await malgrat(db_session)
    baix = await baix_montseny(db_session)
    mal_admin = await admin_headers(db_session, mal, "08380")
    baix_admin = await admin_headers(db_session, baix, "17400")

    mine = (await client.get(f"{API}/towns/me", headers=baix_admin)).json()
    assert mine["name"] == "Baix Montseny"
    assert [(t["name"], t["postal_codes"]) for t in mine["localities"]] == [
        ("Breda", ["17400"]),
        ("Hostalric", ["17450"]),
        ("Riells i Viabrea", ["17404"]),
    ]
    theirs = (await client.get(f"{API}/towns/me", headers=mal_admin)).json()
    assert [t["name"] for t in theirs["localities"]] == ["Malgrat de Mar"]

    # The account says both: the town it is tied to and what it administers.
    me = (await client.get(f"{API}/users/me", headers=baix_admin)).json()
    assert me["town_name"] == "Breda"
    assert me["municipality_name"] == "Baix Montseny"
    me = (await client.get(f"{API}/users/me", headers=mal_admin)).json()
    assert me["town_name"] == me["municipality_name"] == "Malgrat de Mar"


async def test_shops_stay_inside_their_municipality(client, db_session):
    mal = await malgrat(db_session)
    baix = await baix_montseny(db_session)
    mal_admin = await admin_headers(db_session, mal, "08380")
    baix_admin = await admin_headers(db_session, baix, "17400")
    forn = await client.post(f"{API}/shops", json=_shop("Forn"), headers=mal_admin)
    peix = await client.post(
        f"{API}/shops", json=_shop("Peix", postal_code="17400"), headers=baix_admin
    )
    assert forn.status_code == peix.status_code == 201

    # Each admin lists and edits only the shops of their municipality.
    listed = await client.get(f"{API}/shops", headers=baix_admin)
    assert [s["name"] for s in listed.json()] == ["Peix"]
    listed = await client.get(f"{API}/shops", headers=mal_admin)
    assert [s["name"] for s in listed.json()] == ["Forn"]
    r = await client.patch(
        f"{API}/shops/{forn.json()['id']}", json={"name": "Meu"}, headers=baix_admin
    )
    assert r.status_code == 403
    r = await client.patch(
        f"{API}/shops/{peix.json()['id']}", json={"name": "Meu"}, headers=mal_admin
    )
    assert r.status_code == 403


# ── Piloto: las lecturas de vecinos no llevan el código de escaneo ───


async def test_public_reads_hide_the_scan_code_and_the_contact_email(
    client, db_session
):
    town = await malgrat(db_session)
    headers = await admin_headers(db_session, town, "08380")
    created = await client.post(
        f"{API}/shops",
        json=_shop("Forn", postal_code="08380", tax_id="B12345678"),
        headers=headers,
    )
    shop_id = created.json()["id"]
    await client.patch(
        f"{API}/shops/{shop_id}", json={"status": "active"}, headers=headers
    )
    resident = User(email="veina@test.cat", slug="veina", postal_code="08380")
    db_session.add(resident)
    await db_session.commit()
    resident_headers = {
        "Authorization": "Bearer "
        + create_access_token(resident.id, roles=["resident"])
    }

    # El administrador sigue viéndolo todo.
    mine = (await client.get(f"{API}/shops/{shop_id}", headers=headers)).json()
    assert mine["qr_code"] and mine["has_qr"] is True
    assert mine["contact_email"] == "forn@test.cat"
    assert mine["tax_id"] == "B12345678"

    # Sin sesión, con sesión de vecino en la lista, y pidiendo la ficha.
    public = (
        await client.get(f"{API}/shops/public", params={"postal_code": "08380"})
    ).json()
    for_me = (
        await client.get(f"{API}/shops/for-me", headers=resident_headers)
    ).json()
    one = (
        await client.get(f"{API}/shops/{shop_id}", headers=resident_headers)
    ).json()
    for card in (public[0], for_me[0], one):
        assert card["name"] == "Forn"
        assert card["qr_code"] is None
        assert card["has_qr"] is True  # la app sigue sabiendo que tiene QR
        assert card["contact_email"] == ""
        assert card["tax_id"] is None
    # Ni rastro del código en ninguna respuesta de vecino.
    for body in (public, for_me, one):
        assert mine["qr_code"] not in str(body)
