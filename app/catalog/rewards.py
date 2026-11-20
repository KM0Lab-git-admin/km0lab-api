"""Reward type enum + demo catalog for Malgrat (is_fake partition)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Redemption, Reward, RewardMedia, RewardShop
from app.services.reward_media import media_public_path, media_version
from app.services.towns import ensure_demo_town

_REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_REWARD_MEDIA_DIR = _REPO_ROOT / "scripts" / "seed_media" / "rewards"


def demo_reward_id(name: str) -> str:
    """Stable id so re-seed updates in place and keeps reward_media."""
    return hashlib.sha256(f"demo-reward:{name}".encode()).hexdigest()[:32]


DEMO_NAME_PREFIX = "[DEMO] "


def real_reward_id(town_id: str, name: str) -> str:
    """Stable id for real catalog rewards, namespaced per town."""
    return hashlib.sha256(
        f"real-reward:{town_id}:{name}".encode()
    ).hexdigest()[:32]


def real_reward_name(name: str) -> str:
    """Catalog name without the demo marker."""
    return name.removeprefix(DEMO_NAME_PREFIX)


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
        "image": "val-5.png",
    },
    {
        "type": RewardType.BALANCE,
        "name": "[DEMO] Bono 10 €",
        "description": "Saldo de 10 € per gastar en comerços adherits",
        "points_required": 100,
        "value": "10€",
        "stock": 80,
        "image": "val-10.png",
    },
    {
        "type": RewardType.BALANCE,
        "name": "[DEMO] Bono 20 €",
        "description": "Saldo de 20 € per gastar en comerços adherits",
        "points_required": 200,
        "value": "20€",
        "stock": 50,
        "image": "val-20.png",
    },
    {
        "type": RewardType.BALANCE,
        "name": "[DEMO] Bono 50 €",
        "description": "Saldo de 50 € per gastar en comerços adherits",
        "points_required": 500,
        "value": "50€",
        "stock": 20,
        "image": "val-50.png",
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
        "image": "recompensa-bossa.png",
    },
    {
        "type": RewardType.MERCHANDISE,
        "name": "[DEMO] Samarreta KM0 LAB",
        "description": "Samarreta oficial de cotó orgànic",
        "points_required": 300,
        "value": None,
        "stock": 25,
        "image": "recompensa-camiseta.png",
    },
    {
        "type": RewardType.MERCHANDISE,
        "name": "[DEMO] Gorra KM0 LAB",
        "description": "Gorra oficial del programa KM0 LAB.",
        "points_required": 180,
        "value": "1 unitat",
        "stock": 45,
        "image": "recompensa-gorra.png",
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
    {
        "type": RewardType.EXPERIENCE,
        "name": "[DEMO] Entrada de cinema",
        "description": "Una entrada per a qualsevol sessió no premium.",
        "points_required": 200,
        "value": "1 entrada",
        "stock": 20,
        "image": "recompensa-cine.png",
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

    await upsert_demo_reward_images(db, town_id=town_id)
    await db.flush()
    return created if created else len(FAKE_DEMO_REWARDS)


def _strip_demo_prefix_i18n(i18n: dict | None) -> dict | None:
    if not i18n:
        return i18n
    return {
        lang: text.removeprefix(DEMO_NAME_PREFIX) if isinstance(text, str) else text
        for lang, text in i18n.items()
    }


async def _mirror_demo_media(
    db: AsyncSession, *, source: Reward, target: Reward
) -> None:
    """Copy the demo reward's image bytes onto the real mirror."""
    src = source.media
    if src is None:
        return
    # Explicit query: relationship access on flushed/new objects would
    # trigger a lazy load, which is not allowed in async sessions.
    dst = (
        await db.execute(
            select(RewardMedia).where(RewardMedia.reward_id == target.id)
        )
    ).scalar_one_or_none()
    if dst is not None and dst.data == src.data:
        return
    if dst is None:
        dst = RewardMedia(
            id=_uuid(),
            reward_id=target.id,
            content_type=src.content_type,
            data=src.data,
            byte_size=src.byte_size,
        )
        db.add(dst)
    else:
        dst.content_type = src.content_type
        dst.data = src.data
        dst.byte_size = src.byte_size
        dst.updated_at = datetime.utcnow()
    # Version before flush: after flush the server-default timestamps are
    # expired and reading them would trigger a lazy refresh (no async IO).
    target.image_url = media_public_path(target.id, media_version(dst))
    await db.flush()


@dataclass
class CatalogSyncReport:
    """What copying the catalog did (or would do) to one municipality."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    # What a resident would notice in a reward the municipality already
    # has: "name: points 1000 -> 80". Texts and image are not listed.
    changed: list[str] = field(default_factory=list)
    # Copies whose catalog reward no longer exists.
    retired: list[str] = field(default_factory=list)  # redeemed: kept, off
    deleted: list[str] = field(default_factory=list)  # never redeemed
    # Rewards of the municipality that are not copies of the catalog.
    untouched: list[str] = field(default_factory=list)
    new_status: str = "inactive"

    @property
    def synced(self) -> int:
        return len(self.created) + len(self.updated)


async def sync_catalog_rewards(
    db: AsyncSession,
    *,
    town_id: str,
    shop_id: str | None = None,
    activate_new: bool = False,
) -> CatalogSyncReport:
    """Copy the reward catalog (Demo KM0, CP 00000) to a real municipality.

    The catalog is the same for everyone; what each municipality decides is
    which rewards it offers. So:

    - A reward the municipality does not have yet is created **inactive**:
      its admin switches it on. ``activate_new`` (local seeds only) keeps
      the catalog's own status instead.
    - A reward it already has gets the catalog's content (name, texts,
      points, value, validity, image) and **keeps its status and its
      stock**: both are the municipality's (the admin's switch, and the
      units its residents have already redeemed).
    - A copy whose catalog reward is gone is deleted if nobody ever
      redeemed it; otherwise it is kept and switched off.
    - A reward that is not a copy of the catalog is never touched.

    A copy is recognised by ``catalog_id``. Rows that predate that link
    are adopted by name the first time; after that, renaming a catalog
    reward renames its copies instead of duplicating them.
    """
    report = CatalogSyncReport(new_status="catalog" if activate_new else "inactive")
    demo_town = await ensure_demo_town(db)
    if town_id == demo_town.id:
        return report

    async def _demo_rows() -> list[Reward]:
        return (
            (
                await db.execute(
                    select(Reward)
                    .options(selectinload(Reward.media))
                    .where(
                        Reward.town_id == demo_town.id,
                        Reward.is_fake.is_(True),
                    )
                    .order_by(Reward.name)
                )
            )
            .scalars()
            .all()
        )

    demo_rows = await _demo_rows()
    if not demo_rows:
        # Fresh DB: seed the showcase first, then mirror it.
        await seed_fake_rewards(db, town_id=demo_town.id)
        demo_rows = await _demo_rows()

    # Media/shops eager-loaded so the ORM delete cascade needs no lazy IO.
    existing = (
        await db.execute(
            select(Reward)
            .options(selectinload(Reward.media), selectinload(Reward.shops))
            .where(Reward.town_id == town_id, Reward.is_fake.is_(False))
            .order_by(Reward.name)
        )
    ).scalars().all()
    by_catalog = {r.catalog_id: r for r in existing if r.catalog_id}
    by_id = {r.id: r for r in existing}
    unlinked_by_name = {r.name: r for r in existing if not r.catalog_id}
    matched: set[str] = set()

    for src in demo_rows:
        name = real_reward_name(src.name)
        rid = real_reward_id(town_id, name)
        reward = by_catalog.get(src.id)
        if reward is None:
            # Rows older than ``catalog_id``: adopt by stable id, then name.
            for candidate in (by_id.get(rid), unlinked_by_name.get(name)):
                if (
                    candidate is not None
                    and candidate.catalog_id is None
                    and candidate.id not in matched
                ):
                    reward = candidate
                    break
        if reward is None:
            reward = Reward(
                id=_uuid() if rid in by_id else rid,
                town_id=town_id,
                is_fake=False,
                status=src.status if activate_new else "inactive",
                stock=src.stock,
            )
            db.add(reward)
            report.created.append(name)
        else:
            if reward.name != name:
                report.renamed.append((reward.name, name))
            for label, old, new in (
                ("points", reward.points_required, src.points_required),
                ("type", reward.type, src.type),
                ("value", reward.value, src.value),
                ("valid from", reward.valid_from, src.valid_from),
                ("valid until", reward.valid_until, src.valid_until),
            ):
                if old != new:
                    report.changed.append(f"{name}: {label} {old} -> {new}")
            report.updated.append(name)
        matched.add(reward.id)

        reward.catalog_id = src.id
        reward.name = name
        reward.description = src.description or ""
        reward.type = src.type
        reward.points_required = src.points_required
        reward.value = src.value
        reward.conditions = src.conditions
        reward.valid_from = src.valid_from
        reward.valid_until = src.valid_until
        reward.name_i18n = _strip_demo_prefix_i18n(src.name_i18n)
        reward.description_i18n = src.description_i18n
        reward.conditions_i18n = src.conditions_i18n
        reward.i18n_source_lang = src.i18n_source_lang
        await db.flush()
        await _mirror_demo_media(db, source=src, target=reward)

        # Balance vouchers redeem at the town pilot shop when unlinked.
        if shop_id and src.type == RewardType.BALANCE:
            has_link = (
                await db.execute(
                    select(RewardShop.id).where(RewardShop.reward_id == reward.id)
                )
            ).scalars().first()
            if has_link is None:
                db.add(
                    RewardShop(id=_uuid(), reward_id=reward.id, shop_id=shop_id)
                )

    for old in existing:
        if old.id in matched:
            continue
        if old.catalog_id is None:
            report.untouched.append(old.name)
            continue
        has_redemption = (
            await db.execute(
                select(Redemption.id).where(Redemption.reward_id == old.id)
            )
        ).scalars().first()
        if has_redemption is not None:
            # Keep: redemption history references it. Just stop offering it.
            old.status = "inactive"
            report.retired.append(old.name)
            continue
        report.deleted.append(old.name)
        await db.delete(old)  # cascades reward_media + reward_shops

    await db.flush()
    return report


async def seed_real_rewards(
    db: AsyncSession,
    *,
    town_id: str,
    shop_id: str | None = None,
    activate_new: bool = False,
) -> int:
    """``sync_catalog_rewards`` for callers that only want the count."""
    report = await sync_catalog_rewards(
        db, town_id=town_id, shop_id=shop_id, activate_new=activate_new
    )
    return report.synced


async def _reward_for_spec(
    db: AsyncSession,
    *,
    town_id: str,
    spec: dict[str, Any],
    is_fake: bool = True,
) -> Reward | None:
    if is_fake:
        rid = demo_reward_id(spec["name"])
        name = spec["name"]
    else:
        name = real_reward_name(spec["name"])
        rid = real_reward_id(town_id, name)
    reward = await db.get(Reward, rid)
    if reward is not None:
        return reward
    return (
        await db.execute(
            select(Reward).where(
                Reward.is_fake.is_(is_fake),
                Reward.town_id == town_id,
                Reward.name == name,
            )
        )
    ).scalars().first()


async def upsert_demo_reward_images(
    db: AsyncSession, *, town_id: str
) -> int:
    """Attach/replace catalog PNGs on the demo (is_fake) partition."""
    return await upsert_reward_images(db, town_id=town_id, is_fake=True)


async def upsert_reward_images(
    db: AsyncSession, *, town_id: str, is_fake: bool
) -> int:
    """Attach/replace catalog PNGs from scripts/seed_media/rewards.

    Does not change points, names or stock. Missing files are skipped.
    """
    updated = 0
    for spec in FAKE_DEMO_REWARDS:
        filename = spec.get("image")
        if not filename:
            continue
        path = SEED_REWARD_MEDIA_DIR / str(filename)
        if not path.is_file():
            nested = SEED_REWARD_MEDIA_DIR / "rewards" / str(filename)
            path = nested if nested.is_file() else path
        if not path.is_file():
            continue
        reward = await _reward_for_spec(
            db, town_id=town_id, spec=spec, is_fake=is_fake
        )
        if reward is None:
            continue
        data = path.read_bytes()
        existing = (
            await db.execute(
                select(RewardMedia).where(RewardMedia.reward_id == reward.id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.content_type = "image/png"
            existing.data = data
            existing.byte_size = len(data)
            existing.updated_at = datetime.utcnow()
            media_row = existing
        else:
            media_row = RewardMedia(
                id=_uuid(),
                reward_id=reward.id,
                content_type="image/png",
                data=data,
                byte_size=len(data),
            )
            db.add(media_row)
        reward.image_url = media_public_path(reward.id, media_version(media_row))
        updated += 1
    await db.flush()
    return updated
