"""QA territory: fixed-OTP signup, partition, seed and purge safety."""

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models import (
    PointsTransaction,
    QrScan,
    Redemption,
    Reward,
    Shop,
    Town,
    TownPostalCode,
    User,
)
from app.qa import (
    QA_FIXTURE_EMAILS,
    QA_POSTAL_CODE,
    QA_RESIDENT_EMAIL,
    is_qa_email,
    is_qa_postal_code,
)
from app.services.qa_purge import QaPurgeRefused, purge_qa_territory
from app.services.qa_territory import (
    QA_INVITE_PERSON_POINTS,
    QA_RESIDENT_START_POINTS,
    QA_SIGNUP_POINTS,
    QA_VISIT_POINTS,
    _stable_id,
    ensure_qa_territory,
)
from app.utils.slug import slugify

pytestmark = pytest.mark.asyncio

API = "/api/v1"
CODE = "123456"


@pytest.fixture(autouse=True)
def _staging(monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "staging")


@pytest.fixture
async def qa(db_session):
    await ensure_qa_territory(db_session)
    await db_session.commit()
    return db_session


async def _login(client, email, **extra):
    r = await client.post(
        f"{API}/auth/verify-otp", json={"email": email, "code": CODE, **extra}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


async def _count(db, model, *clauses):
    return await db.scalar(select(func.count()).select_from(model).where(*clauses))


async def _real_town(db, name="Vila Real", postal_code="08999"):
    town = Town(name=name, slug=slugify(name))
    db.add(town)
    await db.flush()
    db.add(TownPostalCode(postal_code=postal_code, town_id=town.id, is_primary=True))
    await db.flush()
    return town


# ── Naming rules ──────────────────────────────────────────────────────


async def test_qa_naming_rules():
    assert is_qa_email("qa+vecino@km0lab.com")
    assert is_qa_email("QA+Run-42.alta@km0lab.com")
    assert not is_qa_email("qa@km0lab.com")
    assert not is_qa_email("qa+x@gmail.com")
    assert not is_qa_email("resident@km0lab.com")
    assert not is_qa_email("someone+qa+x@km0lab.com")
    assert is_qa_postal_code("99999") and is_qa_postal_code("99990")
    assert not is_qa_postal_code("08380")
    assert not is_qa_postal_code("00000")
    assert not is_qa_postal_code("9999")


# ── Seed ──────────────────────────────────────────────────────────────


async def test_seed_is_idempotent_and_fake(qa):
    before = {
        m: await _count(qa, m) for m in (Town, Shop, Reward, User, PointsTransaction)
    }
    await ensure_qa_territory(qa)
    await qa.commit()
    after = {
        m: await _count(qa, m) for m in (Town, Shop, Reward, User, PointsTransaction)
    }
    assert before == after
    assert await _count(qa, Shop, Shop.is_fake.is_(False)) == 0
    assert await _count(qa, Reward, Reward.is_fake.is_(False)) == 0
    assert await _count(qa, User, User.is_fake.is_(False)) == 0
    resident = (
        await qa.execute(select(User).where(User.email == QA_RESIDENT_EMAIL))
    ).scalars().one()
    ledger = await qa.scalar(
        select(func.sum(PointsTransaction.points)).where(
            PointsTransaction.user_id == resident.id
        )
    )
    assert resident.points == QA_RESIDENT_START_POINTS == ledger


async def test_public_catalogs_serve_qa_partition(client, qa):
    for path in ("shops/public", "rewards/public", "actions/public"):
        r = await client.get(f"{API}/{path}", params={"postal_code": QA_POSTAL_CODE})
        assert r.status_code == 200, path
        assert len(r.json()) >= 3, path
    r = await client.get(f"{API}/towns/public", params={"postal_code": QA_POSTAL_CODE})
    assert r.status_code == 200
    assert r.json()["default_visit_points"] == QA_VISIT_POINTS


# ── Fixed-OTP signup ──────────────────────────────────────────────────


async def test_new_qa_resident_signs_up_without_mailbox(client, qa):
    email = "qa+run1-alta@km0lab.com"
    r = await client.post(f"{API}/auth/request-otp", json={"email": email})
    assert r.status_code == 200
    body, _ = await _login(client, email)
    assert body["user"]["postal_code"] == QA_POSTAL_CODE
    assert body["user"]["points"] == QA_SIGNUP_POINTS
    assert body["points_awarded"] == QA_SIGNUP_POINTS

    user = (await qa.execute(select(User).where(User.email == email))).scalars().one()
    assert user.is_fake is True
    assert await _count(
        qa,
        PointsTransaction,
        PointsTransaction.user_id == user.id,
        PointsTransaction.is_fake.is_(False),
    ) == 0

    # Logging in again neither duplicates the user nor the welcome points.
    again, _ = await _login(client, email)
    assert again["user"]["id"] == body["user"]["id"]
    assert again["user"]["points"] == QA_SIGNUP_POINTS


async def test_qa_account_rejects_wrong_code(client, qa):
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": "qa+run1-bad@km0lab.com", "code": "000000"},
    )
    assert r.status_code == 400
    assert await _count(qa, User, User.email == "qa+run1-bad@km0lab.com") == 0


async def test_qa_account_cannot_join_a_real_town(client, qa):
    await _real_town(qa)
    await qa.commit()
    email = "qa+run1-escape@km0lab.com"
    body, headers = await _login(client, email, postal_code="08999")
    assert body["user"]["postal_code"] == QA_POSTAL_CODE

    r = await client.patch(
        f"{API}/users/me", json={"postal_code": "08999"}, headers=headers
    )
    assert r.status_code == 400
    r = await client.get(f"{API}/users/me", headers=headers)
    assert r.json()["postal_code"] == QA_POSTAL_CODE


async def test_qa_accounts_disabled_in_production(client, qa, monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "production")
    email = "qa+run1-prod@km0lab.com"
    r = await client.post(f"{API}/auth/request-otp", json={"email": email})
    assert r.status_code == 403
    r = await client.post(
        f"{API}/auth/verify-otp", json={"email": email, "code": CODE}
    )
    assert r.status_code == 403
    assert await _count(qa, User, User.email == email) == 0


async def test_qa_signup_needs_seeded_territory(client):
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": "qa+run1-noseed@km0lab.com", "code": CODE},
    )
    assert r.status_code == 400
    assert "seed_qa" in r.json()["detail"]


async def test_real_signup_is_untouched(client, capture_otp, qa):
    """A normal resident still needs the emailed code and stays real."""
    email = "vecina@test.cat"
    await client.post(f"{API}/auth/request-otp", json={"email": email})
    r = await client.post(
        f"{API}/auth/verify-otp", json={"email": email, "code": CODE}
    )
    assert r.status_code == 400
    r = await client.post(
        f"{API}/auth/verify-otp", json={"email": email, "code": capture_otp()}
    )
    assert r.status_code == 200
    user = (await qa.execute(select(User).where(User.email == email))).scalars().one()
    assert user.is_fake is False


# ── Journeys the app relies on, inside the territory ─────────────────


async def test_qa_scan_redeem_and_invite(client, qa):
    inviter_body, inviter = await _login(client, "qa+run2-a@km0lab.com")

    # Scan: town points once, then cooldown; unknown QR is 404.
    r = await client.post(f"{API}/scans", json={"qr_code": "qa-shop-1"}, headers=inviter)
    assert r.status_code == 201, r.text
    assert r.json()["points"] == QA_VISIT_POINTS
    assert r.json()["balance"] == QA_SIGNUP_POINTS + QA_VISIT_POINTS
    r = await client.post(f"{API}/scans", json={"qr_code": "qa-shop-1"}, headers=inviter)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "qr_cooldown"
    r = await client.post(f"{API}/scans", json={"qr_code": "nope"}, headers=inviter)
    assert r.status_code == 404

    # Voucher: code issued. Product: no code. Both debit the ledger.
    r = await client.post(
        f"{API}/redemptions",
        json={"reward_id": _stable_id("reward-voucher")},
        headers=inviter,
    )
    assert r.status_code == 201, r.text
    assert r.json()["code"] and r.json()["status"] == "pending_use"
    r = await client.post(
        f"{API}/redemptions",
        json={"reward_id": _stable_id("reward-product")},
        headers=inviter,
    )
    assert r.status_code == 201, r.text
    assert r.json()["code"] is None and r.json()["status"] == "requested"
    r = await client.get(f"{API}/users/me", headers=inviter)
    assert r.json()["points"] == QA_SIGNUP_POINTS + QA_VISIT_POINTS - 50 - 30

    # Not enough points / no stock.
    r = await client.post(
        f"{API}/redemptions",
        json={"reward_id": _stable_id("reward-expensive")},
        headers=inviter,
    )
    assert r.status_code == 400 and "Insufficient" in r.json()["detail"]
    r = await client.post(
        f"{API}/redemptions",
        json={"reward_id": _stable_id("reward-soldout")},
        headers=inviter,
    )
    assert r.status_code == 400 and "stock" in r.json()["detail"]

    # Invitation end to end: a second new resident signs up with the code.
    r = await client.get(f"{API}/invites/me/link", params={"kind": "person"}, headers=inviter)
    assert r.status_code == 200, r.text
    code = r.json()["public_code"]
    before = (await client.get(f"{API}/users/me", headers=inviter)).json()["points"]
    await _login(client, "qa+run2-b@km0lab.com", invite_code=code)
    after = (await client.get(f"{API}/users/me", headers=inviter)).json()["points"]
    assert after - before == QA_INVITE_PERSON_POINTS

    assert await _count(qa, QrScan, QrScan.is_fake.is_(False)) == 0
    assert await _count(qa, Redemption, Redemption.is_fake.is_(False)) == 0
    assert await _count(
        qa, PointsTransaction, PointsTransaction.is_fake.is_(False)
    ) == 0


async def test_qa_business_signup_is_fake_and_activates(client, qa):
    email = "qa+run3-negoci@km0lab.com"
    _, owner = await _login(client, email)
    r = await client.post(
        f"{API}/shops/public-signup",
        json={
            "name": "[QA] Negoci de la prova",
            "tax_id": "B00000000",
            "categories": ["other"],
            "contact_email": email,
            "postal_code": QA_POSTAL_CODE,
        },
        headers=owner,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "review"
    shop = await qa.get(Shop, r.json()["shop_id"])
    assert shop.is_fake is True

    _, admin = await _login(client, "qa+admin@km0lab.com")
    r = await client.post(f"{API}/shops/{shop.id}/approve", headers=admin)
    assert r.status_code == 200, r.text
    body, _ = await _login(client, email)
    assert "merchant" in body["user"]["roles"]
    await qa.refresh(shop)
    assert shop.status == "active"


# ── Purge ─────────────────────────────────────────────────────────────


async def _activity(client):
    _, a = await _login(client, "qa+run9-a@km0lab.com")
    await client.post(f"{API}/scans", json={"qr_code": "qa-shop-2"}, headers=a)
    await client.post(
        f"{API}/redemptions",
        json={"reward_id": _stable_id("reward-voucher")},
        headers=a,
    )
    link = await client.get(f"{API}/invites/me/link", params={"kind": "person"}, headers=a)
    _, b = await _login(
        client, "qa+run9-b@km0lab.com", invite_code=link.json()["public_code"]
    )
    r = await client.post(
        f"{API}/shops/public-signup",
        json={
            "name": "[QA] Negoci efímer",
            "tax_id": "B11111119",
            "contact_email": "qa+run9-b@km0lab.com",
            "postal_code": QA_POSTAL_CODE,
        },
        headers=b,
    )
    assert r.status_code == 200, r.text


async def test_purge_dry_run_changes_nothing(client, qa):
    await _activity(client)
    users = await _count(qa, User)
    report = await purge_qa_territory(qa, dry_run=True)
    await qa.rollback()
    assert report.counts["users"] == 2
    assert report.counts["shops"] == 1
    assert report.counts["qr_scans"] == 1
    assert report.counts["redemptions"] == 1
    assert await _count(qa, User) == users


async def test_purge_runs_removes_only_what_tests_created(client, qa):
    # A real resident and town that must survive untouched.
    await _real_town(qa)
    await qa.commit()
    await client.post(f"{API}/auth/request-otp", json={"email": "real@test.cat"})
    from app.main import app

    code = app.state.last_otp["code"]
    real, _ = await _login_with(client, "real@test.cat", code, postal_code="08999")

    await _activity(client)
    report = await purge_qa_territory(qa, dry_run=False)
    await qa.commit()
    assert report.counts["users"] == 2

    emails = set((await qa.execute(select(User.email))).scalars().all())
    assert emails == set(QA_FIXTURE_EMAILS) | {"real@test.cat"}
    assert await _count(qa, QrScan) == 0
    assert await _count(qa, Redemption) == 0
    assert await _count(qa, Shop) == 3  # fixture shops only
    real_user = await qa.get(User, real["user"]["id"])
    assert real_user.points == 100 and real_user.is_fake is False
    # Fixture resident keeps balance == ledger.
    resident = (
        await qa.execute(select(User).where(User.email == QA_RESIDENT_EMAIL))
    ).scalars().one()
    assert resident.points == QA_RESIDENT_START_POINTS

    # Second purge finds nothing: it is repeatable.
    again = await purge_qa_territory(qa, dry_run=False)
    assert again.total == 0


async def _login_with(client, email, code, **extra):
    r = await client.post(
        f"{API}/auth/verify-otp", json={"email": email, "code": code, **extra}
    )
    assert r.status_code == 200, r.text
    return r.json(), {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_purge_keeps_recent_runs_when_asked(client, qa):
    await _activity(client)
    report = await purge_qa_territory(qa, older_than_minutes=120, dry_run=False)
    await qa.commit()
    assert report.counts["users"] == 0
    assert await _count(qa, User, User.email.like("qa+run9-%")) == 2


async def test_purge_undoes_reward_paid_to_a_kept_inviter(client, qa):
    _, fixture = await _login(client, QA_RESIDENT_EMAIL)
    link = await client.get(
        f"{API}/invites/me/link", params={"kind": "person"}, headers=fixture
    )
    await _login(
        client, "qa+run8-invited@km0lab.com", invite_code=link.json()["public_code"]
    )
    me = (await client.get(f"{API}/users/me", headers=fixture)).json()
    assert me["points"] == QA_RESIDENT_START_POINTS + QA_INVITE_PERSON_POINTS

    await purge_qa_territory(qa, dry_run=False)
    await qa.commit()
    resident = (
        await qa.execute(select(User).where(User.email == QA_RESIDENT_EMAIL))
    ).scalars().one()
    await qa.refresh(resident)
    ledger = await qa.scalar(
        select(func.sum(PointsTransaction.points)).where(
            PointsTransaction.user_id == resident.id
        )
    )
    assert resident.points == QA_RESIDENT_START_POINTS == ledger


async def test_purge_refuses_when_a_row_is_not_fake(client, qa):
    await _activity(client)
    user = (
        await qa.execute(select(User).where(User.email == "qa+run9-a@km0lab.com"))
    ).scalars().one()
    user.is_fake = False
    await qa.commit()
    with pytest.raises(QaPurgeRefused):
        await purge_qa_territory(qa, dry_run=False)
    await qa.rollback()
    assert await _count(qa, User, User.email.like("qa+run9-%")) == 2
    assert await _count(qa, QrScan) == 1


async def test_purge_refuses_a_town_that_is_not_qa(qa):
    town = Town(name="Poble de veritat", slug="poble-de-veritat")
    qa.add(town)
    await qa.flush()
    qa.add(TownPostalCode(postal_code="99991", town_id=town.id, is_primary=True))
    await qa.commit()
    with pytest.raises(QaPurgeRefused):
        await purge_qa_territory(qa, everything=True, dry_run=False)


async def test_purge_everything_then_reseed(client, qa):
    await _real_town(qa)
    await qa.commit()
    await _activity(client)
    report = await purge_qa_territory(qa, everything=True, dry_run=False)
    await qa.commit()
    assert report.counts["towns"] == 1
    assert await _count(qa, User) == 0
    assert await _count(qa, Shop) == 0
    assert await _count(qa, Reward) == 0
    assert await _count(qa, PointsTransaction) == 0
    assert await _count(qa, Town) == 1  # the real one
    assert await _count(qa, TownPostalCode) == 1

    await ensure_qa_territory(qa)
    await qa.commit()
    assert await _count(qa, User) == 3


async def test_purge_everything_refuses_outside_activity(client, qa):
    """A non-QA fake account with activity in the territory blocks a wipe."""
    outsider = User(
        email="resident@km0lab.com", slug="demo-res", is_fake=True, points=0
    )
    qa.add(outsider)
    await qa.flush()
    qa.add(
        QrScan(
            user_id=outsider.id,
            shop_id=_stable_id("shop-1"),
            points=QA_VISIT_POINTS,
            scan_date=__import__("datetime").date.today(),
            is_fake=True,
        )
    )
    await qa.commit()
    with pytest.raises(QaPurgeRefused):
        await purge_qa_territory(qa, everything=True, dry_run=False)


# ── HTTP gate ─────────────────────────────────────────────────────────


async def test_prepare_endpoint_is_closed_without_token(client, qa):
    r = await client.post(f"{API}/qa/prepare")
    assert r.status_code == 404


async def test_prepare_endpoint_requires_matching_token(client, qa, monkeypatch):
    monkeypatch.setattr(get_settings(), "qa_token", "s3cret-test-token")
    assert (await client.post(f"{API}/qa/prepare")).status_code == 401
    r = await client.post(f"{API}/qa/prepare", headers={"X-QA-Token": "nope"})
    assert r.status_code == 401

    await _activity(client)
    ok = {"X-QA-Token": "s3cret-test-token"}
    r = await client.post(
        f"{API}/qa/prepare", params={"dry_run": True, "older_than_minutes": 0}, headers=ok
    )
    assert r.status_code == 200
    assert r.json()["purge"]["counts"]["users"] == 2
    assert r.json()["fixture"] is None

    r = await client.post(
        f"{API}/qa/prepare", params={"older_than_minutes": 0}, headers=ok
    )
    assert r.status_code == 200, r.text
    assert r.json()["fixture"]["postal_code"] == QA_POSTAL_CODE
    assert await _count(qa, User) == 3


async def test_rate_limit_key_only_frees_the_robot(monkeypatch):
    from starlette.requests import Request

    from app.ratelimit import rate_limit_key

    def request(token=None):
        headers = [(b"x-qa-token", token.encode())] if token else []
        return Request(
            {"type": "http", "headers": headers, "client": ("203.0.113.7", 1)}
        )

    # No token configured: everyone is limited by IP, header or not.
    assert rate_limit_key(request("anything")) == "203.0.113.7"

    monkeypatch.setattr(get_settings(), "qa_token", "s3cret-test-token")
    assert rate_limit_key(request()) == "203.0.113.7"
    assert rate_limit_key(request("wrong")) == "203.0.113.7"
    first = rate_limit_key(request("s3cret-test-token"))
    second = rate_limit_key(request("s3cret-test-token"))
    assert first.startswith("qa-robot:") and first != second

    monkeypatch.setattr(get_settings(), "environment", "production")
    assert rate_limit_key(request("s3cret-test-token")) == "203.0.113.7"


async def test_prepare_endpoint_closed_in_production(client, qa, monkeypatch):
    monkeypatch.setattr(get_settings(), "qa_token", "s3cret-test-token")
    monkeypatch.setattr(get_settings(), "environment", "production")
    r = await client.post(
        f"{API}/qa/prepare", headers={"X-QA-Token": "s3cret-test-token"}
    )
    assert r.status_code == 404
