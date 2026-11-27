"""The demonstration's QR sheet (dev/staging only).

``GET /demo/qr`` is a page to open on another screen or to print: five
make-believe shops of Demo KM0, each with its QR. Whoever is trying the demo
with friends scans them from the app (postal code 00000) and earns points.

It is the one place where a shop's QR is public, and it only ever shows
shops of the demonstration: scanning them pays make-believe points to
make-believe accounts (``app/services/residency.py`` keeps those from
reaching a real municipality). It answers 404 where the demo is off.

The page is self-contained (the pictures travel inside it) and its few
words live here, in three languages: it is demo material, not the app.
"""

from __future__ import annotations

import base64
import html
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.demo import DEMO_POSTAL_CODE, demo_enabled
from app.models import Shop
from app.services.shop_qr import build_scan_url, render_qr_png
from app.services.towns import get_postal_code

router = APIRouter(prefix="/demo", tags=["demo"])

SHEET_SHOPS = 5
# Shops seeded for the demonstration carry this mark; whatever a test left
# behind in Demo KM0 does not.
_DEMO_MARK = re.compile(r"^\s*\[demo\]\s*", re.I)

_TEXT = {
    "ca": {
        "title": "QR de demostració",
        "how": "Obre l’app KM0 LAB en mode demostració (codi postal 00000), "
        "entra amb el teu correu i escaneja aquests codis. Cada comerç dona "
        "punts un sol cop.",
        "note": "Comerços de mostra: els punts i els premis no són reals.",
    },
    "es": {
        "title": "QR de demostración",
        "how": "Abre la app KM0 LAB en modo demostración (código postal 00000), "
        "entra con tu correo y escanea estos códigos. Cada comercio da puntos "
        "una sola vez.",
        "note": "Comercios de muestra: los puntos y los premios no son reales.",
    },
    "en": {
        "title": "Demo QR codes",
        "how": "Open the KM0 LAB app in demo mode (postal code 00000), sign in "
        "with your email and scan these codes. Each shop gives points once.",
        "note": "Sample shops: points and rewards are not real.",
    },
}

_PAGE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title} · KM0 LAB</title>
<style>
  body {{ margin: 0; padding: 24px; font-family: system-ui, -apple-system,
         "Segoe UI", sans-serif; color: #14213d; background: #fff; }}
  header {{ max-width: 900px; margin: 0 auto 24px; text-align: center; }}
  h1 {{ margin: 0 0 8px; font-size: 28px; }}
  p {{ margin: 0 auto; max-width: 640px; line-height: 1.45; }}
  main {{ display: grid; gap: 24px; max-width: 900px; margin: 0 auto;
          grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
  figure {{ margin: 0; padding: 16px; border: 1px solid #d9d9d9;
            border-radius: 16px; text-align: center; break-inside: avoid; }}
  img {{ width: 100%; max-width: 260px; height: auto;
         image-rendering: pixelated; }}
  figcaption {{ margin-top: 8px; font-size: 18px; font-weight: 700; }}
  footer {{ margin: 24px auto 0; text-align: center; font-size: 13px;
            color: #555; }}
  @media print {{ body {{ padding: 0; }} }}
</style>
</head>
<body>
<header><h1>{title}</h1><p>{how}</p></header>
<main>
{cards}
</main>
<footer>{note}</footer>
</body>
</html>
"""


async def demo_sheet_shops(db: AsyncSession) -> list[Shop]:
    """The shops of the sheet: always the same five, in the same order."""
    postal = await get_postal_code(db, DEMO_POSTAL_CODE)
    if postal is None:
        return []
    rows = (
        await db.execute(
            select(Shop)
            .where(
                Shop.town_id == postal.town_id,
                Shop.is_fake.is_(True),
                Shop.status == "active",
                Shop.qr_code.is_not(None),
            )
            .order_by(Shop.created_at, Shop.name, Shop.id)
        )
    ).scalars().all()
    return [s for s in rows if _DEMO_MARK.match(s.name)][:SHEET_SHOPS]


@router.get("/qr", response_class=HTMLResponse, include_in_schema=False)
async def demo_qr_sheet(
    lang: str = Query(default="ca", pattern="^(ca|es|en)$"),
    db: AsyncSession = Depends(get_db),
):
    if not demo_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    shops = await demo_sheet_shops(db)
    if not shops:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No demo shops")

    cards = []
    for shop in shops:
        png = render_qr_png(build_scan_url(shop.qr_code or ""))
        name = html.escape(_DEMO_MARK.sub("", shop.name).strip())
        cards.append(
            f'<figure><img alt="QR · {name}" '
            f'src="data:image/png;base64,{base64.b64encode(png).decode()}">'
            f"<figcaption>{name}</figcaption></figure>"
        )
    text = _TEXT[lang]
    page = _PAGE.format(
        lang=lang,
        title=html.escape(text["title"]),
        how=html.escape(text["how"]),
        note=html.escape(text["note"]),
        cards="\n".join(cards),
    )
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})
