"""Generate and persist a fixed QR PNG per shop (token + deep-link)."""

from __future__ import annotations

import io
import secrets

import qrcode
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Shop, ShopMedia
from app.services.shop_media import get_shop_media, media_public_path

QR_KIND = "qr"


def build_scan_url(token: str) -> str:
    base = get_settings().qr_scan_base_url.rstrip("/")
    return f"{base}?c={token}"


def render_qr_png(data: str) -> bytes:
    qr = qrcode.QRCode(version=None, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def ensure_shop_qr(db: AsyncSession, shop: Shop) -> ShopMedia:
    """Ensure shop has a stable qr_code token and a PNG in shop_media.

    Idempotent: does not rotate an existing token. Creates PNG if missing.
    """
    if not shop.qr_code:
        shop.qr_code = secrets.token_urlsafe(16)
        await db.flush()

    existing = await get_shop_media(db, shop.id, QR_KIND)
    if existing:
        return existing

    png = render_qr_png(build_scan_url(shop.qr_code))
    row = ShopMedia(
        shop_id=shop.id,
        kind=QR_KIND,
        content_type="image/png",
        data=png,
        byte_size=len(png),
    )
    db.add(row)
    await db.flush()
    return row


def qr_png_url(shop_id: str) -> str:
    return media_public_path(shop_id, QR_KIND)
