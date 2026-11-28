"""Getting in with a social network: what is common to all of them.

Each network is a small **verifier**: it takes the credential the app got
from the network (never a password) and answers who that person is there
(``SocialProfile``) or refuses. Everything else — finding or creating the
account, the terms, the capacity of the pilot, the invitation — is the same
path as the code sent by email (``app/api/auth.py``).

Switching a network on needs no deployment: it is offered when it is listed
in ``AUTH_PROVIDERS``, has its client id in the environment and has a
verifier here. Until then the app does not show its button.

No credential of any network is stored: it is verified and thrown away.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from jose import JWTError, jwt

from app.config import get_settings
from app.services.identities import (
    PROVIDER_APPLE,
    PROVIDER_GOOGLE,
    SOCIAL_PROVIDERS,
)
from app.services.oidc import CredentialRefused, verify_id_token

LINK_PURPOSE = "link_identity"
LINK_TOKEN_MINUTES = 15


@dataclass
class SocialProfile:
    """Who the person is in that network, as the network itself says."""

    # Stable id of the person there. This is the identity, never the email.
    subject: str
    email: str | None = None
    # Only a verified email may open an account that already exists.
    email_verified: bool = False
    first_name: str | None = None
    last_name: str | None = None


# The network did not vouch for that credential.
SocialRefused = CredentialRefused


Verifier = Callable[[str], Awaitable[SocialProfile]]

# provider -> verifier. A network without a verifier here cannot be
# switched on, whatever the environment says.
VERIFIERS: dict[str, Verifier] = {}


def client_id(provider: str) -> str:
    """The public id of our app in that network ('' = not configured)."""
    return (getattr(get_settings(), f"{provider}_client_id", "") or "").strip()


def is_enabled(provider: str) -> bool:
    listed = {
        p.strip().lower() for p in (get_settings().auth_providers or "").split(",")
    }
    return provider in listed and provider in VERIFIERS and bool(client_id(provider))


def enabled_providers(platform: str | None = None) -> list[str]:
    """The networks to offer, in the order the app shows them.

    - Web: every network that is switched on.
    - Android app: none yet. Google's web button does not work inside an
      app; it needs its own native sign-in.
    - iPhone app: Apple only.
    """
    platform = (platform or "web").strip().lower()
    on = [p for p in SOCIAL_PROVIDERS if is_enabled(p)]
    if platform == "android":
        return []
    if platform == "ios":
        return [p for p in on if p == PROVIDER_APPLE]
    return on


async def verify_credential(provider: str, credential: str) -> SocialProfile:
    profile = await VERIFIERS[provider](credential)
    if not (profile.subject or "").strip():
        raise SocialRefused("no subject")
    return profile


# ── Google ────────────────────────────────────────────────────────────
# The "Sign in with Google" button hands the app an identity token; the
# credential sent here is that token. Google always gives an email and
# says whether it has verified it.

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


async def verify_google(credential: str) -> SocialProfile:
    claims = await verify_id_token(
        credential,
        jwks_url=GOOGLE_JWKS_URL,
        issuers=GOOGLE_ISSUERS,
        audience=client_id(PROVIDER_GOOGLE),
    )
    return SocialProfile(
        subject=str(claims["sub"]),
        email=claims.get("email") or None,
        # A boolean; some of Google's tokens carry it as text.
        email_verified=claims.get("email_verified") in (True, "true"),
        first_name=claims.get("given_name") or None,
        last_name=claims.get("family_name") or None,
    )


VERIFIERS[PROVIDER_GOOGLE] = verify_google


# ── "Your email is missing" ───────────────────────────────────────────
# A network may vouch for the person and give no email we can trust
# (Facebook may give none). The account still needs one, so the person
# types it and confirms it with the code. This short-lived token carries
# who they proved to be in the network from one step to the other; it is
# not a session (it has no ``sub``) and holds nothing of the network's.


def create_link_token(provider: str, subject: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "purpose": LINK_PURPOSE,
            "provider": provider,
            "psub": subject,
            "iat": now,
            "exp": now + timedelta(minutes=LINK_TOKEN_MINUTES),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def read_link_token(token: str | None) -> tuple[str, str] | None:
    """(provider, subject) if the token is ours, of this kind and alive."""
    settings = get_settings()
    try:
        claims = jwt.decode(
            token or "", settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
    provider, subject = claims.get("provider"), claims.get("psub")
    if claims.get("purpose") != LINK_PURPOSE or provider not in SOCIAL_PROVIDERS:
        return None
    if not isinstance(subject, str) or not subject:
        return None
    return provider, subject
