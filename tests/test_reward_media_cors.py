"""Public reward media must stay CORS-safe on 404 (img / fetch from backoffice)."""

import pytest

pytestmark = pytest.mark.asyncio

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
