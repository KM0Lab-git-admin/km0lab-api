"""Sign in once, stay in (``app/services/sessions.py``).

The session renews itself with use, lasts a year without it, and can be
closed from the server.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.config import Settings, get_settings
from app.models import User
from app.roles import flags_from_roles
from app.services.sessions import (
    EXAMPLE_JWT_SECRET,
    check_signing_key,
    close_all_sessions,
)
from tests._municipalities import API, admin_headers, malgrat

pytestmark = pytest.mark.asyncio


async def _enter(client, capture_otp, email: str) -> dict:
    body = {"email": email, "postal_code": "08380"}
    r = await client.post(f"{API}/auth/request-otp", json=body)
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/auth/verify-otp", json={**body, "code": capture_otp()})
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _claims(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def _lasts(token: str) -> timedelta:
    return datetime.fromtimestamp(_claims(token)["exp"], timezone.utc) - datetime.now(
        timezone.utc
    )


def _old_token(user_id: str, *, issued_days_ago: int, valid_days_left: int, **extra) -> str:
    """A session token as it would look that long after signing in."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "roles": ["resident"],
            "role": "resident",
            "iat": now - timedelta(days=issued_days_ago),
            "exp": now + timedelta(days=valid_days_left),
            **extra,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


# ── It lasts, and it renews itself with use ───────────────────────────


async def test_a_session_lasts_a_year_from_its_last_use(client, capture_otp, db_session):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    marta = await _enter(client, capture_otp, "marta@test.cat")

    assert timedelta(days=364, hours=23) < _lasts(marta["access_token"]) <= timedelta(days=365)
    # An administrator's is shorter: a month without use.
    r = await client.post(f"{API}/auth/renew", headers=admin)
    assert r.status_code == 200, r.text
    assert timedelta(days=29, hours=23) < _lasts(r.json()["access_token"]) <= timedelta(days=30)


async def test_using_the_app_keeps_the_session_alive_for_ever(
    client, capture_otp, db_session
):
    await malgrat(db_session)
    await db_session.commit()
    marta = (await _enter(client, capture_otp, "marta@test.cat"))["user"]

    # Eleven months after signing in, with one month left: she opens the app.
    worn = _old_token(marta["id"], issued_days_ago=335, valid_days_left=30)
    r = await client.post(f"{API}/auth/renew", headers=_bearer(worn))
    assert r.status_code == 200, r.text
    fresh = r.json()["access_token"]
    assert r.json()["user"]["id"] == marta["id"]
    # A whole year again, without typing anything.
    assert _lasts(fresh) > timedelta(days=364, hours=23)
    assert (await client.get(f"{API}/users/me", headers=_bearer(fresh))).status_code == 200
    # If that answer had been lost on a bad connection, the token she held
    # is still good: nothing is spent by renewing.
    assert (await client.get(f"{API}/users/me", headers=_bearer(worn))).status_code == 200
    assert (await client.post(f"{API}/auth/renew", headers=_bearer(worn))).status_code == 200


async def test_a_year_without_using_it_and_she_signs_in_again(
    client, capture_otp, db_session
):
    await malgrat(db_session)
    await db_session.commit()
    marta = (await _enter(client, capture_otp, "marta@test.cat"))["user"]

    gone = _old_token(marta["id"], issued_days_ago=366, valid_days_left=-1)
    assert (await client.get(f"{API}/users/me", headers=_bearer(gone))).status_code == 401
    assert (await client.post(f"{API}/auth/renew", headers=_bearer(gone))).status_code == 401
    # Without a session there is nothing to renew.
    assert (await client.post(f"{API}/auth/renew")).status_code in (401, 403)


async def test_renewing_brings_the_account_as_it_is_now(client, capture_otp, db_session):
    town = await malgrat(db_session)
    admin = await admin_headers(db_session, town, "08380")
    forn = await _enter(client, capture_otp, "forn@test.cat")
    assert _claims(forn["access_token"])["shop_id"] is None

    # The administrator registers her shop; her next login would take it.
    r = await client.post(
        f"{API}/shops", json={"name": "Forn", "contact_email": "forn@test.cat"}, headers=admin
    )
    assert r.status_code == 201, r.text
    again = await _enter(client, capture_otp, "forn@test.cat")
    renewed = (
        await client.post(f"{API}/auth/renew", headers=_bearer(forn["access_token"]))
    ).json()
    assert _claims(renewed["access_token"])["shop_id"] == again["user"]["shop_id"]
    assert "merchant" in _claims(renewed["access_token"])["roles"]


# ── Closing it from the server ────────────────────────────────────────


async def test_closing_every_session_of_an_account(client, capture_otp, db_session):
    await malgrat(db_session)
    await db_session.commit()
    phone = await _enter(client, capture_otp, "marta@test.cat")
    laptop = await _enter(client, capture_otp, "marta@test.cat")
    pere = await _enter(client, capture_otp, "pere@test.cat")

    r = await client.post(f"{API}/auth/logout-all", headers=_bearer(laptop["access_token"]))
    assert r.status_code == 200, r.text

    # Every device is out, the one that asked included...
    for device in (phone, laptop):
        token = _bearer(device["access_token"])
        r = await client.get(f"{API}/users/me", headers=token)
        assert r.status_code == 401 and r.json()["detail"] == "Session closed"
        assert (await client.post(f"{API}/auth/renew", headers=token)).status_code == 401
        # ...and where a session is optional, it is a visitor's.
        r = await client.get(
            f"{API}/shops/for-me", params={"postal_code": "08380"}, headers=token
        )
        assert r.status_code != 401
    # Nobody else is touched.
    assert (
        await client.get(f"{API}/users/me", headers=_bearer(pere["access_token"]))
    ).status_code == 200

    # She signs in again, at once, and that session is good.
    back = await _enter(client, capture_otp, "marta@test.cat")
    assert back["user"]["id"] == phone["user"]["id"]
    assert (
        await client.get(f"{API}/users/me", headers=_bearer(back["access_token"]))
    ).status_code == 200
    assert _claims(back["access_token"])["ep"] == 1


async def test_a_lost_phone_is_closed_without_the_person(client, capture_otp, db_session):
    await malgrat(db_session)
    await db_session.commit()
    lost = await _enter(client, capture_otp, "marta@test.cat")

    # What scripts/close_sessions.py does.
    user = await db_session.get(User, lost["user"]["id"])
    close_all_sessions(user)
    await db_session.commit()

    assert (
        await client.get(f"{API}/users/me", headers=_bearer(lost["access_token"]))
    ).status_code == 401


async def test_sessions_from_before_keep_working(client, db_session):
    """Nobody is signed out by publishing this: a token issued by the API
    as it was (no counter in it) is good until its own date, and renews."""
    await malgrat(db_session)
    marta = User(
        email="marta@test.cat",
        slug="marta",
        postal_code="08380",
        points=0,
        **flags_from_roles(["resident"]),
    )
    db_session.add(marta)
    await db_session.commit()

    before = _old_token(marta.id, issued_days_ago=20, valid_days_left=10)
    assert "ep" not in _claims(before)
    assert (await client.get(f"{API}/users/me", headers=_bearer(before))).status_code == 200
    r = await client.post(f"{API}/auth/renew", headers=_bearer(before))
    assert r.status_code == 200 and _lasts(r.json()["access_token"]) > timedelta(days=364)

    # Closing her sessions closes that old one too.
    close_all_sessions(marta)
    await db_session.commit()
    assert (await client.get(f"{API}/users/me", headers=_bearer(before))).status_code == 401


# ── The key that signs them ───────────────────────────────────────────


def test_production_does_not_start_on_the_example_key(caplog):
    def settings(environment: str, secret: str) -> Settings:
        return Settings(environment=environment, jwt_secret=secret)

    # With its own key, every environment starts.
    for env in ("development", "staging", "production"):
        check_signing_key(settings(env, "a-long-random-key-of-this-environment"))
    # Local development runs on the example.
    check_signing_key(settings("development", EXAMPLE_JWT_SECRET))

    # Where real people sign in, the example key forges anybody's session.
    for env in ("production", "prod", "anything-else"):
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            check_signing_key(settings(env, EXAMPLE_JWT_SECRET))
    # UAT starts, and says so as loudly as a log can.
    with caplog.at_level(logging.CRITICAL, logger="km0lab-api.sessions"):
        check_signing_key(settings("staging", EXAMPLE_JWT_SECRET))
    assert "JWT_SECRET" in caplog.text
