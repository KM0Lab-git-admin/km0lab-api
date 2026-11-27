"""The demonstration's QR sheet (``GET /demo/qr``)."""

import base64
import re

import pytest

from app.config import get_settings
from app.models import Shop
from app.services.shop_qr import build_scan_url, render_qr_png
from tests._municipalities import API, catalog, malgrat

pytestmark = pytest.mark.asyncio


async def _demo_with_shops(db, names: list[str]):
    demo = await catalog(db)
    for n, name in enumerate(names):
        db.add(
            Shop(
                town_id=demo.id,
                name=name,
                contact_email=f"shop{n}@test.cat",
                status="active",
                is_fake=True,
                qr_code=f"token-{n}",
            )
        )
        await db.flush()
    await db.commit()
    return demo


def _pictures(page: str) -> list[bytes]:
    return [
        base64.b64decode(data)
        for data in re.findall(r'src="data:image/png;base64,([^"]+)"', page)
    ]


async def test_sheet_shows_five_demo_shops_with_their_real_qr(client, db_session):
    await _demo_with_shops(
        db_session,
        [f"[DEMO] Comerç {n}" for n in range(7)] + ["Test Comerc 191416"],
    )

    r = await client.get(f"{API}/demo/qr")

    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    page = r.text
    # Five, always the same, without the "[DEMO]" mark and without leftovers.
    assert re.findall(r"<figcaption>([^<]+)</figcaption>", page) == [
        f"Comerç {n}" for n in range(5)
    ]
    assert "Test Comerc" not in page
    # Each picture is the QR a phone reads: the scan address of that shop.
    assert _pictures(page) == [
        render_qr_png(build_scan_url(f"token-{n}")) for n in range(5)
    ]
    assert (await client.get(f"{API}/demo/qr")).text == page


async def test_sheet_never_shows_a_real_shop(client, db_session):
    town = await malgrat(db_session)
    db_session.add(
        Shop(
            town_id=town.id,
            name="[DEMO] Forn de veritat",
            contact_email="forn@test.cat",
            status="active",
            is_fake=False,
            qr_code="real-token",
        )
    )
    demo = await _demo_with_shops(db_session, ["[DEMO] Comerç 0"])
    # Not a real one filed under Demo KM0 either, nor one that is off.
    db_session.add_all(
        [
            Shop(
                town_id=demo.id,
                name="[DEMO] Real per error",
                contact_email="a@test.cat",
                status="active",
                is_fake=False,
                qr_code="oops-token",
            ),
            Shop(
                town_id=demo.id,
                name="[DEMO] Apagat",
                contact_email="b@test.cat",
                status="inactive",
                is_fake=True,
                qr_code="off-token",
            ),
        ]
    )
    await db_session.commit()

    page = (await client.get(f"{API}/demo/qr")).text

    assert re.findall(r"<figcaption>([^<]+)</figcaption>", page) == ["Comerç 0"]
    assert _pictures(page) == [render_qr_png(build_scan_url("token-0"))]


async def test_sheet_speaks_three_languages(client, db_session):
    await _demo_with_shops(db_session, ["[DEMO] Comerç 0"])

    assert "QR de demostració" in (await client.get(f"{API}/demo/qr")).text
    es = (await client.get(f"{API}/demo/qr", params={"lang": "es"})).text
    assert "QR de demostración" in es and 'lang="es"' in es
    assert "Demo QR codes" in (
        await client.get(f"{API}/demo/qr", params={"lang": "en"})
    ).text
    assert (await client.get(f"{API}/demo/qr", params={"lang": "fr"})).status_code == 422


async def test_sheet_does_not_exist_in_production_or_without_shops(
    client, db_session, monkeypatch
):
    await catalog(db_session)
    await db_session.commit()
    assert (await client.get(f"{API}/demo/qr")).status_code == 404

    await _demo_with_shops(db_session, ["[DEMO] Comerç 0"])
    assert (await client.get(f"{API}/demo/qr")).status_code == 200
    monkeypatch.setattr(get_settings(), "environment", "production")
    assert (await client.get(f"{API}/demo/qr")).status_code == 404
