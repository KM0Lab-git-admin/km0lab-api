"""The Facebook verifier: Facebook is asked, and only its answer is believed
(``verify_facebook`` in ``app/services/social.py``).

Facebook here is a make-believe one that answers like Meta's documentation
says; the real address is never called.
"""

import hashlib
import hmac
import logging

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import User, UserIdentity
from app.services import social
from app.services.social import SocialRefused, verify_facebook
from tests._municipalities import API, malgrat

pytestmark = pytest.mark.asyncio

APP_ID = "889900112233"
SECRET = "f4c3b00k-app-secret-do-not-log"
TOKEN = "EAAMartaUserAccessToken0123456789"


class FakeFacebook:
    """What Facebook knows: which tokens exist, for which app and person."""

    def __init__(self) -> None:
        # token -> (app the token was issued for, person's id for that app)
        self.tokens = {TOKEN: (APP_ID, "10158")}
        self.people = {
            "10158": {"id": "10158", "first_name": "Marta", "last_name": "Puig", "email": "marta@test.cat"}
        }
        self.asked: list[httpx.Request] = []
        self.down = False
        self.app_token_ok = True

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if self.down:
            return httpx.Response(503, text="Service Unavailable")
        params = dict(request.url.params)
        if request.url.path.endswith("/debug_token"):
            if params.get("access_token") != f"{APP_ID}|{SECRET}" or not self.app_token_ok:
                return httpx.Response(
                    400, json={"error": {"type": "OAuthException", "code": 190, "message": "Invalid OAuth access token."}}
                )
            known = self.tokens.get(params.get("input_token", ""))
            if known is None:
                return httpx.Response(
                    200, json={"data": {"is_valid": False, "error": {"code": 190, "message": "Invalid token"}}}
                )
            app_id, user_id = known
            return httpx.Response(
                200,
                json={"data": {"app_id": app_id, "type": "USER", "is_valid": True, "user_id": user_id, "scopes": ["email", "public_profile"]}},
            )
        if request.url.path.endswith("/me"):
            token = params.get("access_token", "")
            known = self.tokens.get(token)
            proof = hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
            if known is None or params.get("appsecret_proof") != proof:
                return httpx.Response(
                    400, json={"error": {"type": "OAuthException", "code": 190, "message": "Invalid"}}
                )
            return httpx.Response(200, json=self.people[known[1]])
        return httpx.Response(404, json={"error": {"type": "GraphMethodException", "code": 100}})


@pytest.fixture
def facebook(monkeypatch):
    """Facebook switched on, answered by the make-believe one."""
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_providers", "facebook")
    monkeypatch.setattr(settings, "facebook_client_id", APP_ID)
    monkeypatch.setattr(settings, "facebook_app_secret", SECRET)
    fake = FakeFacebook()
    monkeypatch.setattr(social, "_facebook_transport", httpx.MockTransport(fake.handle))
    return fake


async def test_facebook_is_asked_and_says_who_it_is(facebook):
    profile = await verify_facebook(TOKEN)

    assert profile.subject == "10158"
    assert (profile.first_name, profile.last_name) == ("Marta", "Puig")
    # Facebook gives an email but does not vouch for it.
    assert (profile.email, profile.email_verified) == ("marta@test.cat", False)

    # Two questions, to Facebook's own address and the version in force.
    first, second = facebook.asked
    assert str(first.url).startswith("https://graph.facebook.com/v27.0/debug_token?")
    assert first.url.params["access_token"] == f"{APP_ID}|{SECRET}"
    assert str(second.url).startswith("https://graph.facebook.com/v27.0/me?")
    # The second one is signed with our secret, as Meta recommends.
    assert second.url.params["appsecret_proof"] == hmac.new(
        SECRET.encode(), TOKEN.encode(), hashlib.sha256
    ).hexdigest()
    assert "email" in second.url.params["fields"]


async def test_a_token_another_app_obtained_does_not_get_in(facebook):
    """The person really signed in with Facebook — but in somebody else's
    app. That app must not be able to use the token here."""
    facebook.tokens["EAAOtherAppToken0123456789"] = ("111111111111", "10158")
    with pytest.raises(SocialRefused, match="another app"):
        await verify_facebook("EAAOtherAppToken0123456789")
    # Asked about it, and stopped there: never asked who it is.
    assert len(facebook.asked) == 1


@pytest.mark.parametrize(
    "why, token",
    [
        ("Facebook does not know it", "EAANobodyKnowsThisToken0123"),
        ("it is a Google credential", "eyJhbGciOiJSUzI1NiIsImtpZCI6ImtleS0xIn0.e30.c2ln"),
    ],
)
async def test_what_facebook_does_not_vouch_for_is_refused(facebook, why, token):
    with pytest.raises(SocialRefused):
        await verify_facebook(token)


async def test_the_token_and_the_profile_must_be_the_same_person(facebook):
    facebook.people["10158"] = {"id": "99999", "first_name": "Altra"}
    with pytest.raises(SocialRefused, match="same person"):
        await verify_facebook(TOKEN)


async def test_no_email_is_not_a_problem_here(facebook):
    facebook.people["10158"] = {"id": "10158", "first_name": "Marta"}
    profile = await verify_facebook(TOKEN)
    assert profile.subject == "10158" and profile.email is None


async def test_without_the_secret_facebook_is_not_offered(client, facebook, monkeypatch):
    monkeypatch.setattr(get_settings(), "facebook_app_secret", "")
    assert (await client.get(f"{API}/auth/providers")).json() == {"providers": []}
    r = await client.post(f"{API}/auth/social/facebook", json={"credential": TOKEN})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "provider_disabled"
    with pytest.raises(SocialRefused):
        await verify_facebook(TOKEN)
    assert facebook.asked == []


async def test_the_secret_and_the_tokens_never_reach_the_log(facebook, caplog):
    import app.main  # noqa: F401  (what silences the request log)

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    facebook.app_token_ok = False  # Facebook rejects our own app token
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(SocialRefused):
            await verify_facebook(TOKEN)
        facebook.app_token_ok = True
        await verify_facebook(TOKEN)
    assert SECRET not in caplog.text and TOKEN not in caplog.text
    # But it does say that Facebook said no, and why.
    assert "Facebook said no to /debug_token" in caplog.text and "190" in caplog.text


# ── Through the door ──────────────────────────────────────────────────


async def test_getting_in_with_facebook_end_to_end(client, capture_otp, db_session, facebook):
    await malgrat(db_session)
    await db_session.commit()
    assert (await client.get(f"{API}/auth/providers")).json() == {
        "providers": [{"provider": "facebook", "client_id": APP_ID}]
    }

    # Facebook's email is not proof: the person confirms one with the code.
    r = await client.post(
        f"{API}/auth/social/facebook", json={"credential": TOKEN, "postal_code": "08380"}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "email_missing"
    assert (await db_session.execute(select(User))).first() is None
    link = r.json()["detail"]["link_token"]

    body = {"email": "marta@test.cat", "postal_code": "08380"}
    await client.post(f"{API}/auth/request-otp", json=body)
    r = await client.post(
        f"{API}/auth/verify-otp", json={**body, "code": capture_otp(), "link_token": link}
    )
    assert r.status_code == 200, r.text
    marta = r.json()["user"]
    doors = (
        await db_session.execute(
            select(UserIdentity.provider, UserIdentity.is_first)
            .where(UserIdentity.user_id == marta["id"])
            .order_by(UserIdentity.is_first.desc())
        )
    ).all()
    assert [tuple(d) for d in doors] == [("facebook", True), ("email_code", False)]

    # From then on, Facebook alone is enough.
    r = await client.post(f"{API}/auth/social/facebook", json={"credential": TOKEN})
    assert r.status_code == 200 and r.json()["user"]["id"] == marta["id"]

    # A token Facebook does not vouch for opens nothing.
    r = await client.post(
        f"{API}/auth/social/facebook", json={"credential": "EAANobodyKnowsThisToken0123"}
    )
    assert r.status_code == 401 and r.json()["detail"]["code"] == "provider_failed"


async def test_if_facebook_does_not_answer_it_says_try_again(client, db_session, facebook):
    await malgrat(db_session)
    await db_session.commit()
    facebook.down = True
    r = await client.post(f"{API}/auth/social/facebook", json={"credential": TOKEN})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "provider_failed"
