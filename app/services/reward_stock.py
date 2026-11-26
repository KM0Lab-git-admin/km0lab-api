"""Stock of a reward in one municipality.

The catalog is shared: names, points and images are the same everywhere and
a municipality's admin only switches rewards on and off. Stock is the one
figure that belongs to each municipality (it goes down with every
redemption there), and nothing in the backoffice sets it. This does, for
``scripts/set_reward_stock.py``: it is how a pilot caps what can be
redeemed, and how units are topped up.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reward, Town


class StockRefused(RuntimeError):
    """A safety check failed; nothing was changed."""


@dataclass
class StockReport:
    municipality: str
    reward: str
    old_stock: int | None
    new_stock: int
    old_status: str
    new_status: str

    def lines(self) -> list[str]:
        was = "unlimited" if self.old_stock is None else str(self.old_stock)
        lines = [f"{self.municipality}: '{self.reward}' stock {was} -> {self.new_stock}"]
        if self.new_status != self.old_status:
            lines.append(
                f"{self.municipality}: '{self.reward}' status "
                f"{self.old_status} -> {self.new_status}"
            )
        elif self.old_status == "inactive":
            lines.append(
                f"{self.municipality}: '{self.reward}' stays inactive "
                "(its admin switches it on)"
            )
        return lines


def _names(reward: Reward) -> set[str]:
    """Every name the reward goes by: its own and its translations."""
    names = {reward.name}
    for value in (reward.name_i18n or {}).values():
        if isinstance(value, str):
            names.add(value)
    return {n.strip().casefold() for n in names if n and n.strip()}


async def set_reward_stock(
    db: AsyncSession, *, town: Town, reward: str, stock: int
) -> StockReport:
    """Set the units left of ``reward`` in ``town``. Flushes, never commits.

    ``reward`` is its id or its name in any language, as the backoffice or
    the app show it. Only the municipality's real rewards are touched: the
    catalog itself (Demo KM0) is edited from the backoffice.

    Reaching zero marks it sold out, as a redemption would; topping up a
    sold-out reward puts it back on offer. One the admin switched off stays
    off.
    """
    if stock < 0:
        raise StockRefused("stock cannot be negative")
    wanted = reward.strip()
    if not wanted:
        raise StockRefused("say which reward")

    rewards = (
        (
            await db.execute(
                select(Reward)
                .where(Reward.town_id == town.id, Reward.is_fake.is_(False))
                .order_by(Reward.name)
            )
        )
        .scalars()
        .all()
    )
    if not rewards:
        raise StockRefused(f"{town.name} has no rewards of its own")

    matches = [r for r in rewards if r.id == wanted]
    if not matches:
        matches = [r for r in rewards if wanted.casefold() in _names(r)]
    if not matches:
        available = ", ".join(f"'{r.name}'" for r in rewards)
        raise StockRefused(
            f"{town.name} has no reward called '{wanted}'. It has: {available}"
        )
    if len(matches) > 1:
        ids = ", ".join(f"{r.name} ({r.id})" for r in matches)
        raise StockRefused(
            f"'{wanted}' matches several rewards in {town.name}: {ids}. Use the id."
        )

    target = matches[0]
    report = StockReport(
        municipality=town.name,
        reward=target.name,
        old_stock=target.stock,
        new_stock=stock,
        old_status=target.status,
        new_status=target.status,
    )
    target.stock = stock
    if stock == 0 and target.status == "active":
        target.status = "sold_out"
    elif stock > 0 and target.status == "sold_out":
        target.status = "active"
    report.new_status = target.status
    await db.flush()
    return report
