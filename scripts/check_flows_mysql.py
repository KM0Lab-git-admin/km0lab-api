"""End-to-end check of the points flows against a real MySQL.

    python -m scripts.check_flows_mysql

The unit tests run on SQLite, which neither enforces foreign keys nor
locks rows. This script covers what they cannot:

1. Seed the QA territory twice (idempotent).
2. Sign up, scan, redeem and invite through the HTTP API (in-process).
3. Fire the same scan and the same redemption concurrently: one scan must
   win, the balance must match the ledger and nothing may answer 500.
4. Purge what was created, then the whole territory, and seed it again.
5. Real (non-fake) data must be exactly as it was.

It only writes inside the QA territory (``app/qa.py``) and refuses to run
unless the database is local: it is meant for a developer machine or CI.
"""

from __future__ import annotations

import asyncio
import sys

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal, engine
from app.demo import DEMO_CODE
from app.main import app
from app.models import PointsTransaction, QrScan, Redemption, Shop, User
from app.qa import QA_ADMIN_EMAIL, QA_POSTAL_CODE, QA_RESIDENT_EMAIL
from app.ratelimit import limiter
from app.services.qa_purge import purge_qa_territory
from app.services.qa_territory import (
    QA_INVITE_PERSON_POINTS,
    QA_RESIDENT_START_POINTS,
    QA_SIGNUP_POINTS,
    QA_VISIT_POINTS,
    _stable_id,
    ensure_qa_territory,
)

API = "/api/v1"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "mysql"}
PARALLEL = 6


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


async def _login(client: AsyncClient, email: str, **extra) -> tuple[dict, dict]:
    r = await client.post(
        f"{API}/auth/verify-otp",
        json={"email": email, "code": DEMO_CODE, **extra},
    )
    if r.status_code != 200:
        raise AssertionError(f"login {email}: {r.status_code} {r.text}")
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


async def _real_data() -> dict[str, int]:
    async with SessionLocal() as db:

        async def n(model) -> int:
            return int(
                await db.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.is_fake.is_(False))
                )
                or 0
            )

        return {
            "users": await n(User),
            "shops": await n(Shop),
            "points_transactions": await n(PointsTransaction),
            "qr_scans": await n(QrScan),
            "redemptions": await n(Redemption),
        }


async def _balance_and_ledger(user_id: str) -> tuple[int, int]:
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        ledger = await db.scalar(
            select(func.sum(PointsTransaction.points)).where(
                PointsTransaction.user_id == user_id
            )
        )
        return user.points, int(ledger or 0)


async def main() -> None:
    settings = get_settings()
    env = settings.environment.lower().strip()
    if settings.db_host not in LOCAL_HOSTS or env == "production":
        raise SystemExit(
            f"Refusing: this check only runs on a local database "
            f"(host={settings.db_host!r}, environment={env!r})."
        )
    limiter.enabled = False
    before = await _real_data()

    print("1. Seed")
    async with SessionLocal() as db:
        await purge_qa_territory(db, dry_run=False)
        first = await ensure_qa_territory(db)
        await db.commit()
        second = await ensure_qa_territory(db)
        await db.commit()
    _check(first == second, "seeding twice gives the same fixture")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        print("2. Flows")
        r = await c.get(f"{API}/shops/public", params={"postal_code": QA_POSTAL_CODE})
        _check(r.status_code == 200 and len(r.json()) == 3, "public catalog serves the QA shops")

        a, user_a = await _login(c, "qa+check-a@km0lab.com")
        _check(user_a["points"] == QA_SIGNUP_POINTS, "new resident gets the welcome points")
        r = await c.post(f"{API}/scans", json={"qr_code": "qa-shop-2"}, headers=a)
        _check(r.status_code == 201 and r.json()["points"] == QA_VISIT_POINTS, "scan awards the town points")
        r = await c.post(f"{API}/scans", json={"qr_code": "qa-shop-2"}, headers=a)
        _check(r.status_code == 409, "second scan of the same shop is refused")
        r = await c.post(f"{API}/redemptions", json={"reward_id": _stable_id("reward-voucher")}, headers=a)
        _check(r.status_code == 201 and bool(r.json()["code"]), "voucher redemption issues a code")
        r = await c.post(f"{API}/redemptions", json={"reward_id": _stable_id("reward-product")}, headers=a)
        _check(r.status_code == 201 and r.json()["code"] is None, "product redemption has no code")

        link = await c.get(f"{API}/invites/me/link", params={"kind": "person"}, headers=a)
        await _login(c, "qa+check-b@km0lab.com", invite_code=link.json()["public_code"])
        me = (await c.get(f"{API}/users/me", headers=a)).json()
        expected = QA_SIGNUP_POINTS + QA_VISIT_POINTS - 50 - 30 + QA_INVITE_PERSON_POINTS
        _check(me["points"] == expected, "inviter is paid when the invitee signs up")

        fixture, _ = await _login(c, QA_RESIDENT_EMAIL)
        flink = await c.get(f"{API}/invites/me/link", params={"kind": "person"}, headers=fixture)
        await _login(c, "qa+check-c@km0lab.com", invite_code=flink.json()["public_code"])

        applicant, _ = await _login(c, "qa+check-negoci@km0lab.com")
        r = await c.post(
            f"{API}/shops/public-signup",
            json={
                "name": "[QA] Negoci de comprovació",
                "tax_id": "B22222228",
                "contact_email": "qa+check-negoci@km0lab.com",
                "postal_code": QA_POSTAL_CODE,
            },
            headers=applicant,
        )
        _check(
            r.status_code == 200 and r.json()["status"] == "review",
            "business signup is held for validation",
        )
        _, waiting = await _login(c, "qa+check-negoci@km0lab.com")
        _check("merchant" not in waiting["roles"], "no shop before it is approved")
        qa_admin, _ = await _login(c, QA_ADMIN_EMAIL)
        r = await c.post(f"{API}/shops/{r.json()['shop_id']}/approve", headers=qa_admin)
        _check(r.status_code == 200, "the administrator approves it")
        _, owner = await _login(c, "qa+check-negoci@km0lab.com")
        _check("merchant" in owner["roles"], "business owner is merchant once approved")

        print(f"3. Concurrency ({PARALLEL} at once)")
        racer, racer_user = await _login(c, "qa+check-race@km0lab.com")
        scans = await asyncio.gather(
            *[
                c.post(f"{API}/scans", json={"qr_code": "qa-shop-3"}, headers=racer)
                for _ in range(PARALLEL)
            ]
        )
        codes = sorted(x.status_code for x in scans)
        _check(codes == [201] + [409] * (PARALLEL - 1), f"one scan wins, the rest are refused {codes}")
        # 200 welcome + 20 scan = 220: two redemptions of 80 fit, no more.
        reds = await asyncio.gather(
            *[
                c.post(f"{API}/redemptions", json={"reward_id": _stable_id("reward-balance")}, headers=racer)
                for _ in range(PARALLEL)
            ]
        )
        codes = sorted(x.status_code for x in reds)
        _check(codes == [201, 201] + [400] * (PARALLEL - 2), f"no overspend and no server error {codes}")
        balance, ledger = await _balance_and_ledger(racer_user["id"])
        _check(balance == ledger == 60, f"balance equals ledger ({balance} / {ledger})")

    print("4. Purge")
    async with SessionLocal() as db:
        kept = await purge_qa_territory(db, older_than_minutes=120, dry_run=False)
        await db.commit()
        _check(kept.counts["users"] == 0, "recent runs are left alone when asked")
        preview = await purge_qa_territory(db, dry_run=True)
        await db.rollback()
        done = await purge_qa_territory(db, dry_run=False)
        await db.commit()
        _check(preview.counts == done.counts, "dry run reports exactly what is deleted")
        _check(done.counts["users"] == 5 and done.counts["shops"] == 1, "run data is removed")
        resident = (
            await db.execute(select(User).where(User.email == QA_RESIDENT_EMAIL))
        ).scalars().one()
        _check(resident.points == QA_RESIDENT_START_POINTS, "fixture resident balance is restored")
        wiped = await purge_qa_territory(db, everything=True, dry_run=False)
        await db.commit()
        _check(wiped.counts["towns"] == 1, "the whole territory can be wiped")
        await ensure_qa_territory(db)
        await db.commit()

    print("5. Real data")
    after = await _real_data()
    _check(after == before, f"real data untouched {after}")
    print("PASA")


async def _run() -> int:
    try:
        await main()
        return 0
    except AssertionError as exc:
        print(f"  FAIL  {exc}")
        print("NO PASA")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_run()))
