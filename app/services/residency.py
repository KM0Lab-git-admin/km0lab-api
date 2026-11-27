"""Where an account lives: its municipality, and its side (real or demo).

The side follows the postal code: Demo KM0 (00000) and the QA territory are
make-believe, every other municipality is real. Points earned on one side
must never be spent on the other, and the app sends the device's postal
code every time someone logs in, so the move has rules:

- Between two real municipalities: free, as before.
- From the demonstration to a real municipality: allowed **when the person
  says so** (``leave_demo``), with the balance set to zero and then the
  welcome points of the new town, like any new resident. Whoever tried the
  demo can join the pilot of their town with the same email; what they
  earned playing stays in the demo. It is never automatic: the app sends
  the device's postal code on every login, and a demo account used to show
  the product must not be lost by logging in from the wrong phone.
- From a real municipality to the demonstration: never. A real resident
  tries the demo with another email.

A postal code is not cleared either: an account that has a municipality
keeps one. The refusals are silent (the account is answered as it is):
the caller is the app syncing the device, not a person asking.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.demo import desired_user_is_fake, is_demo_email, is_fake_postal_code
from app.models import InvitationLink, TownPostalCode, User
from app.qa import is_qa_email
from app.roles import ROLE_ADMIN, ROLE_MERCHANT
from app.services.action_grants import grant_signup_points
from app.services.capacity import town_is_full
from app.services.points import apply_points, lock_user_points

# Ledger type of the movement that empties a balance on leaving the demo.
TX_DEMO_EXIT = "demo_exit"

MOVED = "moved"
LEFT_DEMO = "left_demo"
STAYS = "stays"


def _bound_to_its_side(user: User) -> bool:
    """Fixed demo and QA accounts, and whoever runs a shop or a municipality,
    belong where they are."""
    return (
        is_demo_email(user.email)
        or is_qa_email(user.email)
        or user.has_role(ROLE_ADMIN)
        or user.has_role(ROLE_MERCHANT)
    )


async def move_resident(
    db: AsyncSession,
    user: User,
    postal: TownPostalCode | None,
    *,
    leave_demo: bool = False,
) -> str:
    """Give ``user`` the postal code ``postal`` if the rules allow it.

    ``leave_demo``: the person confirmed they want their demo account to
    become their resident account. Without it a demo account stays put.

    Returns ``MOVED``, ``LEFT_DEMO`` (moved, balance emptied, welcome points
    of the new town granted) or ``STAYS``.
    """
    if postal is None or postal.postal_code == user.postal_code:
        return STAYS

    # Arriving in another municipality takes a place there, like signing up.
    arriving = postal.town_id != user.town_id
    to_real = not desired_user_is_fake(user.email, postal.postal_code)
    if arriving and to_real and not _bound_to_its_side(user):
        if await town_is_full(db, postal.town_id, lock=True):
            return STAYS

    if user.postal_code:
        from_demo = desired_user_is_fake(user.email, user.postal_code)
        to_demo = is_fake_postal_code(postal.postal_code)
        if from_demo != to_demo:
            if to_demo or not leave_demo or _bound_to_its_side(user):
                return STAYS
            await _leave_demo(db, user)
            _set_postal(user, postal)
            await _carry_invite_links(db, user, postal.town_id)
            # A new resident of that town: its welcome points, once.
            await grant_signup_points(db, user=user)
            return LEFT_DEMO

    _set_postal(user, postal)
    await _carry_invite_links(db, user, postal.town_id)
    return MOVED


def _set_postal(user: User, postal: TownPostalCode) -> None:
    user.postal_code = postal.postal_code
    user.postal_ref = postal
    user.is_fake = desired_user_is_fake(user.email, postal.postal_code)


async def _leave_demo(db: AsyncSession, user: User) -> None:
    """Empty the balance, with its movement in the ledger of the demo."""
    await lock_user_points(db, user)
    if user.points > 0:
        await apply_points(
            db,
            user=user,
            points=-user.points,
            type=TX_DEMO_EXIT,
            description="Sortida de la demostració",
        )


async def _carry_invite_links(db: AsyncSession, user: User, town_id: str) -> None:
    """An invitation rewards within one municipality: the link follows its
    owner, or the friends they invite from now on would count for nobody."""
    from sqlalchemy import update

    await db.execute(
        update(InvitationLink)
        .where(
            InvitationLink.inviter_user_id == user.id,
            InvitationLink.town_id != town_id,
        )
        .values(town_id=town_id)
    )
