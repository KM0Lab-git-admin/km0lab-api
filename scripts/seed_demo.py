"""Seed / refresh demo users + fake Demo KM0 content.

Idempotent: safe to re-run. Requires Demo town + CP 00000 (scripts.seed
ensure_demo_town) and ideally Malgrat for municipal fallback context.

Preserves reward_media and admin-created rewards. Catalog [DEMO] rewards
use stable ids and are upserted in place (images stay attached).

Creates 2 complete fake shops per category (with QR PNG), demo users,
promotions/reward on the merchant's shop, and extra fake residents.

    python -m scripts.seed_demo

Login (ENVIRONMENT=development|staging only):
  resident@km0lab.com  + 123456
  merchant@km0lab.com  + 123456
  admin@km0lab.com     + 123456

Use app postal code 00000 (Demo KM0). Malgrat 08380 stays real-only.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, or_, select

from app.catalog.point_actions import ensure_town_point_actions
from app.catalog.rewards import seed_fake_rewards
from app.catalog.shop_categories import DEFAULT_SHOP_CATEGORIES
from app.config import get_settings
from app.db import SessionLocal
from app.demo import (
    DEMO_ADMIN_EMAIL,
    DEMO_MERCHANT_EMAIL,
    DEMO_POSTAL_CODE,
    DEMO_RESIDENT_EMAIL,
)
from app.models import (
    PointAction,
    Promotion,
    Redemption,
    RedemptionEvent,
    Reward,
    Shop,
    ShopMedia,
    ShopPayment,
    Town,
    TownPostalCode,
    User,
)
from app.roles import flags_from_roles
from app.schemas.opening_hours import OpeningHours
from app.services.points import apply_points
from app.services.shop_qr import ensure_shop_qr
from app.services.towns import ensure_demo_town, resolve_malgrat_town
from app.utils.slug import slugify, split_full_name

settings = get_settings()
# Showcase catalog lives under Demo KM0 (CP 00000), not Malgrat real.

# Extra fake residents for admin stats (not login accounts).
FAKE_RESIDENTS = [
    ("veci1.demo@km0lab.com", "Anna Puig", 120),
    ("veci2.demo@km0lab.com", "Marc Soler", 85),
    ("veci3.demo@km0lab.com", "Laia Riera", 200),
    ("veci4.demo@km0lab.com", "Pol Vidal", 45),
    ("veci5.demo@km0lab.com", "Núria Costa", 150),
]

# Two complete shops per category (name, emoji, street number hint, visit_points).
FAKE_SHOPS_BY_CATEGORY: dict[str, list[dict]] = {
    "bakery": [
        {
            "name": "[DEMO] Fleca del Port",
            "emoji": "🥖",
            "address": "Carrer del Mar 1",
            "phone": "937650001",
            "website": "https://demo.km0lab.com/fleca-port",
            "description": "Pa de massa mare i brioxeria fresca cada matí.",
            "visit_points": 15,
            "opens": "07:00",
            "closes": "14:00",
            "weekend_closed": False,
        },
        {
            "name": "[DEMO] Forn Can Riera",
            "emoji": "🥐",
            "address": "Carrer Major 12",
            "phone": "937650002",
            "website": "https://demo.km0lab.com/forn-riera",
            "description": "Forn familiar de Malgrat amb coques i ensaïmades.",
            "visit_points": 12,
            "opens": "06:30",
            "closes": "13:30",
            "weekend_closed": False,
        },
    ],
    "food": [
        {
            "name": "[DEMO] Queviures La Plaça",
            "emoji": "🛒",
            "address": "Plaça de l'Ajuntament 3",
            "phone": "937650011",
            "website": "https://demo.km0lab.com/queviures",
            "description": "Botiga d'alimentació de proximitat.",
            "visit_points": 10,
            "opens": "09:00",
            "closes": "20:00",
        },
        {
            "name": "[DEMO] Colmado del Centre",
            "emoji": "🏪",
            "address": "Carrer de la Muralla 8",
            "phone": "937650012",
            "website": "https://demo.km0lab.com/colmado",
            "description": "Productes locals i embotits artesans.",
            "visit_points": 10,
            "opens": "08:30",
            "closes": "20:30",
        },
    ],
    "cafe": [
        {
            "name": "[DEMO] Cafè Marítim",
            "emoji": "☕",
            "address": "Passeig Marítim 22",
            "phone": "937650021",
            "website": "https://demo.km0lab.com/cafe-maritim",
            "description": "Cafè amb vistes al mar i pastisseria casolana.",
            "visit_points": 10,
            "opens": "08:00",
            "closes": "21:00",
            "weekend_closed": False,
        },
        {
            "name": "[DEMO] Espresso Malgrat",
            "emoji": "🍵",
            "address": "Carrer Sant Joan 5",
            "phone": "937650022",
            "website": "https://demo.km0lab.com/espresso",
            "description": "Cafè especialitat i brunxs de cap de setmana.",
            "visit_points": 10,
            "opens": "08:30",
            "closes": "19:00",
        },
    ],
    "restaurant": [
        {
            "name": "[DEMO] Restaurant Can Toni",
            "emoji": "🍽️",
            "address": "Carrer de l'Església 4",
            "phone": "937650031",
            "website": "https://demo.km0lab.com/can-toni",
            "description": "Cuina catalana de temporada.",
            "visit_points": 20,
            "opens": "13:00",
            "closes": "16:00",
            "opens_2": "20:00",
            "closes_2": "23:00",
            "weekend_closed": False,
        },
        {
            "name": "[DEMO] La Taula Blava",
            "emoji": "🥘",
            "address": "Avinguda de Catalunya 18",
            "phone": "937650032",
            "website": "https://demo.km0lab.com/taula-blava",
            "description": "Arròs, peix i menú del dia.",
            "visit_points": 18,
            "opens": "12:30",
            "closes": "16:00",
            "opens_2": "20:00",
            "closes_2": "22:30",
        },
    ],
    "bar": [
        {
            "name": "[DEMO] Bar Sport",
            "emoji": "🍺",
            "address": "Carrer del Port 9",
            "phone": "937650041",
            "website": "https://demo.km0lab.com/bar-sport",
            "description": "Tapes, cerveses i partits en directe.",
            "visit_points": 8,
            "opens": "10:00",
            "closes": "23:30",
            "weekend_closed": False,
        },
        {
            "name": "[DEMO] Vermuteria Nova",
            "emoji": "🍸",
            "address": "Carrer Nou 14",
            "phone": "937650042",
            "website": "https://demo.km0lab.com/vermuteria",
            "description": "Vermuts i tapes de dilluns a diumenge.",
            "visit_points": 8,
            "opens": "11:00",
            "closes": "23:00",
            "weekend_closed": False,
        },
    ],
    "butcher": [
        {
            "name": "[DEMO] Carnisseria Vidal",
            "emoji": "🥩",
            "address": "Carrer de la Riera 6",
            "phone": "937650051",
            "website": "https://demo.km0lab.com/carnisseria-vidal",
            "description": "Carns de qualitat i embotits propis.",
            "visit_points": 12,
            "opens": "08:00",
            "closes": "14:00",
        },
        {
            "name": "[DEMO] Carns del Maresme",
            "emoji": "🍖",
            "address": "Carrer de Barcelona 21",
            "phone": "937650052",
            "website": "https://demo.km0lab.com/carns-maresme",
            "description": "Pollastre de pagès i preparats casolans.",
            "visit_points": 12,
            "opens": "08:00",
            "closes": "14:30",
        },
    ],
    "greengrocer": [
        {
            "name": "[DEMO] Fruiteria Sol",
            "emoji": "🍎",
            "address": "Mercat Municipal 2",
            "phone": "937650061",
            "website": "https://demo.km0lab.com/fruiteria-sol",
            "description": "Fruita i verdura de temporada.",
            "visit_points": 10,
            "opens": "08:00",
            "closes": "14:00",
        },
        {
            "name": "[DEMO] Horta Malgrat",
            "emoji": "🥬",
            "address": "Carrer de Girona 7",
            "phone": "937650062",
            "website": "https://demo.km0lab.com/horta",
            "description": "Producte de l'hort del Maresme.",
            "visit_points": 10,
            "opens": "08:30",
            "closes": "14:00",
            "opens_2": "17:00",
            "closes_2": "20:00",
        },
    ],
    "fishmonger": [
        {
            "name": "[DEMO] Peixateria del Port",
            "emoji": "🐟",
            "address": "Carrer del Port 3",
            "phone": "937650071",
            "website": "https://demo.km0lab.com/peixateria",
            "description": "Peix fresc de la llotja.",
            "visit_points": 12,
            "opens": "07:30",
            "closes": "14:00",
        },
        {
            "name": "[DEMO] Mar i Sal",
            "emoji": "🦐",
            "address": "Mercat Municipal 5",
            "phone": "937650072",
            "website": "https://demo.km0lab.com/mar-i-sal",
            "description": "Marisc i peix blau del dia.",
            "visit_points": 12,
            "opens": "07:00",
            "closes": "14:00",
        },
    ],
    "pharmacy": [
        {
            "name": "[DEMO] Farmàcia Centre",
            "emoji": "💊",
            "address": "Carrer Major 1",
            "phone": "937650081",
            "website": "https://demo.km0lab.com/farmacia-centre",
            "description": "Farmàcia de guàrdia i consell sanitari.",
            "visit_points": 8,
            "opens": "09:00",
            "closes": "21:00",
            "weekend_closed": False,
        },
        {
            "name": "[DEMO] Farmàcia Mar",
            "emoji": "🩺",
            "address": "Passeig Marítim 10",
            "phone": "937650082",
            "website": "https://demo.km0lab.com/farmacia-mar",
            "description": "Parafarmàcia i productes naturals.",
            "visit_points": 8,
            "opens": "09:00",
            "closes": "20:30",
        },
    ],
    "bookstore": [
        {
            "name": "[DEMO] Llibreria Lletraferit",
            "emoji": "📚",
            "address": "Carrer Sant Antoni 11",
            "phone": "937650091",
            "website": "https://demo.km0lab.com/lletraferit",
            "description": "Llibres en català i club de lectura.",
            "visit_points": 10,
            "opens": "10:00",
            "closes": "20:00",
        },
        {
            "name": "[DEMO] Papereria i Llibres",
            "emoji": "📖",
            "address": "Carrer de la Pau 16",
            "phone": "937650092",
            "website": "https://demo.km0lab.com/papereria",
            "description": "Material escolar i novel·la.",
            "visit_points": 10,
            "opens": "09:30",
            "closes": "20:00",
        },
    ],
    "clothing": [
        {
            "name": "[DEMO] Moda Costa",
            "emoji": "👗",
            "address": "Carrer Nou 2",
            "phone": "937650101",
            "website": "https://demo.km0lab.com/moda-costa",
            "description": "Roba de temporada per a tota la família.",
            "visit_points": 10,
            "opens": "10:00",
            "closes": "20:00",
        },
        {
            "name": "[DEMO] Boutique Marina",
            "emoji": "👠",
            "address": "Passeig de la Llibertat 4",
            "phone": "937650102",
            "website": "https://demo.km0lab.com/boutique-marina",
            "description": "Moda i complements amb estil mediterrani.",
            "visit_points": 10,
            "opens": "10:00",
            "closes": "20:30",
        },
    ],
    "hairdresser": [
        {
            "name": "[DEMO] Perruqueria Estil",
            "emoji": "✂️",
            "address": "Carrer de l'Era 8",
            "phone": "937650111",
            "website": "https://demo.km0lab.com/perruqueria-estil",
            "description": "Tall, color i tractaments capil·lars.",
            "visit_points": 15,
            "opens": "09:00",
            "closes": "19:00",
        },
        {
            "name": "[DEMO] Barberia del Port",
            "emoji": "💈",
            "address": "Carrer del Port 15",
            "phone": "937650112",
            "website": "https://demo.km0lab.com/barberia",
            "description": "Barberia clàssica i modernitat.",
            "visit_points": 12,
            "opens": "09:30",
            "closes": "20:00",
        },
    ],
    "services": [
        {
            "name": "[DEMO] Serveis Informàtics KM0",
            "emoji": "💻",
            "address": "Carrer Indústria 3",
            "phone": "937650121",
            "website": "https://demo.km0lab.com/info-km0",
            "description": "Reparació d'ordinadors i mòbils.",
            "visit_points": 10,
            "opens": "09:00",
            "closes": "19:00",
        },
        {
            "name": "[DEMO] Bugaderia Express",
            "emoji": "🧺",
            "address": "Carrer de Blanes 19",
            "phone": "937650122",
            "website": "https://demo.km0lab.com/bugaderia",
            "description": "Bugaderia i tintoreria en 24 h.",
            "visit_points": 8,
            "opens": "08:00",
            "closes": "20:00",
            "weekend_closed": False,
        },
    ],
    "other": [
        {
            "name": "[DEMO] Regals i Souvenirs",
            "emoji": "🎁",
            "address": "Passeig Marítim 30",
            "phone": "937650131",
            "website": "https://demo.km0lab.com/souvenirs",
            "description": "Regals i productes de Malgrat.",
            "visit_points": 8,
            "opens": "10:00",
            "closes": "20:00",
            "weekend_closed": False,
        },
        {
            "name": "[DEMO] Botiga Miscel·lània",
            "emoji": "📦",
            "address": "Carrer del Carme 13",
            "phone": "937650132",
            "website": "https://demo.km0lab.com/miscellania",
            "description": "Una mica de tot per al dia a dia.",
            "visit_points": 8,
            "opens": "09:00",
            "closes": "20:00",
        },
    ],
}


# Promo templates keyed by shop category. Each shop gets the first two entries.
_PROMO_BY_CATEGORY: dict[str, list[dict]] = {
    "bakery": [
        {
            "type": "discount",
            "label": "-5%",
            "title": "[DEMO] 5% de descompte",
            "detail": "En pa i brioxeria",
            "value": "5%",
            "min_purchase": None,
            "conditions": "No acumulable amb altres ofertes",
            "active": True,
        },
        {
            "type": "gift",
            "label": "Regal",
            "title": "[DEMO] Croissant de regal",
            "detail": "Amb la teva primera visita",
            "value": "1 croissant",
            "min_purchase": "5€",
            "conditions": "Una unitat per persona",
            "active": False,
        },
    ],
    "food": [
        {
            "type": "discount",
            "label": "-10%",
            "title": "[DEMO] 10% en compra",
            "detail": "En productes d'alimentació",
            "value": "10%",
            "min_purchase": "20€",
            "conditions": "Excepte ofertes ja rebaixades",
            "active": True,
        },
        {
            "type": "special_price",
            "label": "2,50€",
            "title": "[DEMO] Pack fruita 2,50€",
            "detail": "Pack de temporada",
            "value": "2,50€",
            "min_purchase": None,
            "conditions": "Segons disponibilitat",
            "active": True,
        },
    ],
    "cafe": [
        {
            "type": "two_for_one",
            "label": "2×1",
            "title": "[DEMO] 2×1 en cafès",
            "detail": "De dilluns a divendres, matins",
            "value": "2×1",
            "min_purchase": None,
            "conditions": "Només cafè sol o amb llet",
            "active": True,
        },
        {
            "type": "discount",
            "label": "-15%",
            "title": "[DEMO] 15% de descompte",
            "detail": "Per compres superiors a 20€",
            "value": "15%",
            "min_purchase": "20€",
            "conditions": "No acumulable",
            "active": True,
        },
    ],
    "restaurant": [
        {
            "type": "discount",
            "label": "-10%",
            "title": "[DEMO] 10% al menú del dia",
            "detail": "De dilluns a dijous",
            "value": "10%",
            "min_purchase": None,
            "conditions": "Excepte festius",
            "active": True,
        },
        {
            "type": "gift",
            "label": "Regal",
            "title": "[DEMO] Postre de regal",
            "detail": "Amb el menú complet",
            "value": "1 postre",
            "min_purchase": None,
            "conditions": "Una vegada per taula",
            "active": True,
        },
    ],
    "bar": [
        {
            "type": "two_for_one",
            "label": "2×1",
            "title": "[DEMO] 2×1 en tapes",
            "detail": "Hora del vermut",
            "value": "2×1",
            "min_purchase": None,
            "conditions": "De 12:00 a 14:00",
            "active": True,
        },
        {
            "type": "special_price",
            "label": "3€",
            "title": "[DEMO] Canya a 3€",
            "detail": "Tota la setmana",
            "value": "3€",
            "min_purchase": None,
            "conditions": None,
            "active": False,
        },
    ],
    "butcher": [
        {
            "type": "discount",
            "label": "-8%",
            "title": "[DEMO] 8% en carn fresca",
            "detail": "Compra mínima 15€",
            "value": "8%",
            "min_purchase": "15€",
            "conditions": "No acumulable",
            "active": True,
        },
        {
            "type": "gift",
            "label": "Regal",
            "title": "[DEMO] Embotit de regal",
            "detail": "Amb compra superior a 30€",
            "value": "1 embotit",
            "min_purchase": "30€",
            "conditions": "Mentre n'hi hagi",
            "active": True,
        },
    ],
    "greengrocer": [
        {
            "type": "discount",
            "label": "-5%",
            "title": "[DEMO] 5% en verdura",
            "detail": "Producte de temporada",
            "value": "5%",
            "min_purchase": None,
            "conditions": None,
            "active": True,
        },
        {
            "type": "special_price",
            "label": "1€",
            "title": "[DEMO] Quilo de taronges 1€",
            "detail": "Oferta del dia",
            "value": "1€/kg",
            "min_purchase": None,
            "conditions": "Segons stock",
            "active": True,
        },
    ],
    "fishmonger": [
        {
            "type": "discount",
            "label": "-10%",
            "title": "[DEMO] 10% en peix blau",
            "detail": "Sardina, seitó i verat",
            "value": "10%",
            "min_purchase": None,
            "conditions": "Segons arribada",
            "active": True,
        },
        {
            "type": "two_for_one",
            "label": "2×1",
            "title": "[DEMO] 2×1 en musclos",
            "detail": "Divendres",
            "value": "2×1",
            "min_purchase": None,
            "conditions": "Només divendres",
            "active": False,
        },
    ],
    "pharmacy": [
        {
            "type": "discount",
            "label": "-5%",
            "title": "[DEMO] 5% en parafarmàcia",
            "detail": "Cremes i higiene",
            "value": "5%",
            "min_purchase": "10€",
            "conditions": "Excepte medicaments",
            "active": True,
        },
        {
            "type": "gift",
            "label": "Regal",
            "title": "[DEMO] Mostres de regal",
            "detail": "Amb compra superior a 25€",
            "value": "Mostres",
            "min_purchase": "25€",
            "conditions": "Mentre n'hi hagi",
            "active": True,
        },
    ],
    "bookstore": [
        {
            "type": "discount",
            "label": "-10%",
            "title": "[DEMO] 10% en novel·la",
            "detail": "Literatura en català",
            "value": "10%",
            "min_purchase": None,
            "conditions": None,
            "active": True,
        },
        {
            "type": "two_for_one",
            "label": "2×1",
            "title": "[DEMO] 2×1 en papereria",
            "detail": "Bolígrafs i llibretes",
            "value": "2×1",
            "min_purchase": None,
            "conditions": "Segona unitat al 50%",
            "active": True,
        },
    ],
    "clothing": [
        {
            "type": "discount",
            "label": "-15%",
            "title": "[DEMO] 15% de descompte",
            "detail": "Segona peça",
            "value": "15%",
            "min_purchase": None,
            "conditions": "La de menor import",
            "active": True,
        },
        {
            "type": "special_price",
            "label": "9,99€",
            "title": "[DEMO] Samarretes a 9,99€",
            "detail": "Col·lecció bàsica",
            "value": "9,99€",
            "min_purchase": None,
            "conditions": "Talles seleccionades",
            "active": False,
        },
    ],
    "hairdresser": [
        {
            "type": "discount",
            "label": "-10%",
            "title": "[DEMO] 10% en tall",
            "detail": "De dilluns a dimecres",
            "value": "10%",
            "min_purchase": None,
            "conditions": "Amb cita prèvia",
            "active": True,
        },
        {
            "type": "gift",
            "label": "Regal",
            "title": "[DEMO] Tractament capil·lar",
            "detail": "Amb el primer tall de color",
            "value": "1 tractament",
            "min_purchase": None,
            "conditions": "Nous clients",
            "active": True,
        },
    ],
    "services": [
        {
            "type": "discount",
            "label": "-10%",
            "title": "[DEMO] 10% en reparacions",
            "detail": "Ordinadors i mòbils",
            "value": "10%",
            "min_purchase": None,
            "conditions": "Mà d'obra",
            "active": True,
        },
        {
            "type": "special_price",
            "label": "5€",
            "title": "[DEMO] Bugada express 5€",
            "detail": "Fins a 5 kg",
            "value": "5€",
            "min_purchase": None,
            "conditions": "Recollida el mateix dia",
            "active": True,
        },
    ],
    "other": [
        {
            "type": "discount",
            "label": "-5%",
            "title": "[DEMO] 5% en souvenirs",
            "detail": "Productes de Malgrat",
            "value": "5%",
            "min_purchase": "10€",
            "conditions": None,
            "active": True,
        },
        {
            "type": "gift",
            "label": "Regal",
            "title": "[DEMO] Bossa de regal",
            "detail": "Amb qualsevol compra",
            "value": "1 bossa",
            "min_purchase": None,
            "conditions": "Mentre n'hi hagi",
            "active": False,
        },
    ],
}


def _id() -> str:
    return uuid.uuid4().hex


def _hours_for(spec: dict) -> dict:
    week = OpeningHours.default_week(
        opens=spec.get("opens", "09:00"),
        closes=spec.get("closes", "20:00"),
        weekend_closed=spec.get("weekend_closed", True),
    )
    opens_2 = spec.get("opens_2")
    closes_2 = spec.get("closes_2")
    if opens_2 and closes_2:
        data = week.model_dump()
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
            if not data[day]["closed"]:
                data[day]["opens_2"] = opens_2
                data[day]["closes_2"] = closes_2
        if not spec.get("weekend_closed", True):
            for day in ("saturday", "sunday"):
                if not data[day]["closed"]:
                    data[day]["opens_2"] = opens_2
                    data[day]["closes_2"] = closes_2
        return data
    return week.model_dump()


async def _demo_town(db) -> Town:
    town = await ensure_demo_town(db)
    cp = await db.get(TownPostalCode, DEMO_POSTAL_CODE)
    if not cp or cp.town_id != town.id:
        raise RuntimeError(f"Postal code {DEMO_POSTAL_CODE} missing for Demo KM0")
    return town


async def _purge_fake(db) -> None:
    """Reset demo ledger/users/shops; never wipe reward_media or admin rewards.

    Catalog [DEMO] rewards are upserted later with stable ids (see
    seed_fake_rewards). Admin-created fake rewards and any uploaded
    reward_media rows are left untouched.
    """
    from app.models import PointsTransaction, QrScan

    fake_user_ids = (
        await db.execute(select(User.id).where(User.is_fake.is_(True)))
    ).scalars().all()
    fake_shops = (
        await db.execute(select(Shop.id).where(Shop.is_fake.is_(True)))
    ).scalars().all()
    # Only purge seeded catalog redemptions/ledger — not reward rows/media.
    fake_redemptions = (
        await db.execute(
            select(Redemption.id).where(
                or_(
                    Redemption.is_fake.is_(True),
                    Redemption.user_id.in_(fake_user_ids or [""]),
                )
            )
        )
    ).scalars().all()

    if fake_redemptions:
        await db.execute(
            delete(RedemptionEvent).where(
                RedemptionEvent.redemption_id.in_(fake_redemptions)
            )
        )
        await db.execute(
            delete(Redemption).where(Redemption.id.in_(fake_redemptions))
        )
    await db.execute(delete(ShopPayment).where(ShopPayment.is_fake.is_(True)))
    await db.execute(
        delete(QrScan).where(
            or_(
                QrScan.is_fake.is_(True),
                QrScan.user_id.in_(fake_user_ids or [""]),
            )
        )
    )
    await db.execute(
        delete(PointsTransaction).where(
            or_(
                PointsTransaction.is_fake.is_(True),
                PointsTransaction.user_id.in_(fake_user_ids or [""]),
            )
        )
    )
    # Do NOT delete Reward / RewardMedia / RewardShop / PointAction here.
    # Catalogs are upserted in place so BO config (visible_home, points, media) persists.
    await db.execute(delete(Promotion).where(Promotion.is_fake.is_(True)))
    if fake_user_ids:
        for u in (
            await db.execute(select(User).where(User.id.in_(fake_user_ids)))
        ).scalars().all():
            u.shop_id = None
        await db.flush()
    if fake_shops:
        await db.execute(delete(ShopMedia).where(ShopMedia.shop_id.in_(fake_shops)))
        await db.execute(delete(Shop).where(Shop.id.in_(fake_shops)))
    if fake_user_ids:
        await db.execute(delete(User).where(User.id.in_(fake_user_ids)))
    await db.flush()


async def _create_shop(
    db,
    *,
    town_id: str,
    category: str,
    spec: dict,
    qr_code: str | None = None,
) -> Shop:
    shop = Shop(
        id=_id(),
        town_id=town_id,
        name=spec["name"],
        emoji=spec.get("emoji"),
        categories=[category],
        contact_email=f"demo+{slugify(spec['name'])}@km0lab.com",
        visit_points=spec.get("visit_points", 10),
        address=spec.get("address"),
        postal_code=DEMO_POSTAL_CODE,
        phone=spec.get("phone"),
        website=spec.get("website"),
        description=spec.get("description"),
        opening_hours=_hours_for(spec),
        status="active",
        qr_code=qr_code,
        is_fake=True,
    )
    db.add(shop)
    await db.flush()
    await ensure_shop_qr(db, shop)
    return shop


def _promos_for_shop(shop: Shop, category: str) -> list[Promotion]:
    templates = _PROMO_BY_CATEGORY.get(category) or _PROMO_BY_CATEGORY["other"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out: list[Promotion] = []
    for i, t in enumerate(templates[:2]):
        out.append(
            Promotion(
                id=_id(),
                shop_id=shop.id,
                type=t["type"],
                label=t["label"],
                title=t["title"],
                detail=t["detail"],
                value=t.get("value"),
                min_purchase=t.get("min_purchase"),
                valid_from=now - timedelta(days=7),
                valid_until=now + timedelta(days=60 + i * 15),
                conditions=t.get("conditions"),
                active=t.get("active", True),
                is_fake=True,
            )
        )
    return out


def _shop_by_name(shops: list[Shop], name: str) -> Shop:
    return next(s for s in shops if s.name == name)


async def _seed_fake_redemptions(
    db,
    *,
    town: Town,
    participants: list[User],
    shops: list[Shop],
    fleca: Shop,
) -> tuple[int, int, list[str]]:
    """Fake redemptions covering every voucher/delivery state + payments.

    Includes Fleca del Port vals for /comerc/vals (fixed codes 10001–10003
    pending, used unpaid, and one settled payment).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rewards = {
        r.name: r
        for r in (
            await db.execute(
                select(Reward).where(
                    Reward.is_fake.is_(True), Reward.town_id == town.id
                )
            )
        ).scalars().all()
    }
    forn = _shop_by_name(shops, "[DEMO] Forn Can Riera")
    cafe = _shop_by_name(shops, "[DEMO] Cafè Marítim")
    llibreria = _shop_by_name(shops, "[DEMO] Llibreria Lletraferit")
    by_email = {u.email: u for u in participants}

    # Top-up so every participant can afford their redemptions.
    for user in participants:
        await apply_points(
            db,
            user=user,
            points=1200,
            type="action",
            town_id=town.id,
            description="[DEMO] Punts per accions al programa",
        )

    created: list[Redemption] = []
    code_seq = 20000
    fleca_pending_codes: list[str] = []

    async def _redeem(
        *,
        email: str,
        reward_name: str,
        status: str,
        requested_days_ago: float,
        history: tuple[str, ...] = (),
        shop: Shop | None = None,
        amount: str | None = None,
        amount_applied: str | None = None,
        used_days_ago: float | None = None,
        delivered_days_ago: float | None = None,
        code: str | None = None,
    ) -> Redemption:
        nonlocal code_seq
        user = by_email[email]
        reward = rewards[reward_name]
        flow = (
            "voucher_qr" if reward.type in ("discount", "balance") else "delivery"
        )
        voucher_code = code
        if flow == "voucher_qr" and voucher_code is None:
            code_seq += 1
            voucher_code = str(code_seq)
        requested_at = now - timedelta(days=requested_days_ago)
        redemption = Redemption(
            id=_id(),
            town_id=town.id,
            user_id=user.id,
            reward_id=reward.id,
            flow=flow,
            points_spent=reward.points_required,
            status=status,
            code=voucher_code,
            amount=amount,
            shop_id=shop.id if shop else None,
            used_at=(
                now - timedelta(days=used_days_ago)
                if used_days_ago is not None
                else None
            ),
            amount_applied=amount_applied,
            delivered_at=(
                now - timedelta(days=delivered_days_ago)
                if delivered_days_ago is not None
                else None
            ),
            requested_at=requested_at,
            is_fake=True,
            created_at=requested_at,
        )
        db.add(redemption)
        if reward.stock is not None and reward.stock > 0:
            reward.stock -= 1
        await db.flush()
        # One event per transition, spread between request date and now.
        states = list(history) + [status]
        step = requested_days_ago / len(states)
        for i, state in enumerate(states):
            db.add(
                RedemptionEvent(
                    id=_id(),
                    redemption_id=redemption.id,
                    status=state,
                    note="Created" if i == 0 else None,
                    is_fake=True,
                    created_at=requested_at + timedelta(days=step * i),
                )
            )
        await apply_points(
            db,
            user=user,
            points=-reward.points_required,
            type="redemption",
            town_id=town.id,
            ref_id=redemption.id,
            description=f"[DEMO] Bescanvi {reward.name}",
        )
        created.append(redemption)
        return redemption

    used_history = ("pending_use",)

    # ── Fleca: pending codes for /comerc/vals (merchant validates) ──
    for code, reward_name, amount, email, days in (
        ("10001", "[DEMO] Bono 5 €", "5€", "veci1.demo@km0lab.com", 0.3),
        ("10002", "[DEMO] Bono 10 €", "10€", "veci2.demo@km0lab.com", 0.8),
        ("10003", "[DEMO] Bono 20 €", "20€", "veci4.demo@km0lab.com", 1.2),
    ):
        await _redeem(
            email=email,
            reward_name=reward_name,
            status="pending_use",
            requested_days_ago=days,
            amount=amount,
            code=code,
        )
        fleca_pending_codes.append(code)

    # ── Fleca: used unpaid (historial + KPI pendent) ────────────────
    await _redeem(
        email="veci3.demo@km0lab.com",
        reward_name="[DEMO] Bono 5 €",
        status="used",
        requested_days_ago=4,
        history=used_history,
        shop=fleca,
        amount="5€",
        amount_applied="5€",
        used_days_ago=2,
        code="10011",
    )
    await _redeem(
        email="veci5.demo@km0lab.com",
        reward_name="[DEMO] Bono 10 €",
        status="used",
        requested_days_ago=6,
        history=used_history,
        shop=fleca,
        amount="10€",
        amount_applied="10€",
        used_days_ago=3,
        code="10012",
    )

    # ── Fleca: used + settled (~15 €) for "Cobrats" ─────────────────
    fleca_paid_a = await _redeem(
        email=DEMO_RESIDENT_EMAIL,
        reward_name="[DEMO] Bono 5 €",
        status="used",
        requested_days_ago=18,
        history=used_history,
        shop=fleca,
        amount="5€",
        amount_applied="5€",
        used_days_ago=16,
        code="10013",
    )
    fleca_paid_b = await _redeem(
        email="veci1.demo@km0lab.com",
        reward_name="[DEMO] Bono 10 €",
        status="used",
        requested_days_ago=17,
        history=used_history,
        shop=fleca,
        amount="10€",
        amount_applied="10€",
        used_days_ago=15,
        code="10014",
    )
    fleca_payment = ShopPayment(
        id=_id(),
        town_id=town.id,
        shop_id=fleca.id,
        total_amount=Decimal("15.00"),
        note="[DEMO] Liquidació Fleca del Port",
        is_fake=True,
        created_at=now - timedelta(days=10),
    )
    db.add(fleca_payment)
    await db.flush()
    fleca_paid_a.payment_id = fleca_payment.id
    fleca_paid_b.payment_id = fleca_payment.id

    # ── Other pending use (admin Bescanvis) ─────────────────────────
    await _redeem(
        email="veci3.demo@km0lab.com",
        reward_name="[DEMO] 20% de descompte",
        status="pending_use",
        requested_days_ago=0.5,
        code="20001",
    )

    # ── Vouchers used, pending payment (other shops) ────────────────
    await _redeem(
        email="veci1.demo@km0lab.com",
        reward_name="[DEMO] Bono 5 €",
        status="used",
        requested_days_ago=4,
        history=used_history,
        shop=forn,
        amount="5€",
        amount_applied="5€",
        used_days_ago=2,
        code="20002",
    )
    await _redeem(
        email="veci2.demo@km0lab.com",
        reward_name="[DEMO] Bono 10 €",
        status="used",
        requested_days_ago=7,
        history=used_history,
        shop=cafe,
        amount="10€",
        amount_applied="10€",
        used_days_ago=5,
        code="20003",
    )
    await _redeem(
        email="veci3.demo@km0lab.com",
        reward_name="[DEMO] Bono 20 €",
        status="used",
        requested_days_ago=9,
        history=used_history,
        shop=forn,
        amount="20€",
        amount_applied="20€",
        used_days_ago=7,
        code="20004",
    )
    await _redeem(
        email="veci5.demo@km0lab.com",
        reward_name="[DEMO] 10% de descompte",
        status="used",
        requested_days_ago=5,
        history=used_history,
        shop=llibreria,
        amount_applied="3€",
        used_days_ago=3,
        code="20005",
    )
    await _redeem(
        email=DEMO_RESIDENT_EMAIL,
        reward_name="[DEMO] Bono 5 €",
        status="used",
        requested_days_ago=3,
        history=used_history,
        shop=cafe,
        amount="5€",
        amount_applied="5€",
        used_days_ago=1,
        code="20006",
    )

    # ── Café historic payment (~20 €) ───────────────────────────────
    paid_a = await _redeem(
        email="veci2.demo@km0lab.com",
        reward_name="[DEMO] Bono 10 €",
        status="used",
        requested_days_ago=22,
        history=used_history,
        shop=cafe,
        amount="10€",
        amount_applied="10€",
        used_days_ago=20,
        code="20007",
    )
    paid_b = await _redeem(
        email="veci3.demo@km0lab.com",
        reward_name="[DEMO] Bono 10 €",
        status="used",
        requested_days_ago=21,
        history=used_history,
        shop=cafe,
        amount="10€",
        amount_applied="10€",
        used_days_ago=19,
        code="20008",
    )
    payment = ShopPayment(
        id=_id(),
        town_id=town.id,
        shop_id=cafe.id,
        total_amount=Decimal("20.00"),
        note="[DEMO] Liquidació mensual de vals",
        is_fake=True,
        created_at=now - timedelta(days=15),
    )
    db.add(payment)
    await db.flush()
    paid_a.payment_id = payment.id
    paid_b.payment_id = payment.id

    # ── Deliveries in every stage ────────────────────────────────────
    await _redeem(
        email="veci1.demo@km0lab.com",
        reward_name="[DEMO] Bossa tote KM0",
        status="requested",
        requested_days_ago=1,
    )
    await _redeem(
        email="veci2.demo@km0lab.com",
        reward_name="[DEMO] Samarreta KM0 LAB",
        status="pending_preparation",
        requested_days_ago=3,
        history=("requested",),
    )
    await _redeem(
        email="veci3.demo@km0lab.com",
        reward_name="[DEMO] Visita guiada al far",
        status="prepared",
        requested_days_ago=5,
        history=("requested", "pending_preparation"),
    )
    await _redeem(
        email="veci5.demo@km0lab.com",
        reward_name="[DEMO] Taller de cuina local",
        status="pending_pickup",
        requested_days_ago=8,
        history=("requested", "pending_preparation", "prepared"),
    )
    await _redeem(
        email="veci4.demo@km0lab.com",
        reward_name="[DEMO] Bossa tote KM0",
        status="delivered",
        requested_days_ago=12,
        history=("requested", "pending_preparation", "prepared", "pending_pickup"),
        delivered_days_ago=10,
    )
    await _redeem(
        email=DEMO_RESIDENT_EMAIL,
        reward_name="[DEMO] Samarreta KM0 LAB",
        status="delivered",
        requested_days_ago=18,
        history=("requested", "pending_preparation", "prepared", "pending_pickup"),
        delivered_days_ago=16,
    )

    await db.flush()
    return len(created), 2, fleca_pending_codes


async def seed_demo() -> None:
    async with SessionLocal() as db:
        town = await _demo_town(db)
        await _purge_fake(db)

        # Drop leftover fake catalog on Malgrat so 08380 stays real-only.
        malgrat = await resolve_malgrat_town(db)
        if malgrat is not None and malgrat.id != town.id:
            await db.execute(
                delete(PointAction).where(
                    PointAction.town_id == malgrat.id,
                    PointAction.is_fake.is_(True),
                )
            )
            # Re-home leftover fake rewards still pointing at Malgrat.
            leftover_rewards = (
                await db.execute(
                    select(Reward).where(
                        Reward.town_id == malgrat.id,
                        Reward.is_fake.is_(True),
                    )
                )
            ).scalars().all()
            for reward in leftover_rewards:
                reward.town_id = town.id
            await db.flush()

        shops: list[Shop] = []
        shop_categories: list[str] = []
        merchant_shop: Shop | None = None

        for category, _order in DEFAULT_SHOP_CATEGORIES:
            specs = FAKE_SHOPS_BY_CATEGORY.get(category)
            if not specs or len(specs) < 2:
                raise RuntimeError(
                    f"Need 2 fake shops for category {category!r}"
                )
            for i, spec in enumerate(specs[:2]):
                # Keep stable QR on the primary demo merchant shop.
                qr = "DEMO-KM0-QR" if category == "bakery" and i == 0 else None
                shop = await _create_shop(
                    db,
                    town_id=town.id,
                    category=category,
                    spec=spec,
                    qr_code=qr,
                )
                shops.append(shop)
                shop_categories.append(category)
                if category == "bakery" and i == 0:
                    merchant_shop = shop
                    shop.contact_email = DEMO_MERCHANT_EMAIL

        assert merchant_shop is not None

        promo_count = 0
        for shop, category in zip(shops, shop_categories, strict=True):
            for promo in _promos_for_shop(shop, category):
                db.add(promo)
                promo_count += 1
        await db.flush()

        action_count = await ensure_town_point_actions(db, town.id, is_fake=True)

        reward_count = await seed_fake_rewards(
            db, town_id=town.id, shop_id=merchant_shop.id
        )

        admin = User(
            id=_id(),
            email=DEMO_ADMIN_EMAIL,
            slug="demo-admin",
            first_name="Demo",
            last_name="Admin",
            postal_code=DEMO_POSTAL_CODE,
            is_fake=True,
            points=0,
            **flags_from_roles(["resident", "admin"]),
        )
        merchant = User(
            id=_id(),
            email=DEMO_MERCHANT_EMAIL,
            slug="demo-merchant",
            first_name="Demo",
            last_name="Merchant",
            postal_code=DEMO_POSTAL_CODE,
            shop_id=merchant_shop.id,
            is_fake=True,
            points=0,
            **flags_from_roles(["resident", "merchant"]),
        )
        resident = User(
            id=_id(),
            email=DEMO_RESIDENT_EMAIL,
            slug="demo-resident",
            first_name="Demo",
            last_name="Resident",
            postal_code=DEMO_POSTAL_CODE,
            is_fake=True,
            points=0,
            **flags_from_roles(["resident"]),
        )
        db.add_all([admin, merchant, resident])
        await db.flush()

        await apply_points(
            db,
            user=resident,
            points=settings.welcome_points,
            type="welcome",
            town_id=town.id,
            description="[DEMO] Welcome bonus",
        )
        await apply_points(
            db,
            user=merchant,
            points=settings.welcome_points,
            type="welcome",
            town_id=town.id,
            description="[DEMO] Welcome bonus",
        )

        fake_residents: list[User] = []
        for email, name, pts in FAKE_RESIDENTS:
            first, last = split_full_name(name)
            u = User(
                id=_id(),
                email=email,
                slug=slugify(name),
                first_name=first,
                last_name=last,
                postal_code=DEMO_POSTAL_CODE,
                is_fake=True,
                contact_shared=True,
                points=0,
                **flags_from_roles(["resident"]),
            )
            db.add(u)
            await db.flush()
            await apply_points(
                db,
                user=u,
                points=pts,
                type="welcome",
                town_id=town.id,
                description="[DEMO] Fake resident balance",
            )
            fake_residents.append(u)

        redemption_count, payment_count, fleca_codes = await _seed_fake_redemptions(
            db,
            town=town,
            participants=[*fake_residents, resident],
            shops=shops,
            fleca=merchant_shop,
        )

        await db.commit()
        n_cats = len(DEFAULT_SHOP_CATEGORIES)
        print(f"Demo seed OK ({town.name} / CP {DEMO_POSTAL_CODE})")
        print(f"  {len(shops)} fake shops ({n_cats} categories x 2) + QR PNG")
        print(f"  {promo_count} fake promotions (2 per shop)")
        print(f"  {action_count} fake point actions (demo admin catalog)")
        print(f"  {reward_count} fake rewards (2+ per type + bonos 5/10/20/50 EUR)")
        print(
            f"  {redemption_count} fake redemptions + {payment_count} shop payments"
        )
        print(
            f"  Fleca pending codes (Validar vals): "
            f"{' / '.join(fleca_codes)}"
        )
        print(f"  {DEMO_RESIDENT_EMAIL} / 123456  -> resident")
        print(f"  {DEMO_MERCHANT_EMAIL} / 123456  -> merchant+resident")
        print(f"  {DEMO_ADMIN_EMAIL} / 123456     -> admin+resident")
        print(f"  + {len(FAKE_RESIDENTS)} fake residents for admin stats")
        print("  QR demo shop: DEMO-KM0-QR")
        print(f"  Demo postal code: {DEMO_POSTAL_CODE} ({town.name})")
        print("  Malgrat 08380 stays real-only (municipal fallback for agenda/news)")


if __name__ == "__main__":
    asyncio.run(seed_demo())
