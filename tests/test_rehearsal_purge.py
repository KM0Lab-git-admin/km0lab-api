"""A rehearsal is removed from its municipality, and only that rehearsal."""

import pytest
from sqlalchemy import func, select

from app.models import Promotion, QrScan, Redemption, Reward, Shop, User
from app.services.rehearsal_purge import (
    NOTHING,
    RehearsalRefused,
    purge_rehearsal,
)
from tests._municipalities import API, admin_headers, single_town
from tests.test_invite_limit import _link, _signup

pytestmark = pytest.mark.asyncio

POSTAL = "17300"
EMAILS = [
    "a@ensayo.cat",
    "b@ensayo.cat",
    "c@ensayo.cat",
    "comercio@ensayo.cat",
]


async def _silence_mail(monkeypatch):
    async def fake(*_args, **_kwargs):
        return True

    monkeypatch.setattr("app.api.shops.send_shop_review_email", fake)


async def _rehearsal(client, db, capture_otp, monkeypatch):
    """Shop with an offer, A scans, B and C join from A's link, A redeems."""
    await _silence_mail(monkeypatch)
    town = await single_town(db, "Blanes", POSTAL)
    reward = Reward(
        town_id=town.id,
        name="Pa de pagès",
        type="product",
        points_required=40,
        stock=1,
        status="active",
    )
    db.add(reward)
    await db.commit()
    admin = await admin_headers(db, town, POSTAL)

    shop_user = await _signup(client, capture_otp, EMAILS[3], POSTAL)
    asked = await client.post(
        f"{API}/shops/public-signup",
        headers=shop_user["headers"],
        json={
            "name": "Forn Blanes",
            "tax_id": "B12345674",
            "contact_email": EMAILS[3],
            "postal_code": POSTAL,
            "phone": "937000000",
        },
    )
    assert asked.status_code == 200, asked.text
    shop_id = asked.json()["shop_id"]
    approved = await client.post(f"{API}/shops/{shop_id}/approve", headers=admin)
    assert approved.status_code == 200, approved.text
    db.add(
        Promotion(
            shop_id=shop_id,
            type="special_price",
            title="Pa del dia",
            label="oferta",
        )
    )
    await db.commit()
    shop = await db.get(Shop, shop_id)

    anna = await _signup(client, capture_otp, EMAILS[0], POSTAL)
    scanned = await client.post(
        f"{API}/scans", json={"qr_code": shop.qr_code}, headers=anna["headers"]
    )
    assert scanned.status_code == 201, scanned.text
    code = await _link(client, anna)
    await _signup(client, capture_otp, EMAILS[1], POSTAL, code)
    await _signup(client, capture_otp, EMAILS[2], POSTAL, code)
    redeemed = await client.post(
        f"{API}/redemptions",
        headers=anna["headers"],
        json={"reward_id": reward.id},
    )
    assert redeemed.status_code == 201, redeemed.text
    await db.refresh(reward)
    assert (reward.stock, reward.status) == (0, "sold_out")
    return town, reward


async def test_apply_removes_the_rehearsal_and_returns_the_unit(
    client, db_session, capture_otp, monkeypatch
):
    town, reward = await _rehearsal(client, db_session, capture_otp, monkeypatch)
    town.max_residents = 3
    await db_session.commit()

    preview = await purge_rehearsal(
        db_session, town="Blanes", emails=EMAILS, dry_run=True
    )
    await db_session.rollback()
    assert not preview.nothing
    assert preview.max_residents == 3
    assert preview.stock[0].after == 1
    assert await db_session.scalar(select(func.count()).select_from(User)) == 5

    done = await purge_rehearsal(
        db_session, town="Blanes", emails=EMAILS, dry_run=False
    )
    await db_session.commit()
    assert done.stock[0].status == "active"
    assert "Aforo actual de Blanes: 3" in done.lines()[-1]

    left = (await db_session.execute(select(User.email))).scalars().all()
    assert set(left) == {"admin-blanes@test.cat"}
    assert await db_session.scalar(select(func.count()).select_from(Shop)) == 0
    assert await db_session.scalar(select(func.count()).select_from(QrScan)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Redemption)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Promotion)) == 0
    fresh = await db_session.get(Reward, reward.id)
    assert (fresh.stock, fresh.status) == (1, "active")
    await db_session.refresh(town)
    assert town.max_residents == 3

    again = await purge_rehearsal(
        db_session, town="Blanes", emails=EMAILS, dry_run=False
    )
    assert again.nothing
    assert again.lines()[0] == NOTHING


async def test_an_outsider_scan_refuses_and_deletes_nothing(
    client, db_session, capture_otp, monkeypatch
):
    _town, _reward = await _rehearsal(client, db_session, capture_otp, monkeypatch)
    shop = (await db_session.execute(select(Shop))).scalars().one()
    outsider = await _signup(client, capture_otp, "fora@ensayo.cat", POSTAL)
    scanned = await client.post(
        f"{API}/scans", json={"qr_code": shop.qr_code}, headers=outsider["headers"]
    )
    assert scanned.status_code == 201, scanned.text

    with pytest.raises(RehearsalRefused, match="escaneo"):
        await purge_rehearsal(db_session, town="Blanes", emails=EMAILS, dry_run=False)
    assert await db_session.scalar(select(func.count()).select_from(Shop)) == 1
    assert await db_session.get(User, outsider["user"]["id"]) is not None


async def test_an_administrator_on_the_list_is_refused(
    client, db_session, capture_otp, monkeypatch
):
    await _rehearsal(client, db_session, capture_otp, monkeypatch)
    with pytest.raises(RehearsalRefused, match="administrador|vecino o comercio"):
        await purge_rehearsal(
            db_session,
            town="Blanes",
            emails=[*EMAILS, "admin-blanes@test.cat"],
            dry_run=False,
        )
    assert await db_session.scalar(select(func.count()).select_from(Shop)) == 1


async def test_an_account_from_another_municipality_is_refused(
    client, db_session, capture_otp, monkeypatch
):
    await _rehearsal(client, db_session, capture_otp, monkeypatch)
    await single_town(db_session, "Malgrat de Mar", "08380")
    await _signup(client, capture_otp, "anna@malgrat.cat", "08380")
    with pytest.raises(RehearsalRefused, match="no están en Blanes"):
        await purge_rehearsal(
            db_session,
            town="Blanes",
            emails=["anna@malgrat.cat"],
            dry_run=False,
        )
    still = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == "anna@malgrat.cat")
    )
    assert still == 1


async def test_an_unknown_town_or_an_empty_list_is_refused(db_session):
    with pytest.raises(RehearsalRefused, match="vacía"):
        await purge_rehearsal(db_session, town="Blanes", emails=[], dry_run=True)
    with pytest.raises(RehearsalRefused, match="población"):
        await purge_rehearsal(
            db_session, town="Ninguna", emails=["a@ensayo.cat"], dry_run=True
        )
