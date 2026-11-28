"""Getting in with a social network: what every network shares
(``app/services/social.py`` and ``POST /auth/social/{provider}``).

The networks here are make-believe verifiers: the real one of each network
has its own tests.
"""

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import PointAction, User, UserIdentity
from app.services import social
from app.services.capacity import CURRENT_TERMS_VERSION
from app.services.social import SocialProfile, SocialRefused, create_link_token
from tests._municipalities import API, admin_headers, malgrat

pytestmark = pytest.mark.asyncio


def cred(subject: str, email: str = "", verified: bool = True, name: str = "") -> str:
    return f"credential|{subject}|{email}|{int(verified)}|{name}"


async def _fake_network(credential: str) -> SocialProfile:
    kind, subject, email, verified, name = credential.split("|")
    if kind != "credential":
        raise SocialRefused("not ours")
    first, _, last = name.partition(" ")
    return SocialProfile(
        subject=subject,
        email=email or None,
        email_verified=verified == "1",
        first_name=first or None,
        last_name=last or None,
    )


@pytest.fixture
def networks(monkeypatch):
    """Google and Facebook switched on, each with a make-believe verifier."""
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_providers", "google, facebook")
    monkeypatch.setattr(settings, "google_client_id", "google-client")
    monkeypatch.setattr(settings, "facebook_client_id", "facebook-app")
    monkeypatch.setattr(settings, "facebook_app_secret", "facebook-secret")
    monkeypatch.setitem(social.VERIFIERS, "google", _fake_network)
    monkeypatch.setitem(social.VERIFIERS, "facebook", _fake_network)


async def _social(client, provider: str, credential: str, headers=None, **extra):
    return await client.post(
        f"{API}/auth/social/{provider}",
        json={"credential": credential, "postal_code": "08380", **extra},
        headers=headers or {},
    )


async def _by_code(client, capture_otp, email: str, **extra):
    body = {"email": email, "postal_code": "08380"}
    r = await client.post(f"{API}/auth/request-otp", json=body)
    assert r.status_code == 200, r.text
    return await client.post(
        f"{API}/auth/verify-otp", json={**body, "code": capture_otp(), **extra}
    )


def _auth(body: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _doors(db, user_id: str) -> list[tuple[str, bool]]:
    rows = (
        await db.execute(
            select(UserIdentity)
            .where(UserIdentity.user_id == user_id)
            .order_by(UserIdentity.is_first.desc(), UserIdentity.provider)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return [(row.provider, row.is_first) for row in rows]


# ── Which networks are offered ────────────────────────────────────────


async def test_a_network_is_offered_only_when_it_is_switched_on(client, monkeypatch):
    settings = get_settings()
    asked = lambda platform=None: client.get(  # noqa: E731
        f"{API}/auth/providers",
        headers={"X-App-Platform": platform} if platform else {},
    )
    # Nothing configured: email only.
    assert (await asked()).json() == {"providers": []}

    monkeypatch.setitem(social.VERIFIERS, "google", _fake_network)
    monkeypatch.setitem(social.VERIFIERS, "apple", _fake_network)
    monkeypatch.setattr(settings, "auth_providers", "apple,google,facebook")
    # Listed, but without its client id it is still off.
    assert (await asked()).json() == {"providers": []}

    monkeypatch.setattr(settings, "google_client_id", "google-client")
    monkeypatch.setattr(settings, "apple_client_id", "com.km0lab.web")
    # Facebook has an id but not the secret it needs to ask Facebook: off.
    monkeypatch.setattr(settings, "facebook_client_id", "facebook-app")
    web = [
        {"provider": "google", "client_id": "google-client"},
        {"provider": "apple", "client_id": "com.km0lab.web"},
    ]
    assert (await asked()).json() == {"providers": web}
    assert (await asked("web")).json() == {"providers": web}
    # Inside the apps: none on Android yet, Apple only on iPhone.
    assert (await asked("android")).json() == {"providers": []}
    assert (await asked("ios")).json() == {"providers": web[1:]}

    # Taking it off the list switches it off, keys and all.
    monkeypatch.setattr(settings, "auth_providers", "apple")
    assert (await asked()).json() == {"providers": web[1:]}
    r = await _social(client, "google", cred("g-1", "marta@test.cat"))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "provider_disabled"
    r = await _social(client, "twitter", cred("t-1", "marta@test.cat"))
    assert r.status_code == 404


async def test_a_credential_the_network_does_not_vouch_for(client, db_session, networks):
    await malgrat(db_session)
    await db_session.commit()
    r = await _social(client, "google", "something-else|g-1|marta@test.cat|1|")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "provider_failed"
    assert (await db_session.execute(select(User))).first() is None


# ── Born with a network ───────────────────────────────────────────────


async def test_an_account_is_born_with_google(client, db_session, networks):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")

    r = await _social(
        client,
        "google",
        cred("g-marta", "Marta@Test.cat", name="Marta Puig"),
        terms_version=CURRENT_TERMS_VERSION,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    user = body["user"]
    assert user["email"] == "marta@test.cat" and user["roles"] == ["resident"]
    assert (user["first_name"], user["last_name"]) == ("Marta", "Puig")
    assert user["town_name"] == "Malgrat de Mar"
    # Same welcome and same proof of consent as by email.
    assert body["points_awarded"] == user["points"] > 0
    assert user["terms_version"] == CURRENT_TERMS_VERSION
    # Its origin is Google: it never used a code.
    assert await _doors(db_session, user["id"]) == [("google", True)]

    mine = (await client.get(f"{API}/users/me/sign-in-methods", headers=_auth(body))).json()
    assert mine["created_with"] == "google" and mine["email"] == "marta@test.cat"
    assert [m["provider"] for m in mine["methods"]] == ["google"]
    card = (await client.get(f"{API}/residents/{user['id']}", headers=admin)).json()
    assert card["signup_provider"] == "google"

    # Coming back: the same account, and no second welcome.
    again = (await _social(client, "google", cred("g-marta", "marta@test.cat"))).json()
    assert again["user"]["id"] == user["id"]
    assert again["points_awarded"] is None and again["user"]["points"] == user["points"]
    # The network's id is the identity: a changed email there changes nothing.
    moved = (await _social(client, "google", cred("g-marta", "altra@test.cat"))).json()
    assert moved["user"]["id"] == user["id"] and moved["user"]["email"] == "marta@test.cat"


async def test_a_verified_email_opens_the_account_that_has_it(
    client, capture_otp, db_session, networks
):
    await malgrat(db_session)
    await db_session.commit()
    by_code = (await _by_code(client, capture_otp, "marta@test.cat")).json()

    r = await _social(client, "google", cred("g-marta", "MARTA@test.cat"))
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == by_code["user"]["id"]
    assert r.json()["points_awarded"] is None
    # Two doors, one account; the origin is still the first one.
    assert await _doors(db_session, by_code["user"]["id"]) == [
        ("email_code", True),
        ("google", False),
    ]


async def test_an_invitation_and_a_waiting_shop_work_the_same(
    client, capture_otp, db_session, networks
):
    town = await malgrat(db_session)
    db_session.add(
        PointAction(
            town_id=town.id,
            type="invite_person",
            name="Convida",
            points=50,
            active=True,
            visible_home=False,
            is_fake=False,
        )
    )
    admin = await admin_headers(db_session, town, "08380")
    host = (await _by_code(client, capture_otp, "host@test.cat")).json()
    code = (
        await client.get(
            f"{API}/invites/me/link", params={"kind": "person"}, headers=_auth(host)
        )
    ).json()["public_code"]

    r = await _social(client, "google", cred("g-guest", "guest@test.cat"), invite_code=code)
    assert r.status_code == 200, r.text
    summary = (await client.get(f"{API}/invites/me/summary", headers=_auth(host))).json()
    assert summary["persons_registered"] == 1 and summary["points_earned"] == 50

    # A shop registered with that email is taken by whoever proves it is theirs.
    await client.post(
        f"{API}/shops",
        json={"name": "Forn", "contact_email": "forn@test.cat"},
        headers=admin,
    )
    owner = (await _social(client, "google", cred("g-forn", "forn@test.cat"))).json()
    assert "merchant" in owner["user"]["roles"] and owner["user"]["shop_id"]


# ── "Your email is missing" ───────────────────────────────────────────


async def test_without_a_trusted_email_the_person_confirms_one(
    client, capture_otp, db_session, networks
):
    await malgrat(db_session)
    await db_session.commit()

    # No email at all, or one the network does not vouch for: same answer.
    for credential in (cred("f-pere"), cred("f-pere", "pere@test.cat", verified=False)):
        r = await _social(client, "facebook", credential)
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "email_missing" and detail["link_token"]
    assert (await db_session.execute(select(User))).first() is None
    # The token is not a session.
    r = await client.get(
        f"{API}/users/me", headers={"Authorization": f"Bearer {detail['link_token']}"}
    )
    assert r.status_code == 401

    # They type an email and confirm it with the code: the account is born
    # with that email and with Facebook as its origin.
    r = await _by_code(client, capture_otp, "pere@test.cat", link_token=detail["link_token"])
    assert r.status_code == 200, r.text
    pere = r.json()["user"]
    assert await _doors(db_session, pere["id"]) == [("facebook", True), ("email_code", False)]
    # From then on Facebook alone is enough.
    r = await _social(client, "facebook", cred("f-pere"))
    assert r.status_code == 200 and r.json()["user"]["id"] == pere["id"]


async def test_facebook_never_opens_an_account_by_its_email_alone(
    client, capture_otp, db_session, networks
):
    await malgrat(db_session)
    await db_session.commit()
    marta = (await _by_code(client, capture_otp, "marta@test.cat")).json()["user"]

    # Someone registers Marta's email in a network that does not verify it.
    r = await _social(client, "facebook", cred("f-intruder", "marta@test.cat", verified=False))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "email_missing"
    token = r.json()["detail"]["link_token"]
    # Without the code sent to Marta's email there is no way in.
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": "marta@test.cat", "code": "000000", "link_token": token},
    )
    assert r.status_code == 400
    assert await _doors(db_session, marta["id"]) == [("email_code", True)]

    # Marta herself, with her code: Facebook is added to her account.
    r = await _social(client, "facebook", cred("f-marta"))
    r = await _by_code(
        client, capture_otp, "marta@test.cat", link_token=r.json()["detail"]["link_token"]
    )
    assert r.status_code == 200 and r.json()["user"]["id"] == marta["id"]
    assert await _doors(db_session, marta["id"]) == [
        ("email_code", True),
        ("facebook", False),
    ]


async def test_a_dead_link_costs_nothing(client, capture_otp, db_session, networks):
    await malgrat(db_session)
    await db_session.commit()
    body = {"email": "pere@test.cat", "postal_code": "08380"}
    await client.post(f"{API}/auth/request-otp", json=body)
    code = capture_otp()

    r = await client.post(
        f"{API}/auth/verify-otp", json={**body, "code": code, "link_token": "not-a-token"}
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "link_expired"
    # The code was not spent: they can still get in with it.
    r = await client.post(f"{API}/auth/verify-otp", json={**body, "code": code})
    assert r.status_code == 200, r.text


# ── Linking, and what is never moved ──────────────────────────────────


async def test_with_a_session_the_network_is_linked_to_that_account(
    client, capture_otp, db_session, networks
):
    await malgrat(db_session)
    await db_session.commit()
    marta = (await _by_code(client, capture_otp, "marta@test.cat")).json()
    pere = (await _by_code(client, capture_otp, "pere@test.cat")).json()

    # A Google with another email: linked because Marta is the one asking.
    r = await _social(client, "google", cred("g-marta", "m.puig@gmail.com"), headers=_auth(marta))
    assert r.status_code == 200 and r.json()["user"]["id"] == marta["user"]["id"]
    assert await _doors(db_session, marta["user"]["id"]) == [
        ("email_code", True),
        ("google", False),
    ]
    assert (await _social(client, "google", cred("g-marta"))).json()["user"]["id"] == (
        marta["user"]["id"]
    )

    # That Google already opens Marta's account: it is not moved to Pere's.
    r = await _social(client, "google", cred("g-marta", "m.puig@gmail.com"), headers=_auth(pere))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "identifier_taken"
    assert await _doors(db_session, pere["user"]["id"]) == [("email_code", True)]
    # Nor with a link token and Pere's own code.
    r = await _by_code(
        client, capture_otp, "pere@test.cat", link_token=create_link_token("google", "g-marta")
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "identifier_taken"


async def test_some_accounts_only_get_in_by_email(client, db_session, networks, monkeypatch):
    town = await malgrat(db_session)
    await admin_headers(db_session, town, "08380")  # admin-malgrat-de-mar@test.cat

    # Administrators: an administrator's account is not opened by a network.
    r = await _social(client, "google", cred("g-admin", "admin-malgrat-de-mar@test.cat"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "use_email"
    # Test and fixed-code accounts.
    for email in ("qa+xarxa@km0lab.com", "resident@km0lab.com", "malgrat@km0lab.com"):
        r = await _social(client, "google", cred("g-x", email))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "use_email", email
    assert (await db_session.execute(select(UserIdentity))).first() is None


async def test_a_full_pilot_is_full_for_networks_too(
    client, capture_otp, db_session, networks
):
    town = await malgrat(db_session)
    town.max_residents = 1
    await db_session.commit()
    marta = (await _by_code(client, capture_otp, "marta@test.cat")).json()

    r = await _social(client, "google", cred("g-pere", "pere@test.cat"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "pilot_full"
    assert (
        await db_session.execute(select(User).where(User.email == "pere@test.cat"))
    ).first() is None
    # Whoever already has an account is never stopped.
    r = await _social(client, "google", cred("g-marta", "marta@test.cat"))
    assert r.status_code == 200 and r.json()["user"]["id"] == marta["user"]["id"]

