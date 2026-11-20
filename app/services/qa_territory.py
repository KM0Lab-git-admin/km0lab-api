"""QA territory fixture (seed). See ``app/qa.py`` and ``qa_purge.py``.

Idempotent: running it again repairs the fixture (names, prices, stock)
without duplicating anything. Every row is on the ``is_fake`` partition.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    PointAction,
    PointsTransaction,
    Promotion,
    Reward,
    Shop,
    Town,
    TownPostalCode,
    User,
)
from app.qa import (
    QA_ADMIN_EMAIL,
    QA_MERCHANT_EMAIL,
    QA_POSTAL_CODE,
    QA_RESIDENT_EMAIL,
    QA_TOWN_NAME,
    QA_TOWN_SLUG,
)
from app.services.shop_qr import ensure_shop_qr

QA_VISIT_POINTS = 20
QA_RESIDENT_START_POINTS = 1000
QA_SIGNUP_POINTS = 200
QA_INVITE_PERSON_POINTS = 150
QA_INVITE_BUSINESS_POINTS = 500


def _stable_id(key: str) -> str:
    return hashlib.sha256(f"qa-territory:{key}".encode()).hexdigest()[:32]


def _i18n(ca: str, es: str, en: str) -> dict[str, str]:
    return {"ca": ca, "es": es, "en": en}


# ── Fixture definition ────────────────────────────────────────────────

QA_SHOPS: tuple[dict, ...] = (
    {
        "key": "shop-1",
        "name": "[QA] Forn de proves",
        "emoji": "🥖",
        "categories": ["bakery"],
        "qr_code": "qa-shop-1",
        "address": "Carrer de les Proves, 1",
    },
    {
        "key": "shop-2",
        "name": "[QA] Llibreria de proves",
        "emoji": "📚",
        "categories": ["bookstore"],
        "qr_code": "qa-shop-2",
        "address": "Carrer de les Proves, 2",
    },
    {
        "key": "shop-3",
        "name": "[QA] Cafè de proves",
        "emoji": "☕",
        "categories": ["cafe"],
        "qr_code": "qa-shop-3",
        "address": "Carrer de les Proves, 3",
    },
)

QA_REWARDS: tuple[dict, ...] = (
    {
        "key": "reward-voucher",
        "name": _i18n("[QA] Val de 5 €", "[QA] Vale de 5 €", "[QA] €5 voucher"),
        "type": "discount",
        "points_required": 50,
        "value": "5 €",
        "stock": None,
    },
    {
        "key": "reward-balance",
        "name": _i18n(
            "[QA] Saldo de 10 €", "[QA] Saldo de 10 €", "[QA] €10 balance"
        ),
        "type": "balance",
        "points_required": 80,
        "value": "10 €",
        "stock": None,
    },
    {
        "key": "reward-product",
        "name": _i18n(
            "[QA] Bossa de proves", "[QA] Bolsa de pruebas", "[QA] Test tote bag"
        ),
        "type": "product",
        "points_required": 30,
        "value": None,
        "stock": None,
    },
    {
        "key": "reward-expensive",
        "name": _i18n(
            "[QA] Experiència inassolible",
            "[QA] Experiencia inalcanzable",
            "[QA] Out-of-reach experience",
        ),
        "type": "experience",
        "points_required": 900_000,
        "value": None,
        "stock": None,
    },
    {
        "key": "reward-soldout",
        "name": _i18n(
            "[QA] Samarreta esgotada",
            "[QA] Camiseta agotada",
            "[QA] Sold-out T-shirt",
        ),
        "type": "merchandise",
        "points_required": 10,
        "value": None,
        "stock": 0,
    },
)

QA_ACTIONS: tuple[dict, ...] = (
    {
        "key": "action-signup",
        "type": "signup",
        "name": _i18n(
            "[QA] Primer registre", "[QA] Primer registro", "[QA] First signup"
        ),
        "points": QA_SIGNUP_POINTS,
        "per_user_limit": 1,
        "visible_home": False,
    },
    {
        "key": "action-qr-scan",
        "type": "qr_scan",
        "name": _i18n(
            "[QA] Visita un comerç",
            "[QA] Visita un comercio",
            "[QA] Visit a shop",
        ),
        "points": QA_VISIT_POINTS,
        "cooldown_days": 30,
        "visible_home": True,
    },
    {
        "key": "action-invite-person",
        "type": "invite_person",
        "name": _i18n(
            "[QA] Convida un veí", "[QA] Invita a un vecino", "[QA] Invite a neighbour"
        ),
        "points": QA_INVITE_PERSON_POINTS,
        "visible_home": True,
    },
    {
        "key": "action-invite-business",
        "type": "invite_business",
        "name": _i18n(
            "[QA] Convida un comerç",
            "[QA] Invita a un comercio",
            "[QA] Invite a business",
        ),
        "points": QA_INVITE_BUSINESS_POINTS,
        "visible_home": True,
    },
    {
        "key": "action-custom",
        "type": "custom",
        "name": _i18n(
            "[QA] Enquesta de proves",
            "[QA] Encuesta de pruebas",
            "[QA] Test survey",
        ),
        "points": 30,
        "per_user_limit": 1,
        "visible_home": True,
    },
)

QA_USERS: tuple[dict, ...] = (
    {
        "email": QA_RESIDENT_EMAIL,
        "slug": "qa-vecino",
        "first_name": "[QA] Veí",
        "last_name": "De Proves",
        "is_admin": False,
        "shop_key": None,
        "points": QA_RESIDENT_START_POINTS,
    },
    {
        "email": QA_MERCHANT_EMAIL,
        "slug": "qa-comerc",
        "first_name": "[QA] Comerç",
        "last_name": "De Proves",
        "is_admin": False,
        "shop_key": "shop-1",
        "points": 0,
    },
    {
        "email": QA_ADMIN_EMAIL,
        "slug": "qa-admin",
        "first_name": "[QA] Admin",
        "last_name": "De Proves",
        "is_admin": True,
        "shop_key": None,
        "points": 0,
    },
)

QA_FIXTURE_SHOP_IDS: frozenset[str] = frozenset(
    _stable_id(s["key"]) for s in QA_SHOPS
)


# ── Seed ──────────────────────────────────────────────────────────────


async def _ensure_town(db: AsyncSession) -> Town:
    postal = await db.get(TownPostalCode, QA_POSTAL_CODE)
    town = await db.get(Town, postal.town_id) if postal else None
    if town is None:
        town = (
            await db.execute(select(Town).where(Town.slug == QA_TOWN_SLUG))
        ).scalars().first()
    if town is None:
        town = Town(id=_stable_id("town"), slug=QA_TOWN_SLUG, name=QA_TOWN_NAME)
        db.add(town)
    town.name = QA_TOWN_NAME
    town.slug = QA_TOWN_SLUG
    town.entity_name = "[QA] KM0 LAB proves"
    town.entity_type = "private"
    town.contact_email = QA_ADMIN_EMAIL
    town.manager_name = "[QA] Admin De Proves"
    town.default_lang = "ca"
    town.default_visit_points = QA_VISIT_POINTS
    await db.flush()
    if postal is None:
        db.add(
            TownPostalCode(
                postal_code=QA_POSTAL_CODE, town_id=town.id, is_primary=True
            )
        )
        await db.flush()
    return town


async def _ensure_shops(db: AsyncSession, town: Town) -> dict[str, Shop]:
    shops: dict[str, Shop] = {}
    for spec in QA_SHOPS:
        shop_id = _stable_id(spec["key"])
        shop = await db.get(Shop, shop_id)
        if shop is None:
            shop = Shop(id=shop_id, town_id=town.id, name=spec["name"])
            db.add(shop)
        shop.town_id = town.id
        shop.name = spec["name"]
        shop.emoji = spec["emoji"]
        shop.categories = spec["categories"]
        shop.contact_email = QA_MERCHANT_EMAIL
        shop.visit_points = QA_VISIT_POINTS
        shop.address = spec["address"]
        shop.postal_code = QA_POSTAL_CODE
        shop.description = "Comerç de proves automàtiques. No és real."
        shop.status = "active"
        shop.qr_code = spec["qr_code"]
        shop.is_fake = True
        await db.flush()
        await ensure_shop_qr(db, shop)
        shops[spec["key"]] = shop

    promo_id = _stable_id("promo-1")
    promo = await db.get(Promotion, promo_id)
    if promo is None:
        promo = Promotion(
            id=promo_id,
            shop_id=shops["shop-1"].id,
            type="discount",
            title="[QA] 10 % en pa de proves",
        )
        db.add(promo)
    promo.shop_id = shops["shop-1"].id
    promo.type = "discount"
    promo.label = "-10 %"
    promo.title = "[QA] 10 % en pa de proves"
    promo.title_i18n = _i18n(
        "[QA] 10 % en pa de proves",
        "[QA] 10 % en pan de pruebas",
        "[QA] 10% off test bread",
    )
    promo.detail = "Promoció de proves automàtiques."
    promo.value = "10 %"
    promo.active = True
    promo.valid_from = None
    promo.valid_until = None
    promo.is_fake = True
    await db.flush()
    return shops


async def _ensure_rewards(db: AsyncSession, town: Town) -> None:
    for spec in QA_REWARDS:
        reward_id = _stable_id(spec["key"])
        reward = await db.get(Reward, reward_id)
        if reward is None:
            reward = Reward(
                id=reward_id,
                town_id=town.id,
                name=spec["name"]["ca"],
                type=spec["type"],
                points_required=spec["points_required"],
            )
            db.add(reward)
        reward.town_id = town.id
        reward.name = spec["name"]["ca"]
        reward.name_i18n = spec["name"]
        reward.description = "Premi de proves automàtiques. No és real."
        reward.type = spec["type"]
        reward.points_required = spec["points_required"]
        reward.value = spec["value"]
        # Reset on every seed: tests may have consumed finite stock.
        reward.stock = spec["stock"]
        reward.status = "active"
        reward.valid_from = None
        reward.valid_until = None
        reward.is_fake = True
    await db.flush()


async def _ensure_actions(db: AsyncSession, town: Town) -> None:
    for spec in QA_ACTIONS:
        action_id = _stable_id(spec["key"])
        action = await db.get(PointAction, action_id)
        if action is None:
            action = PointAction(
                id=action_id,
                town_id=town.id,
                type=spec["type"],
                name=spec["name"]["ca"],
            )
            db.add(action)
        action.town_id = town.id
        action.type = spec["type"]
        action.name = spec["name"]["ca"]
        action.name_i18n = spec["name"]
        action.description = "Acció de proves automàtiques."
        action.points = spec["points"]
        action.per_user_limit = spec.get("per_user_limit")
        action.cooldown_days = spec.get("cooldown_days")
        action.total_limit = None
        action.valid_from = None
        action.valid_until = None
        action.active = True
        action.visible_home = spec["visible_home"]
        action.is_fake = True
    await db.flush()


async def _ensure_users(
    db: AsyncSession, town: Town, shops: dict[str, Shop]
) -> None:
    for spec in QA_USERS:
        user = (
            await db.execute(select(User).where(User.email == spec["email"]))
        ).scalars().first()
        shop = shops[spec["shop_key"]] if spec["shop_key"] else None
        created = user is None
        if user is None:
            user = User(
                id=_stable_id(f"user:{spec['email']}"),
                email=spec["email"],
                slug=spec["slug"],
                points=0,
            )
            db.add(user)
        user.first_name = spec["first_name"]
        user.last_name = spec["last_name"]
        user.lang = "ca"
        user.postal_code = QA_POSTAL_CODE
        user.is_resident = True
        user.is_admin = spec["is_admin"]
        user.is_merchant = shop is not None
        user.shop_id = shop.id if shop else None
        user.is_fake = True
        await db.flush()
        if created and spec["points"] > 0:
            # Ledger is the source of truth: the starting balance is a
            # movement, not a bare number on the user.
            db.add(
                PointsTransaction(
                    user_id=user.id,
                    town_id=town.id,
                    type="adjustment",
                    points=spec["points"],
                    ref_id=_stable_id(f"start:{spec['email']}"),
                    description="[QA] Saldo inicial de proves",
                    is_fake=True,
                )
            )
            user.points = spec["points"]
            await db.flush()


async def ensure_qa_territory(db: AsyncSession) -> dict[str, int]:
    """Idempotent: create or repair the QA fixture. Caller commits."""
    town = await _ensure_town(db)
    shops = await _ensure_shops(db, town)
    await _ensure_rewards(db, town)
    await _ensure_actions(db, town)
    await _ensure_users(db, town, shops)
    return {
        "towns": 1,
        "shops": len(QA_SHOPS),
        "rewards": len(QA_REWARDS),
        "point_actions": len(QA_ACTIONS),
        "users": len(QA_USERS),
    }

