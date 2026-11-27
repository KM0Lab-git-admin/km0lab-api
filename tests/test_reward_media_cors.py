"""Public reward media must stay CORS-safe on 404 (img / fetch from backoffice)."""

import pytest

from app.models import Reward, RewardMedia, Town, TownPostalCode, User
from app.roles import flags_from_roles
from app.security import create_access_token
from app.services.reward_media import media_version
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio

# 1x1 PNG
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"P\x0f\x00\x04\x85\x01\x80\x84\xa9\x8c!\x00\x00\x00\x00IEND\xaeB`\x82"
)

UAT_ORIGIN = "https://backoffice.uat.km0lab.com"
MISSING = "/api/v1/rewards/f1e1915d5c2b406ba5156b11ab2e35fd/media"


async def test_missing_media_get_has_cors_and_corp(client):
    res = await client.get(MISSING, headers={"Origin": UAT_ORIGIN})
    assert res.status_code == 404
    assert res.headers.get("access-control-allow-origin") == UAT_ORIGIN
    assert res.headers.get("cross-origin-resource-policy") == "cross-origin"
    assert "no-store" in (res.headers.get("cache-control") or "")


async def test_missing_media_head_has_cors(client):
    res = await client.head(MISSING, headers={"Origin": UAT_ORIGIN})
    assert res.status_code == 404
    assert res.headers.get("access-control-allow-origin") == UAT_ORIGIN
    assert res.headers.get("cross-origin-resource-policy") == "cross-origin"


async def test_missing_media_options_preflight(client):
    res = await client.options(
        MISSING,
        headers={
            "Origin": UAT_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == UAT_ORIGIN


async def test_upload_reward_media_persists(client, db_session):
    town = Town(name="Demo KM0", slug=slugify("Demo KM0"))
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(postal_code="00000", town_id=town.id, is_primary=True)
    )
    reward = Reward(
        town_id=town.id,
        name="Val 5%",
        description="Val 5%",
        type="discount",
        points_required=500,
        value="5%",
        is_fake=True,
        status="active",
    )
    admin = User(
        email="admin-upload@test.cat",
        slug="admin-upload",
        postal_code="00000",
        first_name="Admin",
        last_name="Demo",
        points=0,
        is_fake=True,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add_all([reward, admin])
    await db_session.commit()

    token = create_access_token(
        admin.id, roles=["admin", "resident"], town_id=town.id
    )
    res = await client.put(
        f"/api/v1/rewards/{reward.id}/media",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("upload.png", _PNG, "image/png")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["byte_size"] == len(_PNG)
    version = body["url"].split("?v=", 1)[1]
    assert int(version) > 1_000_000_000

    got = await client.get(body["url"])
    assert got.status_code == 200
    assert got.content == _PNG

    replaced = _PNG + b"\x00"
    again = await client.put(
        f"/api/v1/rewards/{reward.id}/media",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("upload.png", replaced, "image/png")},
    )
    assert again.status_code == 200, again.text
    assert again.json()["byte_size"] == len(replaced)
    assert int(again.json()["url"].split("?v=", 1)[1]) >= int(version)


async def test_media_version_does_not_lazy_load_expired(db_session):
    town = Town(name="Expire Town", slug=slugify("Expire Town"))
    db_session.add(town)
    await db_session.flush()
    reward = Reward(
        town_id=town.id,
        name="Val",
        type="discount",
        points_required=1,
        status="active",
    )
    db_session.add(reward)
    await db_session.flush()
    row = RewardMedia(
        reward_id=reward.id,
        content_type="image/png",
        data=_PNG,
        byte_size=len(_PNG),
    )
    db_session.add(row)
    await db_session.flush()
    db_session.expire(row, ["created_at", "updated_at"])

    assert media_version(row) == str(len(_PNG))
