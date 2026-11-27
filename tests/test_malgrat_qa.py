"""Malgrat QA accounts: 123456 without landing on the Demo fake partition."""

from __future__ import annotations

import pytest

from app.demo import ADMIN_MALGRAT_EMAIL, DEMO_CODE, MALGRAT_CP
from app.models import Town, TownPostalCode
from app.services.malgrat_qa import ensure_malgrat_qa_accounts

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _enable_fixed_otp(monkeypatch):
    monkeypatch.setattr("app.api.auth.demo_enabled", lambda: True)


async def _malgrat(db_session):
    town = Town(
        name="Malgrat de Mar",
        slug="malgrat-de-mar-qa",
        entity_name="Ajuntament de Malgrat de Mar",
        entity_type="city_council",
        contact_email=ADMIN_MALGRAT_EMAIL,
        manager_name="Admin Malgrat",
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(
            postal_code=MALGRAT_CP, town_id=town.id, is_primary=True
        )
    )
    await db_session.commit()
    return town


async def test_malgrat_admin_fixed_otp_is_real_partition(client, db_session):
    await _malgrat(db_session)
    await ensure_malgrat_qa_accounts(db_session)
    await db_session.commit()

    r = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": ADMIN_MALGRAT_EMAIL, "code": DEMO_CODE},
    )
    assert r.status_code == 200, r.text
    body = r.json()["user"]
    assert body["email"] == ADMIN_MALGRAT_EMAIL
    assert body["is_fake"] is False
    assert "admin" in body["roles"]
    assert body["postal_code"] == MALGRAT_CP


async def test_malgrat_qa_wrong_code_rejected(client, db_session):
    await _malgrat(db_session)
    await ensure_malgrat_qa_accounts(db_session)
    await db_session.commit()

    r = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": ADMIN_MALGRAT_EMAIL, "code": "000000"},
    )
    assert r.status_code == 400


async def test_malgrat_qa_missing_seed(client):
    r = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": ADMIN_MALGRAT_EMAIL, "code": DEMO_CODE},
    )
    assert r.status_code == 400
