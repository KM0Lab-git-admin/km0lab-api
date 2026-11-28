"""The points of the pilot: three ways to earn, one scale for the rewards.

Decided on 27-11-2026 for every municipality (and for the demonstration):

- Signing up gives 50 points, scanning a shop's QR 100, a friend who
  completes their signup 50. Every other action is switched off.
- A real municipality admits 200 accounts (``towns.max_residents``); the
  demonstration, any number.
- A person who joined alone is rewarded for three friends at most. Someone
  they invited is rewarded for one, and anyone further along the chain for
  none. The backoffice edits the first number; the other two are these
  constants.
- Each shop gives its points once per resident: the wait before the same
  shop pays again goes from 30 days to a year, longer than the pilot. (The
  app says "once" instead of showing a date that far away.)
- 100 points are worth 1 EUR: a reward whose value is an amount in euros
  costs that amount times 100. The rewards without an amount have their
  price written here (``FIXED_REWARD_POINTS``): the T-shirt 1000, the rest
  ten times what they cost on the old scale.
- Discounts in percent are switched off: the pilot's rewards are KM0 LAB's,
  and a percentage has no fair price in points.

``set_pilot_points`` puts a municipality in that state and says what it
changed. It can be run again: it writes values, it never multiplies what is
there. A reward none of this covers is left alone and listed, because
someone has to decide it.

The QA territory is not touched: its numbers belong to the tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.point_actions import DEFAULT_POINT_ACTIONS, _stable_action_id
from app.demo import DEMO_TOWN_SLUG
from app.models import PointAction, Reward, Shop, Town, TownPostalCode, User
from app.qa import QA_EMAIL_DOMAIN, QA_SLUG_PREFIX

SCAN_POINTS = 100
POINTS_PER_EURO = 100
# Days before the same shop pays the same resident again: "once" in a pilot
# of two months, and still once if it runs long.
SCAN_COOLDOWN_DAYS = 365
# Friends a person can be rewarded for inviting, by how they joined:
# alone (ring 0), invited by someone who joined alone (ring 1), or further.
INVITE_FRIENDS_LIMIT = 3
INVITE_FRIENDS_LIMIT_RING1 = 1
INVITE_FRIENDS_LIMIT_RING2 = 0
# Accounts a real municipality admits during the pilot.
PILOT_MAX_RESIDENTS = 200

# The only ways to earn points, and what each gives.
ACTION_POINTS: dict[str, int] = {
    "signup": 50,
    "qr_scan": SCAN_POINTS,
    "invite_person": 50,
}

# Rewards with a price of their own, by name (without the "[DEMO] " mark).
FIXED_REWARD_POINTS: dict[str, int] = {
    "samarreta km0 lab": 1000,
    "bossa km0 lab": 1200,
    "bossa tote km0": 1200,
    "ampolla d'oli local": 1800,
    "gorra km0 lab": 1800,
    "entrada de cinema": 2000,
}

# A reward that reached the catalog with a test name, and its real one.
RENAMED_REWARDS: dict[str, dict[str, str]] = {
    "bossa de regal de kmlab super chula de la muerte": {
        "ca": "Bossa KM0 LAB",
        "es": "Bolsa KM0 LAB",
        "en": "KM0 LAB bag",
    },
}

_DEMO_MARK = re.compile(r"^\s*(\[demo\]\s*)", re.I)
_PERCENT = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*%\s*$")

_EUROS = re.compile(r"^\s*(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur|euros?)\s*$", re.I)


@dataclass(frozen=True)
class Change:
    kind: str  # "municipality" | "action" | "shops" | "reward"
    what: str
    before: str
    after: str


@dataclass(frozen=True)
class Undecided:
    """A reward the rule says nothing about: left as it is."""

    name: str
    type: str
    value: str | None
    points: int
    status: str
    own: bool  # not a copy of the shared catalog


@dataclass
class TownReport:
    name: str
    slug: str
    changes: list[Change] = field(default_factory=list)
    unchanged: int = 0
    undecided: list[Undecided] = field(default_factory=list)
    scan_cooldown_days: int | None = None
    # Accounts holding points earned on the old scale.
    balances_test: tuple[int, int] = (0, 0)  # (accounts, points)
    balances_other: tuple[int, int] = (0, 0)


def euros_of(value: str | None) -> float | None:
    """``"5€"`` / ``"12,50 €"`` -> the amount; anything else -> None."""
    match = _EUROS.match(value or "")
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def plain_reward_name(name: str) -> str:
    """The name as the table above writes it: no "[DEMO] " mark, any case."""
    return _DEMO_MARK.sub("", name).strip().casefold()


def is_percent_discount(type_: str, value: str | None) -> bool:
    return type_ == "discount" and bool(_PERCENT.match(value or ""))


def reward_points_for(name: str, value: str | None) -> int | None:
    """What the rule says a reward costs, or None when it says nothing."""
    plain = plain_reward_name(name)
    if plain in FIXED_REWARD_POINTS:
        return FIXED_REWARD_POINTS[plain]
    euros = euros_of(value)
    if euros is None:
        return None
    return round(euros * POINTS_PER_EURO)


def is_pilot_town(town: Town) -> bool:
    return not town.slug.startswith(QA_SLUG_PREFIX)


def _on_off(active: bool) -> str:
    return "on" if active else "off"


async def set_pilot_points(
    db: AsyncSession, town: Town, *, apply: bool
) -> TownReport:
    """Put ``town`` on the pilot's points. Without ``apply`` nothing is
    touched, not even in the session: the report says what would change."""
    report = TownReport(name=town.name, slug=town.slug)

    def change(kind: str, what: str, before: object, after: object) -> bool:
        if before == after:
            report.unchanged += 1
            return False
        report.changes.append(Change(kind, what, str(before), str(after)))
        return True

    # ── The municipality's own numbers ────────────────────────────────
    if change("municipality", "points per scan", town.default_visit_points, SCAN_POINTS):
        if apply:
            town.default_visit_points = SCAN_POINTS
    if change("municipality", "points per 1 EUR", town.points_per_euro, POINTS_PER_EURO):
        if apply:
            town.points_per_euro = POINTS_PER_EURO

    # The pilot is for a limited group; the demonstration has no limit.
    if town.slug != DEMO_TOWN_SLUG:
        if change(
            "municipality",
            "accounts admitted",
            town.max_residents if town.max_residents is not None else "no limit",
            PILOT_MAX_RESIDENTS,
        ):
            if apply:
                town.max_residents = PILOT_MAX_RESIDENTS

    # What each shop's card shows ("+N pts") is its own copy of the number.
    shops = (
        await db.execute(select(Shop).where(Shop.town_id == town.id))
    ).scalars().all()
    stale = [s for s in shops if s.visit_points != SCAN_POINTS]
    if shops and not stale:
        report.unchanged += 1
    if stale:
        seen = sorted({s.visit_points for s in stale})
        report.changes.append(
            Change(
                "shops",
                f"points shown on the card of {len(stale)} of {len(shops)} shops",
                "/".join(str(v) for v in seen),
                str(SCAN_POINTS),
            )
        )
        if apply:
            for shop in stale:
                shop.visit_points = SCAN_POINTS

    # ── Actions: three on, with their points; the rest off ────────────
    actions = (
        await db.execute(
            select(PointAction)
            .where(PointAction.town_id == town.id)
            .order_by(PointAction.is_fake, PointAction.type, PointAction.created_at)
        )
    ).scalars().all()
    main_partition = town.slug == DEMO_TOWN_SLUG
    for action in actions:
        label = f"{action.type} «{action.name}»"
        if action.is_fake != main_partition:
            label += " (demo partition)" if action.is_fake else " (real partition)"
        if action.type == "qr_scan":
            if change(
                "action",
                f"{label}: days before the same shop pays again",
                action.cooldown_days,
                SCAN_COOLDOWN_DAYS,
            ):
                if apply:
                    action.cooldown_days = SCAN_COOLDOWN_DAYS
            if action.is_fake == main_partition:
                report.scan_cooldown_days = SCAN_COOLDOWN_DAYS
        if action.type == "invite_person":
            rings = (
                (
                    "friends rewarded for someone who joined alone",
                    action.per_user_limit,
                    INVITE_FRIENDS_LIMIT,
                    "per_user_limit",
                ),
                (
                    "friends rewarded for someone who was invited",
                    action.per_user_limit_ring1,
                    INVITE_FRIENDS_LIMIT_RING1,
                    "per_user_limit_ring1",
                ),
                (
                    "friends rewarded further along the chain",
                    action.per_user_limit_ring2,
                    INVITE_FRIENDS_LIMIT_RING2,
                    "per_user_limit_ring2",
                ),
            )
            for what, before, after, field_name in rings:
                shown = before if before is not None else "no limit"
                if change("action", f"{label}: {what}", shown, after) and apply:
                    setattr(action, field_name, after)
        if action.type in ACTION_POINTS:
            points = ACTION_POINTS[action.type]
            if change("action", f"{label}: points", action.points, points) and apply:
                action.points = points
            if change("action", f"{label}: state", _on_off(action.active), "on"):
                if apply:
                    action.active = True
        elif change("action", f"{label}: state", _on_off(action.active), "off"):
            if apply:
                action.active = False

    # A municipality that never had one of the three would fall back to the
    # defaults in settings (100 for an invitation): give it the row.
    present = {a.type for a in actions if a.is_fake == main_partition}
    for spec in DEFAULT_POINT_ACTIONS:
        if spec["type"] not in ACTION_POINTS or spec["type"] in present:
            continue
        points = ACTION_POINTS[spec["type"]]
        report.changes.append(
            Change("action", f"{spec['type']} «{spec['name']}»", "missing", f"{points}, on")
        )
        if apply:
            db.add(
                PointAction(
                    **{
                        **spec,
                        "id": _stable_action_id(
                            town.id, is_fake=main_partition, type_=spec["type"]
                        ),
                        "town_id": town.id,
                        "is_fake": main_partition,
                        "points": points,
                        "active": True,
                        **(
                            {"cooldown_days": SCAN_COOLDOWN_DAYS}
                            if spec["type"] == "qr_scan"
                            else {}
                        ),
                        **(
                            {
                                "per_user_limit": INVITE_FRIENDS_LIMIT,
                                "per_user_limit_ring1": INVITE_FRIENDS_LIMIT_RING1,
                                "per_user_limit_ring2": INVITE_FRIENDS_LIMIT_RING2,
                            }
                            if spec["type"] == "invite_person"
                            else {}
                        ),
                    }
                )
            )

    # ── Rewards: 100 points per euro ──────────────────────────────────
    rewards = (
        await db.execute(
            select(Reward)
            .where(Reward.town_id == town.id)
            .order_by(Reward.is_fake, Reward.points_required, Reward.name)
        )
    ).scalars().all()
    for reward in rewards:
        new_name = RENAMED_REWARDS.get(plain_reward_name(reward.name))
        if new_name is not None:
            mark = _DEMO_MARK.match(reward.name)
            prefix = mark.group(1) if mark else ""
            report.changes.append(
                Change("reward", "name", f"«{reward.name}»", f"«{prefix}{new_name['ca']}»")
            )
            if apply:
                reward.name = f"{prefix}{new_name['ca']}"
                reward.name_i18n = {
                    lang: f"{prefix}{text}" for lang, text in new_name.items()
                }
                reward.i18n_source_lang = "ca"
            name_now = new_name["ca"]
        else:
            name_now = reward.name

        if is_percent_discount(reward.type, reward.value):
            # Switched off; a sold-out or already inactive one stays as it is.
            if reward.status == "active":
                change("reward", f"«{name_now}»: state", "on", "off")
                if apply:
                    reward.status = "inactive"
            else:
                report.unchanged += 1
            continue

        target = reward_points_for(name_now, reward.value)
        if target is None:
            report.undecided.append(
                Undecided(
                    name=reward.name,
                    type=reward.type,
                    value=reward.value,
                    points=reward.points_required,
                    status=reward.status,
                    own=reward.catalog_id is None and town.slug != DEMO_TOWN_SLUG,
                )
            )
            continue
        if change("reward", f"«{name_now}»", reward.points_required, target):
            if apply:
                reward.points_required = target

    # ── Points already earned on the old scale ────────────────────────
    # A user belongs to a municipality through their postal code.
    codes = select(TownPostalCode.postal_code).where(
        TownPostalCode.town_id == town.id
    )
    is_test = User.is_fake.is_(True) | User.email.like(f"%@{QA_EMAIL_DOMAIN}")
    for attr, condition in (
        ("balances_test", is_test),
        ("balances_other", ~is_test),
    ):
        row = (
            await db.execute(
                select(func.count(), func.coalesce(func.sum(User.points), 0)).where(
                    User.postal_code.in_(codes), User.points > 0, condition
                )
            )
        ).one()
        setattr(report, attr, (int(row[0]), int(row[1])))

    if apply:
        await db.flush()
    return report


async def pilot_towns(db: AsyncSession) -> list[Town]:
    """Every municipality the pilot's points apply to, the demo included."""
    towns = (await db.execute(select(Town).order_by(Town.name))).scalars().all()
    return [town for town in towns if is_pilot_town(town)]
