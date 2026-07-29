"""Default point-action catalog per town (real and optional fake partition)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete
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
    },
    {
        "type": "signup",
        "name": "Primer registre a l'app",
        "description": "Punts de benvinguda",
        "points": 100,
        "per_user_limit": 1,
        "active": True,
    },
    {
        "type": "qr_scan",
        "name": "Primer escaneig d'un comerç",
        "description": "Visita a un comerç adherit",
        "points": 10,
        "cooldown_days": 30,
        "active": True,
    },
    {
        "type": "web_visit",
        "name": "Visita la web de turisme",
        "description": "Visita la web municipal de turisme",
        "points": 20,
        "active": True,
    },
    {
        "type": "web_signup",
        "name": "Registre al butlletí municipal",
        "description": "Subscripció al butlletí",
        "points": 50,
        "per_user_limit": 1,
        "active": True,
    },
    {
        "type": "event",
        "name": "Inscripció a la Festa Major",
        "description": "Inscripció a un esdeveniment municipal",
        "points": 100,
        "active": True,
    },
    {
        "type": "custom",
        "name": "Enquesta de satisfacció",
        "description": "Participa a l'enquesta municipal",
        "points": 30,
        "per_user_limit": 1,
        "active": True,
    },
)


def _uuid() -> str:
    return uuid.uuid4().hex


async def ensure_town_point_actions(
    db: AsyncSession,
    town_id: str,
    *,
    is_fake: bool = False,
) -> int:
    """Replace one partition of town point_actions with the default inventory.

    Real admins use ``is_fake=False``; demo admin/residents use ``is_fake=True``.
    Partitions are independent so reseeding fake does not wipe real (and vice versa).
    """
    await db.execute(
        delete(PointAction).where(
            PointAction.town_id == town_id,
            PointAction.is_fake.is_(is_fake),
        )
    )
    for spec in DEFAULT_POINT_ACTIONS:
        db.add(
            PointAction(
                id=_uuid(),
                town_id=town_id,
                is_fake=is_fake,
                **spec,
            )
        )
    await db.flush()
    return len(DEFAULT_POINT_ACTIONS)
