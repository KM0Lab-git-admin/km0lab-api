"""A voucher is money: only its town, one use, and a cancel gives it back."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    PointsTransaction,
    Redemption,
    Reward,
    Shop,
    Town,
    TownPostalCode,
    User,
)
from app.roles import flags_from_roles
from app.security import create_access_token
from app.utils.slug import slugify
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _town(db, name: str, postal: str, *, expiry_months: int | None = None):
    town = Town(
        name=name,
        slug=slugify(name),
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{postal}.cat",
        manager_name="Admin",
        expiry_months=expiry_months,
    )
    db.add(town)
    await db.flush()
    db.add(
        TownPostalCode(postal_code=postal, town_id=town.id, is_primary=True)
    )
    await db.flush()
    return town, postal


async def _resident(client, capture_otp, email: str, postal: str) -> dict:
    await client.post("/api/v1/auth/request-otp", json={"email": email})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await client.patch(
        "/api/v1/users/me", headers=headers, json={"postal_code": postal}
    )
    return headers


def _token(user: User, roles: list[str], town_id: str) -> dict:
    return {
        "Authorization": (
            "Bearer "
            + create_access_token(user.id, roles=roles, town_id=town_id)
        )
    }


async def test_other_town_looks_like_a_missing_code(client, db_session, capture_otp):
    town_a, cp_a = await _town(db_session, "Blanes", "17300")
    town_b, cp_b = await _town(db_session, "Pineda", "08397")
    reward = Reward(
        town_id=town_a.id,
        name="Val",
        description="d",
        type="discount",
        points_required=40,
        value="5€",
        status="active",
        stock=2,
    )
    shop_b = Shop(
        town_id=town_b.id,
        name="Botiga de Pineda",
        categories=[],
        contact_email="pineda@test.cat",
        visit_points=10,
        status="active",
        qr_code="PINEDA",
    )
    db_session.add_all([reward, shop_b])
    await db_session.flush()
    merchant = User(
        email="merchant-pineda@test.cat",
        slug="merchant-pineda",
        postal_code=cp_b,
        shop_id=shop_b.id,
        points=0,
        **flags_from_roles(["merchant", "resident"]),
    )
    db_session.add(merchant)
    await db_session.commit()

    headers = await _resident(client, capture_otp, "vei-blanes@test.cat", cp_a)
    created = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id, "amount": "5€"},
    )
    assert created.status_code == 201, created.text
    code = created.json()["code"]

    other = await client.post(
        "/api/v1/redemptions/validate",
        headers=_token(merchant, ["merchant", "resident"], town_b.id),
        json={"code": code},
    )
    assert other.status_code == 404
    assert other.json()["detail"] == "Voucher not found"
    still = await client.get("/api/v1/redemptions", headers=headers)
    assert still.json()[0]["status"] == "pending_use"


async def test_ten_misses_then_the_shop_has_to_wait(client, db_session, capture_otp):
    town, cp = await _town(db_session, "Malgrat de Mar", "08380")
    shop = Shop(
        town_id=town.id,
        name="Fleca",
        categories=[],
        contact_email="fleca@test.cat",
        visit_points=10,
        status="active",
        qr_code="FLECA",
    )
    reward = Reward(
        town_id=town.id,
        name="Val",
        description="d",
        type="discount",
        points_required=40,
        value="5€",
        status="active",
    )
    db_session.add_all([shop, reward])
    await db_session.flush()
    merchant = User(
        email="fleca-owner@test.cat",
        slug="fleca-owner",
        postal_code=cp,
        shop_id=shop.id,
        points=100,
        **flags_from_roles(["merchant", "resident"]),
    )
    db_session.add(merchant)
    await db_session.commit()
    headers = _token(merchant, ["merchant", "resident"], town.id)

    for n in range(9):
        missed = await client.post(
            "/api/v1/redemptions/validate",
            headers=headers,
            json={"code": f"{n:05d}"},
        )
        assert missed.status_code == 404

    own = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id, "amount": "5€"},
    )
    assert own.status_code == 201, own.text
    hit = await client.post(
        "/api/v1/redemptions/validate",
        headers=headers,
        json={"code": own.json()["code"]},
    )
    assert hit.status_code == 200, hit.text
    body = hit.json()
    assert body["validated_by_user_id"] == merchant.id
    assert body["self_validated"] is True
    assert body["used_at"]
    assert body["shop_id"] == shop.id

    tenth = await client.post(
        "/api/v1/redemptions/validate",
        headers=headers,
        json={"code": "99999"},
    )
    assert tenth.status_code == 404
    blocked = await client.post(
        "/api/v1/redemptions/validate",
        headers=headers,
        json={"code": "88888"},
    )
    assert blocked.status_code == 429
    detail = blocked.json()["detail"]
    assert detail["code"] == "too_many_attempts"
    assert detail["retry_after_seconds"] >= 1

    admin = User(
        email="admin-malgrat@test.cat",
        slug="admin-malgrat",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()
    debts = await client.get(
        "/api/v1/payments/debts",
        headers=_token(admin, ["admin", "resident"], town.id),
    )
    assert debts.status_code == 200, debts.text
    row = next(item for item in debts.json() if item["shop_id"] == shop.id)
    assert row["self_validated_count"] == 1
    assert row["pending_count"] == 1


async def test_cancel_returns_points_and_stock(client, db_session, capture_otp):
    town, cp = await _town(db_session, "Tordera", "08490")
    reward = Reward(
        town_id=town.id,
        name="Val",
        description="d",
        type="discount",
        points_required=40,
        value="5€",
        status="active",
        stock=1,
    )
    db_session.add(reward)
    await db_session.flush()
    admin = User(
        email="admin-tordera@test.cat",
        slug="admin-tordera",
        postal_code=cp,
        points=0,
        **flags_from_roles(["admin", "resident"]),
    )
    db_session.add(admin)
    await db_session.commit()
    headers = await _resident(client, capture_otp, "vei-tordera@test.cat", cp)
    created = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": reward.id},
    )
    assert created.status_code == 201, created.text
    redemption_id = created.json()["id"]
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.json()["points"] == 60

    admin_headers = _token(admin, ["admin", "resident"], town.id)
    cancelled = await client.patch(
        f"/api/v1/redemptions/{redemption_id}/status",
        headers=admin_headers,
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.json()["points"] == 100

    await db_session.refresh(reward)
    assert (reward.stock, reward.status) == (1, "active")
    user_id = me.json()["id"]
    refunds = (
        await db_session.execute(
            select(PointsTransaction).where(
                PointsTransaction.user_id == user_id,
                PointsTransaction.type == "refund",
            )
        )
    ).scalars().all()
    assert len(refunds) == 1
    assert refunds[0].points == 40
    assert refunds[0].ref_id == redemption_id

    again = await client.patch(
        f"/api/v1/redemptions/{redemption_id}/status",
        headers=admin_headers,
        json={"status": "cancelled"},
    )
    assert again.status_code == 409

    used_reward = Reward(
        town_id=town.id,
        name="Altre",
        description="d",
        type="discount",
        points_required=40,
        value="5€",
        status="active",
    )
    shop = Shop(
        town_id=town.id,
        name="Botiga",
        categories=[],
        contact_email="botiga@test.cat",
        visit_points=10,
        status="active",
        qr_code="TORDERA",
    )
    db_session.add_all([used_reward, shop])
    await db_session.flush()
    merchant = User(
        email="merchant-tordera@test.cat",
        slug="merchant-tordera",
        postal_code=cp,
        shop_id=shop.id,
        points=0,
        **flags_from_roles(["merchant", "resident"]),
    )
    db_session.add(merchant)
    await db_session.commit()
    second = await client.post(
        "/api/v1/redemptions",
        headers=headers,
        json={"reward_id": used_reward.id},
    )
    assert second.status_code == 201, second.text
    used = await client.post(
        "/api/v1/redemptions/validate",
        headers=_token(merchant, ["merchant", "resident"], town.id),
        json={"code": second.json()["code"]},
    )
    assert used.status_code == 200, used.text
    refused = await client.patch(
        f"/api/v1/redemptions/{second.json()['id']}/status",
        headers=admin_headers,
        json={"status": "cancelled"},
    )
    assert refused.status_code == 409


async def test_expiry_comes_from_the_town(client, db_session, capture_otp):
    open_town, open_cp = await _town(db_session, "Hostalric", "17450")
    closed, closed_cp = await _town(db_session, "Riells", "17421", expiry_months=1)
    open_reward = Reward(
        town_id=open_town.id,
        name="Obert",
        description="d",
        type="discount",
        points_required=40,
        value="5€",
        status="active",
    )
    closed_reward = Reward(
        town_id=closed.id,
        name="Tancat",
        description="d",
        type="discount",
        points_required=40,
        value="5€",
        status="active",
    )
    shop = Shop(
        town_id=closed.id,
        name="Botiga de Riells",
        categories=[],
        contact_email="riells@test.cat",
        visit_points=10,
        status="active",
        qr_code="RIELLS",
    )
    db_session.add_all([open_reward, closed_reward, shop])
    await db_session.flush()
    merchant = User(
        email="merchant-riells@test.cat",
        slug="merchant-riells",
        postal_code=closed_cp,
        shop_id=shop.id,
        points=0,
        **flags_from_roles(["merchant", "resident"]),
    )
    db_session.add(merchant)
    await db_session.commit()

    open_headers = await _resident(client, capture_otp, "vei-hostalric@test.cat", open_cp)
    open_voucher = await client.post(
        "/api/v1/redemptions",
        headers=open_headers,
        json={"reward_id": open_reward.id},
    )
    assert open_voucher.status_code == 201, open_voucher.text
    assert open_voucher.json()["expires_at"] is None

    closed_headers = await _resident(client, capture_otp, "vei-riells@test.cat", closed_cp)
    closed_voucher = await client.post(
        "/api/v1/redemptions",
        headers=closed_headers,
        json={"reward_id": closed_reward.id},
    )
    assert closed_voucher.status_code == 201, closed_voucher.text
    assert closed_voucher.json()["expires_at"] is not None

    row = await db_session.get(Redemption, closed_voucher.json()["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()
    refused = await client.post(
        "/api/v1/redemptions/validate",
        headers=_token(merchant, ["merchant", "resident"], closed.id),
        json={"code": closed_voucher.json()["code"]},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "expired"
