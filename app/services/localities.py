"""Localities: the towns (poblaciones) inside a municipality.

See ``app.models.Locality``. Three jobs live here:

- Reading: which locality a postal code belongs to, and its illustration.
- Keeping old data usable: a municipality created without localities gets
  one with its own name (``ensure_default_locality``).
- Grouping: moving several single-town municipalities under one
  (``group_towns``), used by ``scripts/group_towns.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.catalog.point_actions import ensure_town_point_actions
from app.models import (
    InvitationLink,
    Locality,
    LocalityMedia,
    PointAction,
    PointsTransaction,
    Redemption,
    Reward,
    Shop,
    Town,
    TownMedia,
    TownPostalCode,
    User,
)
from app.services.town_media import media_public_path, media_version
from app.utils.slug import slugify

ART_KIND = "art"


def locality_art_path(locality_id: str, version: str | None = None) -> str:
    path = f"/api/v1/towns/localities/{locality_id}/art"
    return f"{path}?v={version}" if version else path


async def get_locality_art(
    db: AsyncSession, locality_id: str
) -> LocalityMedia | None:
    return (
        await db.execute(
            select(LocalityMedia).where(
                LocalityMedia.locality_id == locality_id,
                LocalityMedia.kind == ART_KIND,
            )
        )
    ).scalars().first()


async def art_urls(
    db: AsyncSession, town_id: str, locality_ids: list[str]
) -> tuple[dict[str, str], str | None]:
    """Illustration URL per locality, plus the municipality's own (fallback).

    A locality without its own illustration uses the municipality's: that
    is where single-town municipalities have always kept theirs.
    """
    by_locality: dict[str, str] = {}
    if locality_ids:
        rows = (
            await db.execute(
                select(LocalityMedia)
                .options(defer(LocalityMedia.data))
                .where(
                    LocalityMedia.locality_id.in_(locality_ids),
                    LocalityMedia.kind == ART_KIND,
                )
            )
        ).scalars().all()
        for row in rows:
            by_locality[row.locality_id] = locality_art_path(
                row.locality_id, media_version(row)  # type: ignore[arg-type]
            )
    town_row = (
        await db.execute(
            select(TownMedia)
            .options(defer(TownMedia.data))
            .where(TownMedia.town_id == town_id, TownMedia.kind == ART_KIND)
        )
    ).scalars().first()
    town_art = (
        media_public_path(town_id, ART_KIND, media_version(town_row))
        if town_row
        else None
    )
    return by_locality, town_art


async def list_localities(db: AsyncSession, town_id: str) -> list[Locality]:
    return list(
        (
            await db.execute(
                select(Locality)
                .where(Locality.town_id == town_id)
                .order_by(Locality.name)
            )
        )
        .scalars()
        .all()
    )


async def _free_slug(db: AsyncSession, wanted: str) -> str:
    base = slugify(wanted) or "poblacio"
    slug = base
    n = 2
    while await db.scalar(select(Locality.id).where(Locality.slug == slug)):
        slug = f"{base}-{n}"
        n += 1
    return slug


async def ensure_default_locality(db: AsyncSession, town: Town) -> Locality:
    """Idempotent: a municipality always has at least one locality.

    Creates one named like the municipality if it has none, and attaches to
    the first locality every postal code and shop still without one.
    """
    localities = await list_localities(db, town.id)
    if localities:
        locality = localities[0]
    else:
        locality = Locality(
            town_id=town.id,
            name=town.name,
            slug=await _free_slug(db, town.slug or town.name),
        )
        db.add(locality)
        await db.flush()
    if len(localities) <= 1:
        await db.execute(
            update(TownPostalCode)
            .where(
                TownPostalCode.town_id == town.id,
                TownPostalCode.locality_id.is_(None),
            )
            .values(locality_id=locality.id)
        )
        await db.execute(
            update(Shop)
            .where(Shop.town_id == town.id, Shop.locality_id.is_(None))
            .values(locality_id=locality.id)
        )
        await db.flush()
    return locality


async def locality_for_postal_code(
    db: AsyncSession, town_id: str, postal_code: str | None
) -> Locality | None:
    """The town a shop or resident at this postal code belongs to."""
    if not postal_code:
        return None
    row = (
        await db.execute(
            select(TownPostalCode).where(
                TownPostalCode.postal_code == postal_code.strip(),
                TownPostalCode.town_id == town_id,
            )
        )
    ).scalars().first()
    return row.locality if row else None


class LocalityRefused(ValueError):
    """The shop's town cannot be decided. ``code`` goes to the client."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


LOCALITY_REQUIRED = "locality_required"
LOCALITY_NOT_IN_TOWN = "locality_not_in_town"


async def resolve_shop_locality(
    db: AsyncSession,
    *,
    town_id: str,
    locality_id: str | None = None,
    postal_code: str | None = None,
) -> Locality | None:
    """The town of the municipality a shop belongs to.

    In order: the one the caller names (it must be of this municipality),
    the one its postal code belongs to, the only one there is. With several
    towns and neither hint it is not guessed: ``LocalityRefused``.

    A municipality without localities (rows older than them) gives None.
    """
    if locality_id:
        locality = await db.get(Locality, locality_id)
        if locality is None or locality.town_id != town_id:
            raise LocalityRefused(LOCALITY_NOT_IN_TOWN)
        return locality
    by_code = await locality_for_postal_code(db, town_id, postal_code)
    if by_code is not None:
        return by_code
    localities = await list_localities(db, town_id)
    if len(localities) > 1:
        raise LocalityRefused(LOCALITY_REQUIRED)
    return localities[0] if localities else None


# ── Grouping ──────────────────────────────────────────────────────────


class GroupRefused(RuntimeError):
    """A safety check failed; nothing was changed."""


@dataclass
class GroupReport:
    municipality: str
    dry_run: bool
    localities: list[str] = field(default_factory=list)
    postal_codes: list[str] = field(default_factory=list)
    removed_towns: list[str] = field(default_factory=list)
    moved_art: int = 0
    moved_shops: int = 0
    created_municipality: bool = False

    def lines(self) -> list[str]:
        verb = "Se crearía" if self.dry_run else "Creado"
        kept = "ya existía"
        return [
            f"Municipio «{self.municipality}»: "
            f"{verb if self.created_municipality else kept}",
            f"Poblaciones: {', '.join(self.localities)}",
            f"Códigos postales: {', '.join(self.postal_codes)}",
            f"Ilustraciones que pasan a su población: {self.moved_art}",
            f"Comercios que pasan al municipio: {self.moved_shops}",
            "Municipios sueltos que desaparecen: "
            + (", ".join(self.removed_towns) or "ninguno"),
        ]


async def _count(db: AsyncSession, model, *clauses) -> int:
    stmt = select(func.count()).select_from(model).where(*clauses)
    return int(await db.scalar(stmt) or 0)


async def group_towns(
    db: AsyncSession,
    *,
    name: str,
    postal_codes: list[str],
    dry_run: bool = True,
) -> GroupReport:
    """Put the towns of these postal codes under one municipality.

    Each postal code must today belong to a municipality that is a single
    town (one locality). Those towns become localities of ``name`` (created
    if missing, with the default point actions); their illustration and
    shops move with them and the emptied municipalities are removed.

    Refuses if a town to move has anything that belongs to a municipality
    and cannot be moved safely: rewards, redemptions, point movements,
    invitation links, its own admin, or point actions other than untouched
    defaults in use. Caller commits (unless ``dry_run``).
    """
    codes = sorted({c.strip() for c in postal_codes if c.strip()})
    if len(codes) < 1:
        raise GroupRefused("Hace falta al menos un código postal.")
    report = GroupReport(municipality=name, dry_run=dry_run, postal_codes=codes)

    rows = (
        await db.execute(
            select(TownPostalCode).where(TownPostalCode.postal_code.in_(codes))
        )
    ).scalars().all()
    missing = sorted(set(codes) - {r.postal_code for r in rows})
    if missing:
        raise GroupRefused(
            f"Códigos postales que no existen: {', '.join(missing)}. "
            "Da de alta antes el pueblo (scripts/add_town.py)."
        )

    slug = slugify(name)
    target = (
        await db.execute(select(Town).where(Town.slug == slug))
    ).scalars().first()
    report.created_municipality = target is None

    source_ids = sorted({r.town_id for r in rows} - ({target.id} if target else set()))
    sources = (
        (await db.execute(select(Town).where(Town.id.in_(source_ids))))
        .scalars()
        .all()
        if source_ids
        else []
    )

    moves: list[tuple[Town, Locality]] = []
    for town in sources:
        locality = await ensure_default_locality(db, town)
        if len(await list_localities(db, town.id)) != 1:
            raise GroupRefused(
                f"«{town.name}» ya agrupa varias poblaciones; no se mueve entera."
            )
        outside = await _count(
            db,
            TownPostalCode,
            TownPostalCode.town_id == town.id,
            TownPostalCode.postal_code.notin_(codes),
        )
        if outside:
            raise GroupRefused(
                f"«{town.name}» tiene códigos postales que no están en la "
                "lista; indícalos todos."
            )
        blockers = {
            "premios": await _count(db, Reward, Reward.town_id == town.id),
            "canjes": await _count(db, Redemption, Redemption.town_id == town.id),
            "movimientos de puntos": await _count(
                db, PointsTransaction, PointsTransaction.town_id == town.id
            ),
            "enlaces de invitación": await _count(
                db, InvitationLink, InvitationLink.town_id == town.id
            ),
            "administradores": await _count(
                db,
                User,
                User.is_admin.is_(True),
                User.postal_code.in_(
                    select(TownPostalCode.postal_code).where(
                        TownPostalCode.town_id == town.id
                    )
                ),
            ),
        }
        found = {k: v for k, v in blockers.items() if v}
        if found:
            raise GroupRefused(
                f"«{town.name}» ya tiene actividad propia ({found}). "
                "Agruparlo exige decidir a mano qué se hace con ella."
            )
        moves.append((town, locality))
        report.localities.append(locality.name)
        report.removed_towns.append(town.name)
        report.moved_shops += await _count(db, Shop, Shop.town_id == town.id)
        if await db.scalar(
            select(TownMedia.id).where(
                TownMedia.town_id == town.id, TownMedia.kind == ART_KIND
            )
        ):
            report.moved_art += 1

    if target is not None:
        for locality in await list_localities(db, target.id):
            if locality.name not in report.localities:
                report.localities.append(locality.name)
    report.localities.sort()

    if dry_run:
        return report

    if target is None:
        target = Town(
            name=name,
            slug=slug,
            entity_name=name,
            entity_type="city_council",
        )
        db.add(target)
        await db.flush()
        await ensure_town_point_actions(db, target.id)

    has_primary = await _count(
        db,
        TownPostalCode,
        TownPostalCode.town_id == target.id,
        TownPostalCode.is_primary.is_(True),
    )
    for town, locality in moves:
        # The illustration belonged to the municipality; now to its town.
        art = (
            await db.execute(
                select(TownMedia).where(
                    TownMedia.town_id == town.id, TownMedia.kind == ART_KIND
                )
            )
        ).scalars().first()
        if art is not None and await get_locality_art(db, locality.id) is None:
            db.add(
                LocalityMedia(
                    locality_id=locality.id,
                    kind=ART_KIND,
                    content_type=art.content_type,
                    data=art.data,
                    byte_size=art.byte_size,
                )
            )
        locality.town_id = target.id
        await db.execute(
            update(TownPostalCode)
            .where(TownPostalCode.town_id == town.id)
            .values(
                town_id=target.id,
                locality_id=locality.id,
                # One primary postal code per municipality.
                is_primary=False,
            )
        )
        await db.execute(
            update(Shop)
            .where(Shop.town_id == town.id)
            .values(town_id=target.id, locality_id=locality.id)
        )
        await db.flush()
        # Default actions of the emptied municipality: nothing references
        # them (checked above), the target has its own.
        await db.execute(delete(PointAction).where(PointAction.town_id == town.id))
        await db.execute(delete(TownMedia).where(TownMedia.town_id == town.id))
        await db.execute(delete(Town).where(Town.id == town.id))
        await db.flush()

    if not has_primary:
        first = (
            await db.execute(
                select(TownPostalCode)
                .where(TownPostalCode.town_id == target.id)
                .order_by(TownPostalCode.postal_code)
            )
        ).scalars().first()
        if first is not None:
            first.is_primary = True
    await db.flush()
    # The towns just changed municipality: what the app reads about them
    # in memory is no longer true. (Run from a script, in another process,
    # this does nothing there: the API catches up within its TTL.)
    from app.services import public_towns

    public_towns.invalidate()
    return report
