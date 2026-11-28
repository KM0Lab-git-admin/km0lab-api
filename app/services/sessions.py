"""Sessions: sign in once, stay in.

A person signs in once and is not asked again while they keep using the
app. How:

- The session token lasts ``SESSION_IDLE_DAYS`` (a year; 30 days for an
  administrator) **from the last time it was renewed**.
- The apps renew it quietly when they open (``POST /auth/renew``): whoever
  uses the app never reaches the date. Whoever stops using it for that
  long signs in again.
- A renewal that fails because of the connection changes nothing: the
  token the app holds is still good. Nothing here can sign a person out
  for having bad coverage.

What can end a session: the person signing out on that device (the app
drops the token), a year without use, the account being deleted, and
``close_all_sessions`` — a lost phone, or "close my session on all my
devices". That one is all the devices or none: each account has a counter
(``users.session_epoch``), every token carries the value it was issued
with, and adding one makes every earlier token stop working.

The signing key (``JWT_SECRET``) must never change once there are real
accounts: changing it signs everybody out at once.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.models import User

logger = logging.getLogger("km0lab-api.sessions")

# The value the code ships with and .env.example shows. It is public.
EXAMPLE_JWT_SECRET = "change-me-in-production"

EPOCH_CLAIM = "ep"


def token_epoch(payload: dict) -> int:
    """The counter a token was issued with. Tokens from before the counter
    existed carry none: they count as 0, like the accounts of that time."""
    value = payload.get(EPOCH_CLAIM)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def is_closed(user: User, payload: dict) -> bool:
    """This token's session was closed from the server."""
    return token_epoch(payload) != int(user.session_epoch or 0)


def close_all_sessions(user: User) -> None:
    """Every token this account holds, on every device, stops working."""
    user.session_epoch = int(user.session_epoch or 0) + 1


def check_signing_key(settings: Settings) -> None:
    """Refuse to run on the public example key where real people sign in.

    With the example key anybody can write a valid session for any account.
    In production the API does not start. In staging (UAT, where the pilot
    runs today) it starts and says so as loudly as a log can; in local
    development it is what everybody uses.
    """
    if settings.jwt_secret != EXAMPLE_JWT_SECRET:
        return
    env = settings.environment.lower().strip()
    if env == "development":
        return
    message = (
        "JWT_SECRET is the public example value: anybody can forge a session "
        "for any account. Set a long random one in this environment."
    )
    if env == "staging":
        logger.critical(message)
        return
    raise RuntimeError(message)
