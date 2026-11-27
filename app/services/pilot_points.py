"""The points of the pilot: three ways to earn, one scale for the rewards.

Decided on 27-11-2026 for every municipality (and for the demonstration):

- Signing up gives 50 points, scanning a shop's QR 100, a friend who
  completes their signup 50. Every other action is switched off.
- 100 points are worth 1 EUR: a reward whose value is an amount in euros
  costs that amount times 100. The KM0 LAB T-shirt costs 1000.

``set_pilot_points`` puts a municipality in that state and says what it
changed. It can be run again: it writes values, it never multiplies what is
there. Rewards the rule does not cover (a percentage, a product with no
price) are left alone and listed, because someone has to decide them.

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

# The only ways to earn points, and what each gives.
ACTION_POINTS: dict[str, int] = {
    "signup": 50,
    "qr_scan": SCAN_POINTS,
    "invite_person": 50,
}

# Rewards with a price of their own, by name (without the "[DEMO] " mark).
FIXED_REWARD_POINTS: dict[str, int] = {"samarreta km0 lab": 1000}

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


def reward_points_for(name: str, value: str | None) -> int | None:
    """What the rule says a reward costs, or None when it says nothing."""
    plain = re.sub(r"^\s*\[demo\]\s*", "", name, flags=re.I).strip().casefold()
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
        if action.type == "qr_scan" and action.is_fake == main_partition:
            report.scan_cooldown_days = action.cooldown_days
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
        target = reward_points_for(reward.name, reward.value)
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
        if change("reward", f"«{reward.name}»", reward.points_required, target):
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
