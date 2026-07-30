"""Default point-action catalog per town (real and optional fake partition)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PointAction

# Shared UMS templates; each town gets its own rows to configure.
DEFAULT_POINT_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "type": "birthday",
        "name": "Perque avui és el teu aniversari!",
        "description": "Punts pel teu aniversari",
        "points": 500,
        "per_user_limit": 1,
        "active": True,
        "visible_home": True,
    },
    {
        "type": "signup",
        "name": "Primer registre a l'app",
        "description": "Punts de benvinguda",
        "points": 100,
        "per_user_limit": 1,
        "active": True,
        "visible_home": False,
    },
    {
        "type": "qr_scan",
        "name": "Primer escaneig d'un comerç",
        "description": "Visita a un comerç adherit",
        "points": 10,
        "cooldown_days": 30,
        "active": True,
        "visible_home": True,
    },
    {
        "type": "web_visit",
        "name": "Visita la web de turisme",
        "description": "Visita la web municipal de turisme",
        "points": 20,
        "active": True,
        "visible_home": True,
    },
    {
        "type": "web_signup",
        "name": "Registre al butlletí municipal",
        "description": "Subscripció al butlletí",
        "points": 50,
        "per_user_limit": 1,
        "active": True,
        "visible_home": True,
    },
    {
        "type": "event",
        "name": "Inscripció a la Festa Major",
        "description": "Inscripció a un esdeveniment municipal",
        "points": 100,
        "active": True,
        "visible_home": True,
    },
    {
        "type": "custom",
        "name": "Enquesta de satisfacció",
        "description": "Participa a l'enquesta municipal",
        "points": 30,
        "per_user_limit": 1,
        "active": True,
        "visible_home": True,
    },
)


def _uuid() -> str:
    return uuid.uuid4().hex


def _stable_action_id(town_id: str, *, is_fake: bool, type_: str) -> str:
    key = f"point-action:{town_id}:{'fake' if is_fake else 'real'}:{type_}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


async def ensure_town_point_actions(
    db: AsyncSession,
    town_id: str,
    *,
    is_fake: bool = False,
) -> int:
    """Upsert default catalog actions without wiping admin overrides.

    Existing rows keep points / visible_home / limits configured in the BO.
    Only missing catalog types are inserted with defaults.
    Custom admin-created actions (not in DEFAULT types with stable id) stay.
    """
    catalog_types = {spec["type"] for spec in DEFAULT_POINT_ACTIONS}
    existing = (
        await db.execute(
            select(PointAction).where(
                PointAction.town_id == town_id,
                PointAction.is_fake.is_(is_fake),
            )
        )
    ).scalars().all()
    by_type = {a.type: a for a in existing if a.type in catalog_types}
    # Prefer stable-id rows when duplicates exist from legacy seeds.
    by_id = {a.id: a for a in existing}

    created = 0
    for spec in DEFAULT_POINT_ACTIONS:
        rid = _stable_action_id(town_id, is_fake=is_fake, type_=spec["type"])
        row = by_id.get(rid) or by_type.get(spec["type"])
        if row is None:
            db.add(
                PointAction(
                    id=rid,
                    town_id=town_id,
                    is_fake=is_fake,
                    **spec,
                )
            )
            created += 1
            continue
        # Keep BO-tuned fields; only fill blanks / ensure type+name baseline
        # for brand-new migrations. Do not overwrite points/visible_home/active.
        if row.id != rid and rid not in by_id:
            # Leave legacy row as-is (preserves media-like config); skip insert.
            pass

    await db.flush()
    return created if created else len(DEFAULT_POINT_ACTIONS)
