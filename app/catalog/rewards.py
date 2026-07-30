"""Reward type enum + demo catalog for Malgrat (is_fake partition)."""

from __future__ import annotations

import hashlib
import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reward, RewardShop


def demo_reward_id(name: str) -> str:
    """Stable id so re-seed updates in place and keeps reward_media."""
    return hashlib.sha256(f"demo-reward:{name}".encode()).hexdigest()[:32]


DEMO_REWARD_NAME_PREFIX = "[DEMO]"

# BO labels: Descuento | Saldo | Producto | Servicio | Merchandising | Experiencia
class RewardType(StrEnum):
    DISCOUNT = "discount"
    BALANCE = "balance"
    PRODUCT = "product"
    SERVICE = "service"
    MERCHANDISE = "merchandise"
    EXPERIENCE = "experience"


REWARD_TYPE_PATTERN = (
    "^(discount|balance|product|service|merchandise|experience)$"
)

# ≥2 per type; balance includes euro vouchers 5 / 10 / 20 / 50 €
FAKE_DEMO_REWARDS: tuple[dict[str, Any], ...] = (
    # ── Descuento ────────────────────────────────────────────────────
    {
        "type": RewardType.DISCOUNT,
        "name": "[DEMO] 10% de descompte",
        "description": "Descompte del 10% en compra mínima de 20 €",
        "points_required": 80,
        "value": "10%",
        "stock": 40,
        "conditions": "Mínim 20 € de compra",
    },
    {
        "type": RewardType.DISCOUNT,
        "name": "[DEMO] 20% de descompte",
        "description": "Descompte del 20% en una compra",
        "points_required": 150,
        "value": "20%",
        "stock": 25,
        "conditions": "No acumulable amb altres ofertes",
    },
    # ── Saldo (bonos 5 / 10 / 20 / 50 €) ─────────────────────────────
    {
        "type": RewardType.BALANCE,
        "name": "[DEMO] Bono 5 €",
        "description": "Saldo de 5 € per gastar en comerços adherits",
        "points_required": 50,
        "value": "5€",
        "stock": 100,
    },
    {
        "type": RewardType.BALANCE,
        "name": "[DEMO] Bono 10 €",
        "description": "Saldo de 10 € per gastar en comerços adherits",
        "points_required": 100,
        "value": "10€",
        "stock": 80,
    },
    {
        "type": RewardType.BALANCE,
        "name": "[DEMO] Bono 20 €",
        "description": "Saldo de 20 € per gastar en comerços adherits",
        "points_required": 200,
        "value": "20€",
        "stock": 50,
    },
    {
        "type": RewardType.BALANCE,
        "name": "[DEMO] Bono 50 €",
        "description": "Saldo de 50 € per gastar en comerços adherits",
        "points_required": 500,
        "value": "50€",
        "stock": 20,
    },
    # ── Producto ─────────────────────────────────────────────────────
    {
        "type": RewardType.PRODUCT,
        "name": "[DEMO] Pa de pagès",
        "description": "Una peça de pa de pagès a fleques adherides",
        "points_required": 60,
        "value": None,
        "stock": 30,
    },
    {
        "type": RewardType.PRODUCT,
        "name": "[DEMO] Ampolla d'oli local",
        "description": "Ampolla d'oli d'oliva verge extra de proximitat",
        "points_required": 180,
        "value": "500 ml",
        "stock": 15,
    },
    # ── Servicio ─────────────────────────────────────────────────────
    {
        "type": RewardType.SERVICE,
        "name": "[DEMO] Tall de cabell",
        "description": "Servei de tall bàsic en perruqueries adherides",
        "points_required": 250,
        "value": None,
        "stock": 20,
    },
    {
        "type": RewardType.SERVICE,
        "name": "[DEMO] Rentat de cotxe",
        "description": "Rentat exterior en tallers / rentadors adherits",
        "points_required": 220,
        "value": None,
        "stock": 15,
    },
    # ── Merchandising ────────────────────────────────────────────────
    {
        "type": RewardType.MERCHANDISE,
        "name": "[DEMO] Bossa tote KM0",
        "description": "Bossa de tela reutilitzable del programa",
        "points_required": 120,
        "value": None,
        "stock": 40,
    },
    {
        "type": RewardType.MERCHANDISE,
        "name": "[DEMO] Samarreta KM0 LAB",
        "description": "Samarreta oficial de cotó orgànic",
        "points_required": 300,
        "value": None,
        "stock": 25,
    },
    # ── Experiencia ──────────────────────────────────────────────────
    {
        "type": RewardType.EXPERIENCE,
        "name": "[DEMO] Visita guiada al far",
        "description": "Inscripció a una visita guiada cultural a Malgrat",
        "points_required": 200,
        "value": "1 persona",
        "stock": 12,
    },
    {
        "type": RewardType.EXPERIENCE,
        "name": "[DEMO] Taller de cuina local",
        "description": "Participació en un taller gastronòmic municipal",
        "points_required": 350,
        "value": "1 plaça",
        "stock": 10,
    },
)


def _uuid() -> str:
    return uuid.uuid4().hex


async def seed_fake_rewards(
    db: AsyncSession,
    *,
    town_id: str,
    shop_id: str | None = None,
) -> int:
    """Upsert fake demo catalog rewards without wiping reward_media.

    Uses stable ids derived from the reward name so re-running seed_demo
    updates the same rows. Legacy random-id [DEMO] twins are merged: their
    uploaded media is reattached to the stable id, then the twin is removed.
    Admin-created rewards (name without [DEMO] prefix) are never touched.
    """
    from app.models import RewardMedia

    catalog_ids: set[str] = set()
    for spec in FAKE_DEMO_REWARDS:
        rid = demo_reward_id(spec["name"])
        catalog_ids.add(rid)
        existing = await db.get(Reward, rid)
        if existing:
            existing.town_id = town_id
            existing.name = spec["name"]
            existing.description = spec.get("description") or ""
            existing.type = str(spec["type"])
            existing.points_required = spec["points_required"]
            existing.value = spec.get("value")
            existing.stock = spec.get("stock")
            existing.conditions = spec.get("conditions")
            existing.status = "active"
            existing.is_fake = True
            reward = existing
        else:
            reward = Reward(
                id=rid,
                town_id=town_id,
                name=spec["name"],
                description=spec.get("description") or "",
                type=str(spec["type"]),
                points_required=spec["points_required"],
                value=spec.get("value"),
                stock=spec.get("stock"),
                conditions=spec.get("conditions"),
                status="active",
                is_fake=True,
            )
            db.add(reward)
        await db.flush()

        # Migrate media from legacy random-id duplicates of this catalog name.
        legacy_twins = (
            await db.execute(
                select(Reward).where(
                    Reward.is_fake.is_(True),
                    Reward.name == spec["name"],
                    Reward.id != rid,
                )
            )
        ).scalars().all()
        stable_media = (
            await db.execute(
                select(RewardMedia).where(RewardMedia.reward_id == rid)
            )
        ).scalar_one_or_none()
        for twin in legacy_twins:
            twin_media = (
                await db.execute(
                    select(RewardMedia).where(RewardMedia.reward_id == twin.id)
                )
            ).scalar_one_or_none()
            if twin_media and stable_media is None:
                twin_media.reward_id = rid
                stable_media = twin_media
                await db.flush()
            await db.execute(
                delete(RewardShop).where(RewardShop.reward_id == twin.id)
            )
            await db.delete(twin)
        await db.flush()

        await db.execute(
            delete(RewardShop).where(RewardShop.reward_id == reward.id)
        )
        # Euro vouchers usable at the demo merchant shop; rest = all shops.
        if shop_id and spec["type"] == RewardType.BALANCE:
            db.add(RewardShop(id=_uuid(), reward_id=reward.id, shop_id=shop_id))

    # Remove obsolete [DEMO] catalog rows no longer in FAKE_DEMO_REWARDS,
    # but never drop a reward that still has uploaded media.
    ids_with_media = set(
        (await db.execute(select(RewardMedia.reward_id))).scalars().all()
    )
    obsolete = (
        await db.execute(
            select(Reward.id).where(
                Reward.is_fake.is_(True),
                Reward.name.startswith(DEMO_REWARD_NAME_PREFIX),
                Reward.id.not_in(catalog_ids or [""]),
            )
        )
    ).scalars().all()
    to_drop = [rid for rid in obsolete if rid not in ids_with_media]
    if to_drop:
        await db.execute(
            delete(RewardShop).where(RewardShop.reward_id.in_(to_drop))
        )
        await db.execute(delete(Reward).where(Reward.id.in_(to_drop)))

    await db.flush()
    return len(FAKE_DEMO_REWARDS)
