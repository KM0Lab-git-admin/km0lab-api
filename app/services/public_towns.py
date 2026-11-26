"""What the residents app reads about towns without a session.

Two reads, both on every resident's path: the list of towns
(``GET /towns``) and the card of one postal code
(``GET /towns/public?postal_code=``, the postal-code screen and the home).

They used to ask the database municipality by municipality: 24 queries for
the list and 13 for one card with four municipalities, and each query is a
round trip. Here everything is read once, in five queries however many
municipalities there are, and kept in memory for a few minutes: this data
changes when a town is added or its administrator edits the settings, not
between two residents opening the app.

Staleness: a change made from the backoffice clears the cache at once
(``invalidate``); one made by a script, in another process, shows up within
``TTL_SECONDS``. A postal code the cache does not know is looked up before
answering "unknown", so a town added by a script works straight away.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, lazyload

from app.demo import DEMO_TOWN_SLUG
from app.models import Locality, LocalityMedia, Town, TownMedia, TownPostalCode
from app.qa import QA_SLUG_PREFIX
from app.schemas.towns import LocalityOut, TownPublicOut
from app.services.localities import ART_KIND, locality_art_path
from app.services.town_media import media_public_path, media_version

# How long a snapshot is served before reading the database again.
TTL_SECONDS = 180.0


@dataclass(frozen=True)
class PublicTowns:
    """Every public card, ready to serve."""

    # What ``GET /towns`` answers: one entry per town a resident can pick.
    listing: list[TownPublicOut] = field(default_factory=list)
    # The card as seen from each postal code (every municipality, also the
    # demo and the test territory).
    by_postal_code: dict[str, TownPublicOut] = field(default_factory=dict)


_cached: PublicTowns | None = None
_cached_at = 0.0


def invalidate() -> None:
    """Forget the snapshot: the next read goes to the database."""
    global _cached, _cached_at
    _cached = None
    _cached_at = 0.0


def _card(
    town: Town, media: list[TownMedia], codes: list[TownPostalCode]
) -> TownPublicOut:
    """The municipality's own card (rules, logo, illustration, all its codes)."""
    has_logo = any(m.kind == "logo" for m in media)
    art = next((m for m in media if m.kind == ART_KIND), None)
    ordered = sorted(codes, key=lambda c: (not c.is_primary, c.postal_code))
    return TownPublicOut(
        id=town.id,
        name=town.name,
        slug=town.slug,
        postal_codes=[c.postal_code for c in ordered],
        logo_url=media_public_path(town.id, "logo") if has_logo else town.logo_url,
        has_logo=has_logo,
        art_url=(
            media_public_path(town.id, ART_KIND, media_version(art)) if art else None
        ),
        points_per_euro=town.points_per_euro,
        default_visit_points=town.default_visit_points,
        default_lang=town.default_lang,
        expiry_months=town.expiry_months,
    )


def _seen_from(
    card: TownPublicOut,
    town: Town,
    home: LocalityOut | None,
    localities: list[LocalityOut],
) -> TownPublicOut:
    """The card as one town of the municipality sees it."""
    update: dict = {
        "municipality_id": town.id,
        "municipality_name": town.name,
        "localities": localities,
    }
    if home is not None:
        update.update(
            name=home.name,
            slug=home.slug,
            postal_codes=home.postal_codes,
            art_url=home.art_url,
            locality_id=home.id,
        )
    return card.model_copy(update=update)


def _listed(town: Town) -> bool:
    """The demo and the test territory are modes of the product, not places."""
    return town.slug != DEMO_TOWN_SLUG and not town.slug.startswith(QA_SLUG_PREFIX)


async def _build(db: AsyncSession) -> PublicTowns:
    """Five queries, whatever the number of municipalities.

    Relationships are switched off on purpose: several of them load
    themselves (``lazy="selectin"``) and would bring a query each, and the
    images' bytes are left in the database (only their versions are needed).
    """
    towns = (
        (
            await db.execute(
                select(Town)
                .options(lazyload(Town.media), lazyload(Town.postal_codes))
                .order_by(Town.name)
            )
        )
        .scalars()
        .all()
    )
    codes = (
        (
            await db.execute(
                select(TownPostalCode)
                .options(lazyload(TownPostalCode.locality))
                .order_by(TownPostalCode.postal_code)
            )
        )
        .scalars()
        .all()
    )
    localities = (
        (await db.execute(select(Locality).order_by(Locality.name))).scalars().all()
    )
    town_media = (
        (await db.execute(select(TownMedia).options(defer(TownMedia.data))))
        .scalars()
        .all()
    )
    locality_art = (
        (
            await db.execute(
                select(LocalityMedia)
                .options(defer(LocalityMedia.data))
                .where(LocalityMedia.kind == ART_KIND)
            )
        )
        .scalars()
        .all()
    )

    codes_by_town: dict[str, list[TownPostalCode]] = {}
    for code in codes:
        codes_by_town.setdefault(code.town_id, []).append(code)
    localities_by_town: dict[str, list[Locality]] = {}
    for loc in localities:
        localities_by_town.setdefault(loc.town_id, []).append(loc)
    media_by_town: dict[str, list[TownMedia]] = {}
    for row in town_media:
        media_by_town.setdefault(row.town_id, []).append(row)
    art_by_locality = {
        row.locality_id: locality_art_path(row.locality_id, media_version(row))
        for row in locality_art
    }

    listing: list[TownPublicOut] = []
    by_postal_code: dict[str, TownPublicOut] = {}
    for town in towns:
        town_codes = codes_by_town.get(town.id, [])
        card = _card(town, media_by_town.get(town.id, []), town_codes)
        # A town without its own illustration uses the municipality's.
        cards = [
            LocalityOut(
                id=loc.id,
                name=loc.name,
                slug=loc.slug,
                postal_codes=[
                    c.postal_code for c in town_codes if c.locality_id == loc.id
                ],
                art_url=art_by_locality.get(loc.id) or card.art_url,
            )
            for loc in localities_by_town.get(town.id, [])
        ]
        by_id = {loc.id: loc for loc in cards}
        for code in town_codes:
            by_postal_code[code.postal_code] = _seen_from(
                card, town, by_id.get(code.locality_id or ""), cards
            )
        if not _listed(town):
            continue
        if cards:
            listing.extend(_seen_from(card, town, loc, cards) for loc in cards)
        else:
            listing.append(_seen_from(card, town, None, []))

    listing.sort(key=lambda c: c.name.casefold())
    return PublicTowns(listing=listing, by_postal_code=by_postal_code)


async def public_towns(db: AsyncSession, *, fresh: bool = False) -> PublicTowns:
    """The snapshot, from memory while it is recent enough."""
    global _cached, _cached_at
    now = time.monotonic()
    if not fresh and _cached is not None and now - _cached_at < TTL_SECONDS:
        return _cached
    built = await _build(db)
    _cached, _cached_at = built, now
    return built


async def public_town_list(db: AsyncSession) -> list[TownPublicOut]:
    return (await public_towns(db)).listing


async def public_town_card(
    db: AsyncSession, postal_code: str
) -> TownPublicOut | None:
    """The card of a postal code, or None when no town has it."""
    snapshot = await public_towns(db)
    card = snapshot.by_postal_code.get(postal_code)
    if card is not None:
        return card
    # Not in memory: either nobody has that code (the usual case: a typo), or
    # a town was added from outside this process. One cheap query tells.
    known = await db.scalar(
        select(TownPostalCode.postal_code).where(
            TownPostalCode.postal_code == postal_code
        )
    )
    if known is None:
        return None
    return (await public_towns(db, fresh=True)).by_postal_code.get(postal_code)
