"""Grant points from catalogued point_actions (signup, birthday, …)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import PointAction, PointsTransaction, User
from app.services.points import apply_points

ACTION_TYPE_SIGNUP = "signup"
ACTION_TYPE_BIRTHDAY = "birthday"
ACTION_TYPE_QR_SCAN = "qr_scan"

# Ledger type for signup (keeps existing welcome semantics / tests).
TX_TYPE_WELCOME = "welcome"
TX_TYPE_BIRTHDAY = "birthday"


@dataclass(frozen=True)
class ActionGrantResult:
    points: int
    action: PointAction | None
    message: str | None


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _is_in_window(action: PointAction, now: datetime) -> bool:
    if action.valid_from is not None and _aware(action.valid_from) > now:
        return False
    if action.valid_until is not None and _aware(action.valid_until) < now:
        return False
    return True


async def find_active_action(
    db: AsyncSession,
    *,
    action_type: str,
    user: User,
    town_id: str | None = None,
) -> PointAction | None:
    """Prefer town-scoped action; if no town, newest matching action."""
    scope_town_id = town_id if town_id is not None else user.town_id
    q = (
        select(PointAction)
        .where(
            PointAction.type == action_type,
            PointAction.active.is_(True),
            PointAction.is_fake.is_(user.is_fake),
        )
        .order_by(PointAction.created_at.desc())
    )
    if scope_town_id:
        q = q.where(PointAction.town_id == scope_town_id)

    rows = (await db.execute(q)).scalars().all()
    now = datetime.now(timezone.utc)
    for action in rows:
        if action.points <= 0:
            continue
        if _is_in_window(action, now):
            return action
    return None


async def _count_grants(
    db: AsyncSession,
    *,
    action_id: str,
    user_id: str | None = None,
    tx_type: str | None = None,
    year: int | None = None,
) -> int:
    q = select(func.count()).select_from(PointsTransaction).where(
        PointsTransaction.ref_id == action_id
    )
    if user_id is not None:
        q = q.where(PointsTransaction.user_id == user_id)
    if tx_type is not None:
        q = q.where(PointsTransaction.type == tx_type)
    if year is not None:
        q = q.where(extract("year", PointsTransaction.created_at) == year)
    return int((await db.execute(q)).scalar_one())


async def grant_signup_points(
    db: AsyncSession,
    *,
    user: User,
) -> ActionGrantResult:
    """Award signup points from active `signup` action, or settings fallback."""
    action = await find_active_action(
        db, action_type=ACTION_TYPE_SIGNUP, user=user
    )
    if action is not None:
        # One-time signup: treat as per_user_limit=1 if unset.
        limit = action.per_user_limit if action.per_user_limit is not None else 1
        used = await _count_grants(
            db,
            action_id=action.id,
            user_id=user.id,
            tx_type=TX_TYPE_WELCOME,
        )
        if used >= limit:
            return ActionGrantResult(0, action, None)
        if action.total_limit is not None:
            if (
                await _count_grants(
                    db, action_id=action.id, tx_type=TX_TYPE_WELCOME
                )
                >= action.total_limit
            ):
                return ActionGrantResult(0, action, None)

        await apply_points(
            db,
            user=user,
            points=action.points,
            type=TX_TYPE_WELCOME,
            town_id=action.town_id,
            ref_id=action.id,
            description=action.name or "Welcome bonus",
        )
        return ActionGrantResult(
            action.points,
            action,
            action.name or action.description or None,
        )

    settings = get_settings()
    if settings.welcome_points <= 0:
        return ActionGrantResult(0, None, None)

    await apply_points(
        db,
        user=user,
        points=settings.welcome_points,
        type=TX_TYPE_WELCOME,
        description="Welcome bonus",
    )
    return ActionGrantResult(settings.welcome_points, None, "Welcome bonus")


def is_birthday_today(birth: date, today: date | None = None) -> bool:
    today = today or date.today()
    if birth.month == 2 and birth.day == 29:
        # Non-leap years: celebrate on Feb 28.
        if today.month == 2 and today.day == 28:
            try:
                date(today.year, 2, 29)
            except ValueError:
                return True
        return today.month == 2 and today.day == 29
    return today.month == birth.month and today.day == birth.day


async def grant_birthday_points(
    db: AsyncSession,
    *,
    user: User,
    today: date | None = None,
) -> ActionGrantResult:
    """If today is the user's birthday, grant once per calendar year."""
    today = today or date.today()
    if user.birth_date is None:
        return ActionGrantResult(0, None, None)
    if not is_birthday_today(user.birth_date, today):
        return ActionGrantResult(0, None, None)

    action = await find_active_action(
        db, action_type=ACTION_TYPE_BIRTHDAY, user=user
    )
    if action is None:
        return ActionGrantResult(0, None, None)

    # Default: once per year per user.
    year = today.year
    per_user = action.per_user_limit if action.per_user_limit is not None else 1
    used = await _count_grants(
        db,
        action_id=action.id,
        user_id=user.id,
        tx_type=TX_TYPE_BIRTHDAY,
        year=year,
    )
    if used >= per_user:
        return ActionGrantResult(0, action, None)
    if action.total_limit is not None:
        used_total = await _count_grants(
            db,
            action_id=action.id,
            tx_type=TX_TYPE_BIRTHDAY,
            year=year,
        )
        if used_total >= action.total_limit:
            return ActionGrantResult(0, action, None)

    await apply_points(
        db,
        user=user,
        points=action.points,
        type=TX_TYPE_BIRTHDAY,
        town_id=action.town_id,
        ref_id=action.id,
        description=action.name or "Birthday bonus",
    )
    return ActionGrantResult(
        action.points,
        action,
        action.name or action.description or None,
    )
