"""Helpers for shop payments — voucher amount parsing."""

import re
from decimal import Decimal, InvalidOperation

from app.models import Redemption, Reward

_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def parse_amount(*candidates: str | None) -> Decimal:
    """First parseable numeric value among candidates ("5€" -> 5.00)."""
    for raw in candidates:
        if not raw:
            continue
        match = _NUM_RE.search(raw)
        if not match:
            continue
        try:
            return Decimal(match.group(1).replace(",", "."))
        except InvalidOperation:  # pragma: no cover - regex guarantees format
            continue
    return Decimal("0")


def voucher_amount(redemption: Redemption, reward: Reward | None) -> Decimal:
    """Amount owed to the shop for a used voucher.

    Prefer the amount the merchant registered when using the voucher
    (discount case), else the nominal voucher amount/value.
    """
    return parse_amount(
        redemption.amount_applied,
        redemption.amount,
        reward.value if reward else None,
    )
