"""Reward type enum + demo catalog for Malgrat (is_fake partition)."""

from __future__ import annotations

import hashlib
import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reward, RewardShop


def demo_reward_id(name: str) -> str:
    """Stable id so re-seed updates in place and keeps reward_media."""
    return hashlib.sha256(f"demo-reward:{name}".encode()).hexdigest()[:32]


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
    """Insert missing fake demo catalog rewards only — never overwrite.

    Existing rows (any field, media, shop links, stock, i18n) are left
    untouched. Stable ids are used only for new inserts. Duplicates by
    catalog name are kept as-is (no merge/delete).
    """
    created = 0
    for spec in FAKE_DEMO_REWARDS:
        rid = demo_reward_id(spec["name"])
        existing = await db.get(Reward, rid)
        if existing is None:
            by_name = (
                await db.execute(
                    select(Reward).where(
                        Reward.is_fake.is_(True),
                        Reward.town_id == town_id,
                        Reward.name == spec["name"],
                    )
                )
            ).scalars().first()
            if by_name is not None:
                existing = by_name

        if existing is not None:
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
            created += 1

        # Link balance vouchers to the demo merchant only when no shop link yet.
        if shop_id and spec["type"] == RewardType.BALANCE:
            has_link = (
                await db.execute(
                    select(RewardShop.id).where(RewardShop.reward_id == reward.id)
                )
            ).scalars().first()
            if has_link is None:
                db.add(
                    RewardShop(id=_uuid(), reward_id=reward.id, shop_id=shop_id)
                )

    await db.flush()
    return created if created else len(FAKE_DEMO_REWARDS)
