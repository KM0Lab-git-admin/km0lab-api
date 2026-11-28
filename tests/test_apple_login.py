"""The Apple verifier: what makes a "Sign in with Apple" token ours
(``verify_apple`` in ``app/services/social.py``).

Tokens here are signed for real, with a key made for the test standing in
for Apple's; Apple's address is never called.
"""

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt
from sqlalchemy import select

from app.config import get_settings
from app.models import User
from app.services import oidc
from app.services.capacity import CURRENT_TERMS_VERSION
from app.services.social import (
    APPLE_JWKS_URL,
    SocialRefused,
    create_nonce,
    read_nonce_token,
    verify_apple,
    verify_google,
)
from tests._municipalities import API, admin_headers, malgrat

pytestmark = pytest.mark.asyncio

SERVICES_ID = "com.km0lab.app.web"
HIDDEN = "x7k2p9q4rt@privaterelay.appleid.com"


def _key_pair(kid: str) -> tuple[str, dict]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    public = jwk.construct(public_pem, "RS256").to_dict()
    return private_pem, {**public, "kid": kid, "use": "sig", "alg": "RS256"}


PRIVATE, PUBLIC = _key_pair("APPLEKEY01")
OTHER_PRIVATE, OTHER_PUBLIC = _key_pair("GOOGLEKEY1")


def token(nonce: str, private: str = PRIVATE, kid: str = "APPLEKEY01", **over) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": SERVICES_ID,
        "sub": "001234.a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6.0912",
        "email": "marta@icloud.com",
        # Apple sends these two as text or as booleans.
        "email_verified": "true",
        "is_private_email": "false",
        "nonce": nonce,
        "nonce_supported": True,
        "iat": now,
        "exp": now + 600,
        **over,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid})


class FakeKeys:
    def __init__(self) -> None:
        self.by_url = {APPLE_JWKS_URL: [PUBLIC]}
        self.asked: list[str] = []

    async def fetch(self, url: str) -> dict:
        self.asked.append(url)
        return {"keys": self.by_url.get(url, [])}


@pytest.fixture
def apple(monkeypatch):
    """Apple switched on, publishing its key at its own address."""
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_providers", "apple")
    monkeypatch.setattr(settings, "apple_client_id", SERVICES_ID)
    fake = FakeKeys()
    monkeypatch.setattr(oidc, "_fetch_jwks", fake.fetch)
    monkeypatch.setattr(oidc, "_KEYS", {})
    return fake


async def test_a_token_apple_signed_for_this_sign_in_says_who_it_is(apple):
    nonce, nonce_token = create_nonce()
    assert read_nonce_token(nonce_token) == nonce

    profile = await verify_apple(token(nonce), nonce)
    assert profile.subject == "001234.a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6.0912"
    assert (profile.email, profile.email_verified) == ("marta@icloud.com", True)
    # The name is never in Apple's token: the app sends it apart.
    assert (profile.first_name, profile.last_name) == (None, None)
    assert apple.asked == [APPLE_JWKS_URL]

    # "Verified" as a boolean, and a hidden email, are the same to us.
    profile = await verify_apple(
        token(nonce, email=HIDDEN, email_verified=True, is_private_email=True), nonce
    )
    assert (profile.email, profile.email_verified) == (HIDDEN, True)
    # A Work & School account: no email Apple vouches for.
    profile = await verify_apple(token(nonce, email=None, email_verified="false"), nonce)
    assert (profile.email, profile.email_verified) == (None, False)


async def test_apple_always_needs_the_nonce_of_this_sign_in(apple):
    nonce, _ = create_nonce()
    other, _ = create_nonce()

    # Sent without saying which sign-in it belongs to.
    with pytest.raises(SocialRefused, match="nonce"):
        await verify_apple(token(nonce), None)
    # A token made for another sign-in (picked up somewhere, replayed).
    with pytest.raises(SocialRefused, match="nonce"):
        await verify_apple(token(other), nonce)
    # A token with no nonce inside.
    with pytest.raises(SocialRefused, match="nonce"):
        await verify_apple(token(None), nonce)


@pytest.mark.parametrize(
    "why, over",
    [
        ("issued for another app", {"aud": "com.someone.else"}),
        ("issued for our iPhone app id, which the web does not accept", {"aud": "com.km0lab.app"}),
        ("issued by someone else", {"iss": "https://accounts.google.com"}),
        ("expired", {"exp": int(time.time()) - 60}),
        ("no subject", {"sub": ""}),
    ],
)
async def test_anything_else_is_refused(apple, why, over):
    nonce, _ = create_nonce()
    with pytest.raises(SocialRefused):
        await verify_apple(token(nonce, **over), nonce)


async def test_a_bad_signature_is_refused(apple):
    nonce, _ = create_nonce()
    with pytest.raises(SocialRefused):
        await verify_apple(token(nonce, private=OTHER_PRIVATE), nonce)
    with pytest.raises(SocialRefused):
        await verify_apple("this-is-not-a-token", nonce)


async def test_one_networks_token_is_never_anothers(apple, monkeypatch):
    """Google and Apple hand out the same kind of token. Each is only good
    at its own door, even with both issued for 'our' client id."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", SERVICES_ID)
    apple.by_url["https://www.googleapis.com/oauth2/v3/certs"] = [OTHER_PUBLIC]
    nonce, _ = create_nonce()

    apples = token(nonce)
    googles = token(
        nonce, private=OTHER_PRIVATE, kid="GOOGLEKEY1", iss="https://accounts.google.com"
    )
    # Each one is fine where it belongs...
    assert (await verify_apple(apples, nonce)).subject
    assert (await verify_google(googles, nonce)).subject
    # ...and refused at the other door.
    with pytest.raises(SocialRefused):
        await verify_apple(googles, nonce)
    with pytest.raises(SocialRefused):
        await verify_google(apples, nonce)


async def test_google_checks_the_nonce_when_it_comes(apple, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", SERVICES_ID)
    apple.by_url["https://www.googleapis.com/oauth2/v3/certs"] = [OTHER_PUBLIC]
    nonce, _ = create_nonce()
    other, _ = create_nonce()
    googles = token(
        other, private=OTHER_PRIVATE, kid="GOOGLEKEY1", iss="https://accounts.google.com"
    )
    assert (await verify_google(googles, None)).subject
    assert (await verify_google(googles, other)).subject
    with pytest.raises(SocialRefused, match="nonce"):
        await verify_google(googles, nonce)


# ── Through the door ──────────────────────────────────────────────────


async def _start(client) -> dict:
    r = await client.post(f"{API}/auth/social/apple/nonce")
    assert r.status_code == 200, r.text
    return r.json()


async def test_getting_in_with_apple_end_to_end(client, db_session, apple):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    for platform in ("web", "ios"):
        offered = await client.get(f"{API}/auth/providers", headers={"X-App-Platform": platform})
        assert offered.json() == {"providers": [{"provider": "apple", "client_id": SERVICES_ID}]}

    # The app asks for a nonce, Apple writes it in the token, both come back.
    start = await _start(client)
    r = await client.post(
        f"{API}/auth/social/apple",
        json={
            "credential": token(start["nonce"], email=HIDDEN, is_private_email="true"),
            "nonce_token": start["nonce_token"],
            "postal_code": "08380",
            "terms_version": CURRENT_TERMS_VERSION,
            # Apple gives the name to the app, the first time only.
            "first_name": "Marta",
            "last_name": "Puig",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    user = body["user"]
    assert user["email"] == HIDDEN and (user["first_name"], user["last_name"]) == ("Marta", "Puig")
    assert user["terms_version"] == CURRENT_TERMS_VERSION and body["points_awarded"]

    # Her card says she came in by Apple and that her email is a hidden one.
    card = (await client.get(f"{API}/residents/{user['id']}", headers=admin)).json()
    assert card["signup_provider"] == "apple" and card["email_hidden"] is True
    mine = await client.get(
        f"{API}/users/me/sign-in-methods",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert mine.json()["created_with"] == "apple" and mine.json()["email_hidden"] is True

    # Next time: no name from Apple, and the one she has is kept.
    start = await _start(client)
    r = await client.post(
        f"{API}/auth/social/apple",
        json={
            "credential": token(start["nonce"], email=HIDDEN),
            "nonce_token": start["nonce_token"],
        },
    )
    assert r.status_code == 200 and r.json()["user"]["id"] == user["id"]
    assert r.json()["user"]["first_name"] == "Marta" and r.json()["points_awarded"] is None


async def test_without_the_right_nonce_nothing_gets_in(client, db_session, apple):
    await malgrat(db_session)
    await db_session.commit()
    start = await _start(client)
    another = await _start(client)
    good = token(start["nonce"])

    for why, body in {
        "no nonce sent back": {"credential": good},
        "the nonce of another sign-in": {"credential": good, "nonce_token": another["nonce_token"]},
        "a made-up nonce token": {"credential": good, "nonce_token": "not-a-token"},
    }.items():
        r = await client.post(f"{API}/auth/social/apple", json=body)
        assert r.status_code == 401, why
        assert r.json()["detail"]["code"] == "provider_failed", why
    assert (await db_session.execute(select(User))).first() is None

    # A nonce is only handed out for a network that is switched on.
    assert (await client.post(f"{API}/auth/social/google/nonce")).status_code == 404


async def test_an_apple_account_without_email_confirms_one(client, capture_otp, db_session, apple):
    await malgrat(db_session)
    await db_session.commit()
    start = await _start(client)
    r = await client.post(
        f"{API}/auth/social/apple",
        json={
            "credential": token(start["nonce"], email=None, email_verified="false"),
            "nonce_token": start["nonce_token"],
        },
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "email_missing"

    body = {"email": "alumna@escola.cat", "postal_code": "08380"}
    await client.post(f"{API}/auth/request-otp", json=body)
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={**body, "code": capture_otp(), "link_token": r.json()["detail"]["link_token"]},
    )
    assert r.status_code == 200, r.text
    start = await _start(client)
    again = await client.post(
        f"{API}/auth/social/apple",
        json={
            "credential": token(start["nonce"], email=None, email_verified="false"),
            "nonce_token": start["nonce_token"],
        },
    )
    assert again.status_code == 200 and again.json()["user"]["id"] == r.json()["user"]["id"]
