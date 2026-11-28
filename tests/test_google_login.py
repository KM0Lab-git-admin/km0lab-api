"""The Google verifier: what makes a "Sign in with Google" token ours
(``app/services/oidc.py`` and ``verify_google``).

Tokens here are signed for real, with a key made for the test standing in
for Google's; Google's address is never called.
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
from app.services.social import GOOGLE_JWKS_URL, SocialRefused, verify_google
from tests._municipalities import API, malgrat

pytestmark = pytest.mark.asyncio

CLIENT_ID = "1234-km0lab.apps.googleusercontent.com"


def _key_pair(kid: str) -> tuple[str, dict]:
    """(private key, public key as Google publishes it)."""
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


PRIVATE, PUBLIC = _key_pair("key-1")
OTHER_PRIVATE, OTHER_PUBLIC = _key_pair("key-2")


def token(private: str = PRIVATE, kid: str = "key-1", **over) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "108204268033311374519",
        "email": "marta@gmail.com",
        "email_verified": True,
        "given_name": "Marta",
        "family_name": "Puig",
        "iat": now,
        "exp": now + 3600,
        **over,
    }
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid})


class FakeGoogle:
    """What Google publishes, and every time it was asked for it."""

    def __init__(self) -> None:
        self.keys = [PUBLIC]
        self.asked: list[str] = []

    async def fetch(self, url: str) -> dict:
        self.asked.append(url)
        return {"keys": self.keys}


@pytest.fixture
def google(monkeypatch):
    """Google switched on, publishing ``key-1``."""
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_providers", "google")
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    fake = FakeGoogle()
    monkeypatch.setattr(oidc, "_fetch_jwks", fake.fetch)
    monkeypatch.setattr(oidc, "_KEYS", {})
    return fake


async def test_a_token_google_signed_for_us_says_who_it_is(google):
    profile = await verify_google(token())
    assert profile.subject == "108204268033311374519"
    assert (profile.email, profile.email_verified) == ("marta@gmail.com", True)
    assert (profile.first_name, profile.last_name) == ("Marta", "Puig")
    # Google's keys are asked for at its own address, and kept.
    await verify_google(token())
    assert google.asked == [GOOGLE_JWKS_URL]

    # Both ways Google writes its name and its "verified".
    profile = await verify_google(token(iss="accounts.google.com", email_verified="true"))
    assert profile.email_verified is True
    profile = await verify_google(token(email_verified=False))
    assert profile.email_verified is False


@pytest.mark.parametrize(
    "why, make",
    [
        ("issued for another app", lambda: token(aud="someone-else.apps.googleusercontent.com")),
        ("issued by someone else", lambda: token(iss="https://accounts.example.com")),
        ("expired", lambda: token(exp=int(time.time()) - 60)),
        ("signed with another key", lambda: token(private=OTHER_PRIVATE)),
        ("signed with a key Google does not publish", lambda: token(OTHER_PRIVATE, "key-2")),
        ("no subject", lambda: token(sub="")),
        ("not a token", lambda: "this-is-not-a-token"),
        (
            "unsigned",
            lambda: ".".join(
                [
                    "eyJhbGciOiJub25lIiwia2lkIjoia2V5LTEifQ",
                    token().split(".")[1],
                    "",
                ]
            ),
        ),
    ],
)
async def test_anything_else_is_refused(google, why, make):
    with pytest.raises(SocialRefused):
        await verify_google(make())


async def test_the_public_key_is_never_taken_as_a_shared_secret(google):
    """The classic trick: sign with HS256 using the public key as the secret."""
    claims = jwt.get_unverified_claims(token())
    forged = jwt.encode(claims, "anything", algorithm="HS256", headers={"kid": "key-1"})
    with pytest.raises(SocialRefused):
        await verify_google(forged)


async def test_when_google_changes_its_keys_it_looks_again_once(google):
    await verify_google(token())
    # Google starts signing with a new key the cache has not seen.
    google.keys = [PUBLIC, OTHER_PUBLIC]
    profile = await verify_google(token(OTHER_PRIVATE, "key-2"))
    assert profile.subject and len(google.asked) == 2
    # A key nobody publishes costs one more look, never a loop.
    with pytest.raises(SocialRefused):
        await verify_google(token(kid="key-9"))
    assert len(google.asked) == 3


async def test_without_our_client_id_nothing_is_valid(google, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "")
    with pytest.raises(SocialRefused):
        await verify_google(token())


# ── Through the door ──────────────────────────────────────────────────


async def test_getting_in_with_google_end_to_end(client, db_session, google):
    await malgrat(db_session)
    await db_session.commit()

    offered = (await client.get(f"{API}/auth/providers")).json()
    assert offered == {"providers": [{"provider": "google", "client_id": CLIENT_ID}]}

    r = await client.post(
        f"{API}/auth/social/google",
        json={"credential": token(), "postal_code": "08380", "terms_version": CURRENT_TERMS_VERSION},
    )
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["email"] == "marta@gmail.com" and user["first_name"] == "Marta"
    assert user["town_name"] == "Malgrat de Mar" and user["terms_version"] == CURRENT_TERMS_VERSION

    # A token for another app, or a forged one, opens nothing.
    for bad in (token(aud="another-app"), token(private=OTHER_PRIVATE, email="pere@gmail.com")):
        r = await client.post(
            f"{API}/auth/social/google", json={"credential": bad, "postal_code": "08380"}
        )
        assert r.status_code == 401 and r.json()["detail"]["code"] == "provider_failed"
    assert len((await db_session.execute(select(User))).all()) == 1

    # An email Google has not verified does not open or create an account
    # by itself: the person confirms it with the code.
    r = await client.post(
        f"{API}/auth/social/google",
        json={"credential": token(sub="999", email="pere@empresa.cat", email_verified=False)},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "email_missing"


async def test_if_google_cannot_be_reached_it_says_try_again(
    client, db_session, google, monkeypatch
):
    await malgrat(db_session)
    await db_session.commit()

    async def down(url: str) -> dict:
        raise ConnectionError("no route to Google")

    monkeypatch.setattr(oidc, "_fetch_jwks", down)
    r = await client.post(f"{API}/auth/social/google", json={"credential": token()})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "provider_failed"


async def test_a_token_of_one_network_is_not_another_networks(google):
    """A real Google token, for our own app, handed in as if it were Apple's."""
    apple = dict(
        jwks_url="https://appleid.apple.com/auth/keys",
        issuers=("https://appleid.apple.com",),
        audience=CLIENT_ID,
    )
    # Apple does not publish Google's keys...
    google.keys = [OTHER_PUBLIC]
    with pytest.raises(SocialRefused):
        await oidc.verify_id_token(token(), **apple)
    # ...and even if the key matched, the token says who issued it.
    google.keys = [PUBLIC]
    monkeypatch_cache = oidc._KEYS
    monkeypatch_cache.clear()
    with pytest.raises(SocialRefused):
        await oidc.verify_id_token(token(), **apple)
    # The same token is fine where it belongs.
    monkeypatch_cache.clear()
    assert (await verify_google(token())).subject
