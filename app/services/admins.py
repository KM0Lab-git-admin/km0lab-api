"""Registering the administrator of a municipality.

An admin is tied to a municipality through a postal code (``User.town_id``
is derived from it), so a new admin gets the municipality's primary postal
code. There is no password: they enter the backoffice with their email and
the one-time code sent to it.

Used by ``scripts/add_admin.py``. Kept here so the rules are tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.demo import is_fake_postal_code
from app.models import Town, TownPostalCode, User
from app.roles import ROLE_ADMIN, ROLE_RESIDENT
from app.services.slugs import allocate_user_slug
from app.services.towns import get_primary_postal_code


class AdminRefused(RuntimeError):
    """A safety check failed; nothing was changed."""


@dataclass
class AdminReport:
    municipality: str
    email: str
    postal_code: str
    # "created" | "promoted" | "unchanged"
    outcome: str
    other_admins: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        what = {
            "created": "create the account and make it administrator",
            "promoted": "make the existing resident account administrator",
            "unchanged": "already its administrator: nothing to do",
        }[self.outcome]
        lines = [
            f"{self.municipality}: {self.email} -> {what}",
            f"{self.municipality}: tied through postal code {self.postal_code}",
        ]
        if self.other_admins:
            lines.append(
                f"{self.municipality}: other administrators kept: "
                + ", ".join(self.other_admins)
            )
        return lines


async def register_admin(
    db: AsyncSession,
    *,
    town: Town,
    email: str,
    first_name: str | None = None,
    last_name: str | None = None,
    allow_additional: bool = False,
) -> AdminReport:
    """Make ``email`` the administrator of ``town``. Flushes, never commits.

    Refuses rather than guesses when the email already belongs to someone
    whose account would change meaning: a merchant (the roles are
    incompatible), the admin of another municipality, or a resident of
    another one (their postal code, and with it their town, would move).
    """
    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise AdminRefused(f"'{email}' is not an email address")

    codes = list(
        (
            await db.execute(
                select(TownPostalCode.postal_code).where(
                    TownPostalCode.town_id == town.id
                )
            )
        )
        .scalars()
        .all()
    )
    primary = await get_primary_postal_code(db, town.id)
    if primary is None or not codes:
        raise AdminRefused(f"{town.name} has no postal code to tie an admin to")
    if any(is_fake_postal_code(code) for code in codes):
        raise AdminRefused(
            f"{town.name} is a demo or test territory: its accounts come from the seeds"
        )

    admins = (
        (
            await db.execute(
                select(User).where(
                    User.is_admin.is_(True),
                    User.is_fake.is_(False),
                    User.postal_code.in_(codes),
                )
            )
        )
        .scalars()
        .all()
    )
    others = sorted(a.email for a in admins if a.email.lower() != email)
    report = AdminReport(
        municipality=town.name,
        email=email,
        postal_code=primary.postal_code,
        outcome="created",
        other_admins=others,
    )

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalars().first()

    if user is not None and user.is_admin:
        if user.postal_code in codes:
            report.outcome = "unchanged"
            report.postal_code = user.postal_code or primary.postal_code
            return report
        raise AdminRefused(f"{email} already administers another municipality")

    if others and not allow_additional:
        raise AdminRefused(
            f"{town.name} already has an administrator ({', '.join(others)}). "
            "A municipality has one; pass --additional to add another on purpose."
        )

    if user is None:
        user = User(
            email=email,
            slug=await allocate_user_slug(
                db, first_name=first_name, last_name=last_name, email=email
            ),
            first_name=first_name,
            last_name=last_name,
            lang=town.default_lang or "ca",
            postal_code=primary.postal_code,
            points=0,
            is_fake=False,
        )
        user.set_roles([ROLE_RESIDENT, ROLE_ADMIN])
        db.add(user)
        await db.flush()
        return report

    if user.is_fake:
        raise AdminRefused(f"{email} is a demo or test account")
    if user.is_merchant:
        raise AdminRefused(
            f"{email} is a merchant: an account cannot be merchant and admin. "
            "Use another email."
        )
    if user.postal_code and user.postal_code not in codes:
        raise AdminRefused(
            f"{email} is a resident of another town (postal code "
            f"{user.postal_code}): making it admin here would move the account. "
            "Use another email."
        )
    if not user.postal_code:
        user.postal_code = primary.postal_code
    user.set_roles([*user.roles, ROLE_ADMIN])
    if first_name and not user.first_name:
        user.first_name = first_name
    if last_name and not user.last_name:
        user.last_name = last_name
    report.outcome = "promoted"
    report.postal_code = user.postal_code
    await db.flush()
    return report
