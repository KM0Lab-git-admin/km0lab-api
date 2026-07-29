"""Signup + birthday grants from point_actions catalog."""

from datetime import date

import pytest

from app.models import PointAction, Town, TownPostalCode
from app.services.action_grants import is_birthday_today
from app.utils.slug import slugify


async def _create_town(db_session, name="Malgrat", postal_code="08390"):
    town = Town(
        name=name,
        slug=slugify(name),
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{slugify(name)}.cat",
        manager_name="Admin",
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(
            postal_code=postal_code, town_id=town.id, is_primary=True
        )
    )
    await db_session.flush()
    return town, postal_code


@pytest.mark.asyncio
async def test_signup_uses_active_signup_action(client, capture_otp, db_session):
    town, _ = await _create_town(db_session, "SignupTown", "08401")
    db_session.add(
        PointAction(
            town_id=town.id,
            type="signup",
            name="Benvinguda custom",
            description="Custom welcome",
            points=250,
            active=True,
            is_fake=False,
        )
    )
    await db_session.commit()

    email = "signup-action@malgrat.cat"
    await client.post("/api/v1/auth/request-otp", json={"email": email})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # Without town, newest signup action (250) is used instead of settings 100.
    assert data["user"]["points"] == 250
    assert data["points_awarded"] == 250
    assert data["points_award_message"] == "Benvinguda custom"


@pytest.mark.asyncio
async def test_claim_birthday_once_per_year(client, capture_otp, db_session):
    town, cp = await _create_town(db_session, "BdayTown", "08402")
    db_session.add(
        PointAction(
            town_id=town.id,
            type="birthday",
            name="Felicitat",
            description="Aniversari",
            points=500,
            active=True,
            is_fake=False,
        )
    )
    await db_session.commit()

    email = "bday-claim@malgrat.cat"
    await client.post("/api/v1/auth/request-otp", json={"email": email})
    code = capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": email, "code": code}
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    today = date.today()
    r = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"birth_date": today.isoformat(), "postal_code": cp},
    )
    assert r.status_code == 200, r.text
    assert r.json()["birth_date"] == today.isoformat()

    r = await client.post("/api/v1/points/claim-birthday", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["awarded"] is True
    assert body["points"] == 500
    assert body["message"] == "Felicitat"

    r = await client.post("/api/v1/points/claim-birthday", headers=headers)
    assert r.status_code == 200
    assert r.json()["awarded"] is False
    assert r.json()["points"] == 0


def test_is_birthday_today_leap():
    assert is_birthday_today(date(2000, 2, 29), date(2023, 2, 28)) is True
    assert is_birthday_today(date(2000, 2, 29), date(2024, 2, 29)) is True
    assert is_birthday_today(date(2000, 2, 29), date(2023, 3, 1)) is False
