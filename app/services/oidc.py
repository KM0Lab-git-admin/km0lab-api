"""Checking a signed identity token (OpenID Connect), as Google and Apple
hand them out.

The app receives the token from the network and sends it here. Nothing in
it is believed until all of this holds:

- it is signed (RS256) with one of the network's **current public keys**,
  fetched from the network's own address and kept for an hour;
- it was issued **for our app** (``aud`` is our client id) — a token issued
  for someone else's app is somebody else's login, not ours;
- it was issued **by that network** (``iss``);
- it has **not expired**;
- if a nonce is expected, it carries **that nonce**: the token was made
  for a sign-in this server started, not picked up somewhere else.

No extra library: the API already has what signs and checks its own
sessions (python-jose) and what fetches (httpx).
"""

from __future__ import annotations

import hmac
import time

import httpx
from jose import JWTError, jwt

JWKS_TTL_SECONDS = 3600
ALGORITHM = "RS256"

# url -> (fetched at, keys by kid)
_KEYS: dict[str, tuple[float, dict[str, dict]]] = {}


class CredentialRefused(Exception):
    """The token is not one the network vouches for, for us, right now."""


async def _fetch_jwks(url: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def _keys(url: str, *, fresh: bool = False) -> dict[str, dict]:
    cached = _KEYS.get(url)
    if cached and not fresh and time.monotonic() - cached[0] < JWKS_TTL_SECONDS:
        return cached[1]
    document = await _fetch_jwks(url)
    keys = {
        key["kid"]: key
        for key in document.get("keys", [])
        if isinstance(key, dict) and key.get("kid")
    }
    _KEYS[url] = (time.monotonic(), keys)
    return keys


async def verify_id_token(
    token: str,
    *,
    jwks_url: str,
    issuers: tuple[str, ...],
    audience: str,
    nonce: str | None = None,
) -> dict:
    """The claims of ``token`` if everything above holds; else it refuses.

    A failure to reach the network's keys is not a refusal: it is raised as
    it is, so the caller can tell "try again" from "this is not valid".
    """
    if not audience:
        raise CredentialRefused("no client id configured")
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise CredentialRefused("not a token") from exc
    # Only the algorithm the networks sign with: never "none", and never a
    # symmetric one that would take the public key as a shared secret.
    if header.get("alg") != ALGORITHM:
        raise CredentialRefused("unexpected algorithm")
    kid = header.get("kid")
    if not kid:
        raise CredentialRefused("no key id")

    key = (await _keys(jwks_url)).get(kid)
    if key is None:
        # The networks rotate their keys: look again once before refusing.
        key = (await _keys(jwks_url, fresh=True)).get(kid)
    if key is None:
        raise CredentialRefused("unknown key")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            audience=audience,
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise CredentialRefused(str(exc)) from exc
    if claims.get("iss") not in issuers:
        raise CredentialRefused("unexpected issuer")
    if not claims.get("sub"):
        raise CredentialRefused("no subject")
    if nonce is not None and not hmac.compare_digest(
        str(claims.get("nonce") or ""), nonce
    ):
        raise CredentialRefused("nonce does not match")
    return claims
