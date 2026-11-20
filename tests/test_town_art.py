"""Town illustration (media kind ``art``) and the public list of towns."""

import pytest

from app.demo import DEMO_TOWN_SLUG
from app.models import Town, TownPostalCode, User
from app.qa import QA_TOWN_NAME, QA_TOWN_SLUG
from app.roles import flags_from_roles
from app.security import create_access_token
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio

WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 fake-illustration-bytes"
PNG = b"\x89PNG\r\n\x1a\n fake-logo-bytes"


async def _create_town(db_session, name, postal_codes, slug=None):
    town = Town(
        name=name,
        slug=slug or slugify(name),
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{slugify(name)}.cat",
        manager_name="Admin",
    )
    db_session.add(town)
    await db_session.flush()
    for i, cp in enumerate(postal_codes):
        db_session.add(
            TownPostalCode(postal_code=cp, town_id=town.id, is_primary=i == 0)
        )
    await db_session.flush()
    return town


async def _admin_headers(db_session, town, postal_code, tag):
    admin = User(
        email=f"admin-{tag}@test.cat",
        slug=f"admin-{tag}",
        postal_code=postal_code,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()
    token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    return {"Authorization": f"Bearer {token}"}


async def _put_media(client, town_id, kind, headers, data=WEBP, mime="image/webp"):
    return await client.put(
        f"/api/v1/towns/{town_id}/media/{kind}",
        headers=headers,
        files={"file": (f"{kind}.bin", data, mime)},
    )


async def test_art_is_served_and_announced_by_postal_code(client, db_session):
    town = await _create_town(db_session, "ArtTown", ["08561", "08560"])
    headers = await _admin_headers(db_session, town, "08561", "art")

    before = await client.get("/api/v1/towns/public", params={"postal_code": "08561"})
    assert before.json()["art_url"] is None

    r = await _put_media(client, town.id, "art", headers)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "art"

    body = (
        await client.get("/api/v1/towns/public", params={"postal_code": "08560"})
    ).json()
    assert body["slug"] == "arttown"
    assert body["postal_codes"] == ["08561", "08560"]  # primary first
    assert body["art_url"].startswith(f"/api/v1/towns/{town.id}/media/art?v=")
    # The illustration is not the brand logo.
    assert body["has_logo"] is False
    assert body["logo_url"] is None

    img = await client.get(body["art_url"])
    assert img.status_code == 200
    assert img.content == WEBP
    assert img.headers["content-type"] == "image/webp"


async def test_art_and_logo_do_not_overwrite_each_other(client, db_session):
    town = await _create_town(db_session, "BothTown", ["08562"])
    headers = await _admin_headers(db_session, town, "08562", "both")

    assert (await _put_media(client, town.id, "logo", headers, PNG, "image/png")).status_code == 200
    assert (await _put_media(client, town.id, "art", headers)).status_code == 200

    me = (await client.get("/api/v1/towns/me", headers=headers)).json()
    assert me["logo_url"] == f"/api/v1/towns/{town.id}/media/logo"
    assert me["art_url"].startswith(f"/api/v1/towns/{town.id}/media/art?v=")
    assert (await client.get(me["logo_url"])).content == PNG

    r = await client.delete(f"/api/v1/towns/{town.id}/media/art", headers=headers)
    assert r.status_code == 204
    me = (await client.get("/api/v1/towns/me", headers=headers)).json()
    assert me["art_url"] is None
    assert me["has_logo"] is True
    assert me["logo_url"] == f"/api/v1/towns/{town.id}/media/logo"
    assert (await client.get(f"/api/v1/towns/{town.id}/media/art")).status_code == 404


async def test_admin_cannot_upload_art_to_another_town(client, db_session):
    mine = await _create_town(db_session, "MineTown", ["08563"])
    other = await _create_town(db_session, "OtherTown", ["08564"])
    headers = await _admin_headers(db_session, mine, "08563", "scope")

    r = await _put_media(client, other.id, "art", headers)
    assert r.status_code in (403, 404)
    body = (
        await client.get("/api/v1/towns/public", params={"postal_code": "08564"})
    ).json()
    assert body["art_url"] is None


async def test_unknown_media_kind_is_rejected(client, db_session):
    town = await _create_town(db_session, "KindTown", ["08565"])
    headers = await _admin_headers(db_session, town, "08565", "kind")
    r = await _put_media(client, town.id, "banner", headers)
    assert r.status_code == 400


async def test_list_towns_is_public_and_hides_demo_and_qa(client, db_session):
    zeta = await _create_town(db_session, "Zeta Town", ["08567"])
    alfa = await _create_town(db_session, "Alfa Town", ["08566"])
    await _create_town(db_session, "Demo KM0", ["00000"], slug=DEMO_TOWN_SLUG)
    await _create_town(db_session, QA_TOWN_NAME, ["99999"], slug=QA_TOWN_SLUG)
    headers = await _admin_headers(db_session, alfa, "08566", "list")
    assert (await _put_media(client, alfa.id, "art", headers)).status_code == 200

    r = await client.get("/api/v1/towns")
    assert r.status_code == 200, r.text
    listed = {t["slug"]: t for t in r.json()}

    assert DEMO_TOWN_SLUG not in listed
    assert QA_TOWN_SLUG not in listed
    names = [t["name"] for t in r.json()]
    assert names == sorted(names)
    assert names.index("Alfa Town") < names.index("Zeta Town")

    assert listed["alfa-town"]["id"] == alfa.id
    assert listed["alfa-town"]["postal_codes"] == ["08566"]
    assert listed["alfa-town"]["art_url"].startswith(
        f"/api/v1/towns/{alfa.id}/media/art?v="
    )
    assert listed["zeta-town"]["id"] == zeta.id
    assert listed["zeta-town"]["art_url"] is None
