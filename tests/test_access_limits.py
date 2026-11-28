"""How many codes can be asked for: by connection, and to the same email.

The limit by connection is what a venue's shared Wi-Fi runs into on the
day of a presentation, so it is generous and can be raised from the
environment. What keeps one person from filling somebody else's inbox is
the cap of codes per hour to the same email, wherever the request comes
from.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app import email as email_module
from app.api import auth
from app.config import get_settings
from app.models import OtpCode
from app.ratelimit import limiter, wait_minutes
from tests._municipalities import API, malgrat

pytestmark = pytest.mark.asyncio


async def _ask(client, email: str, ip: str | None = None):
    return await client.post(
        f"{API}/auth/request-otp",
        json={"email": email, "postal_code": "08380"},
        headers={"X-Real-IP": ip} if ip else {},
    )


async def test_one_mailbox_gets_five_codes_an_hour_whoever_asks(
    client, capture_otp, db_session
):
    await malgrat(db_session)
    await db_session.commit()

    # From five different connections: the cap is on the mailbox.
    for n in range(5):
        r = await _ask(client, "marta@test.cat", ip=f"81.0.0.{n + 1}")
        assert r.status_code == 200, r.text
    last_code = capture_otp()

    r = await _ask(client, "marta@test.cat", ip="81.0.0.99")
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["code"] == "otp_email_limit"
    # It says when: the first of those five codes leaves the hour in ~60 min.
    assert 3500 < detail["retry_after_seconds"] <= 3600
    assert r.headers["Retry-After"] == str(detail["retry_after_seconds"])
    assert "60 minuts" in detail["message"]
    # Nothing was sent and no code was created.
    assert capture_otp() == last_code
    codes = (
        await db_session.execute(select(OtpCode).where(OtpCode.email == "marta@test.cat"))
    ).scalars().all()
    assert len(codes) == 5

    # Somebody else's mailbox is not affected...
    assert (await _ask(client, "pere@test.cat", ip="81.0.0.99")).status_code == 200
    # ...and Marta still gets in with a code she already has.
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": "marta@test.cat", "code": last_code, "postal_code": "08380"},
    )
    assert r.status_code == 200, r.text


async def test_the_hour_moves_on(client, db_session):
    await malgrat(db_session)
    await db_session.commit()
    for _ in range(5):
        assert (await _ask(client, "marta@test.cat")).status_code == 200
    assert (await _ask(client, "marta@test.cat")).status_code == 429

    # Forty minutes later the wait is the twenty that are left...
    for code in (await db_session.execute(select(OtpCode))).scalars().all():
        code.expires_at = code.expires_at - timedelta(minutes=40)
    await db_session.commit()
    r = await _ask(client, "marta@test.cat")
    assert r.status_code == 429
    assert 1100 < r.json()["detail"]["retry_after_seconds"] <= 1200
    assert "20 minuts" in r.json()["detail"]["message"]

    # ...and once the oldest code is an hour old, another one may go.
    row = (
        await db_session.execute(select(OtpCode).order_by(OtpCode.created_at).limit(1))
    ).scalars().first()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=51)
    await db_session.commit()
    assert (await _ask(client, "marta@test.cat")).status_code == 200


async def test_the_cap_by_email_can_be_changed_or_switched_off(
    client, db_session, monkeypatch
):
    await malgrat(db_session)
    await db_session.commit()
    monkeypatch.setattr(get_settings(), "otp_per_email_per_hour", 2)
    assert (await _ask(client, "marta@test.cat")).status_code == 200
    assert (await _ask(client, "marta@test.cat")).status_code == 200
    assert (await _ask(client, "marta@test.cat")).status_code == 429
    monkeypatch.setattr(get_settings(), "otp_per_email_per_hour", 0)
    assert (await _ask(client, "marta@test.cat")).status_code == 200


def test_the_limit_by_connection_comes_from_the_environment(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "otp_requests_per_hour", None)
    monkeypatch.setattr(settings, "otp_verifies_per_hour", None)

    # Nothing set: 30 codes and 60 entries an hour, in UAT and in production.
    for env in ("staging", "production"):
        monkeypatch.setattr(settings, "environment", env)
        assert auth._otp_request_limit() == "30/hour"
        assert auth._otp_verify_limit() == "60/hour"
    # Loose in local development.
    monkeypatch.setattr(settings, "environment", "development")
    assert auth._otp_request_limit() == "600/hour"

    # Raised for the day of a presentation, in any environment.
    monkeypatch.setattr(settings, "otp_requests_per_hour", 200)
    monkeypatch.setattr(settings, "otp_verifies_per_hour", 400)
    for env in ("development", "staging", "production"):
        monkeypatch.setattr(settings, "environment", env)
        assert auth._otp_request_limit() == "200/hour"
        assert auth._otp_verify_limit() == "400/hour"


async def test_the_limit_by_connection_says_when_to_come_back(
    client, db_session, monkeypatch
):
    await malgrat(db_session)
    await db_session.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "otp_requests_per_hour", 2)
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    try:
        venue = "81.0.0.50"  # everyone on the venue's Wi-Fi
        assert (await _ask(client, "anna@test.cat", ip=venue)).status_code == 200
        assert (await _ask(client, "pol@test.cat", ip=venue)).status_code == 200
        r = await _ask(client, "nuria@test.cat", ip=venue)
        assert r.status_code == 429
        detail = r.json()["detail"]
        assert detail["code"] == "rate_limited"
        assert 0 < detail["retry_after_seconds"] <= 3600
        assert r.headers["Retry-After"] == str(detail["retry_after_seconds"])
        assert "minut" in detail["message"]
        # Someone on their own mobile data is not held back by the venue.
        assert (await _ask(client, "nuria@test.cat", ip="90.1.2.3")).status_code == 200
    finally:
        limiter.reset()


def test_the_wait_is_told_in_whole_minutes():
    assert wait_minutes(1) == 1
    assert wait_minutes(60) == 1
    assert wait_minutes(61) == 2
    assert wait_minutes(3600) == 60


# ── When the email provider says no ───────────────────────────────────


@pytest.mark.parametrize(
    "status, body, level",
    [
        # The plan's quota is used up: nothing leaves until it renews.
        (429, '{"name":"daily_quota_exceeded","message":"You have reached your daily email sending quota."}', logging.CRITICAL),
        (429, '{"name":"monthly_quota_exceeded","message":"Monthly quota reached."}', logging.CRITICAL),
        # Too fast, or anything else: an ordinary error.
        (429, '{"name":"rate_limit_exceeded","message":"Too many requests."}', logging.ERROR),
        (422, '{"name":"validation_error","message":"Invalid `to` field."}', logging.ERROR),
    ],
)
def test_a_used_up_quota_is_told_apart_in_the_log(caplog, status, body, level):
    response = httpx.Response(
        status, text=body, request=httpx.Request("POST", email_module.RESEND_API_URL)
    )
    with caplog.at_level(logging.ERROR, logger="km0lab-api.email"):
        with pytest.raises(httpx.HTTPStatusError):
            email_module._raise_for_resend(response)
    (record,) = caplog.records
    assert record.levelno == level
    assert ("CUPO DE CORREO AGOTADO" in record.getMessage()) is (level == logging.CRITICAL)


async def test_a_refused_send_tells_the_neighbour_and_keeps_older_codes(
    client, capture_otp, db_session, monkeypatch
):
    await malgrat(db_session)
    await db_session.commit()
    assert (await _ask(client, "marta@test.cat")).status_code == 200
    good_code = capture_otp()

    async def no_quota(to, code, lang=None):
        response = httpx.Response(
            429,
            text='{"name":"daily_quota_exceeded"}',
            request=httpx.Request("POST", email_module.RESEND_API_URL),
        )
        email_module._raise_for_resend(response)

    monkeypatch.setattr("app.api.auth.send_otp_email", no_quota)
    r = await _ask(client, "marta@test.cat")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "otp_send_failed"
    # The code already in her inbox still works.
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": "marta@test.cat", "code": good_code, "postal_code": "08380"},
    )
    assert r.status_code == 200, r.text
