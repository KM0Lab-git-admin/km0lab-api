"""Signup + birthday grants from point_actions catalog."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.config import get_settings
from app.models import PointAction, Town, TownPostalCode, User
from app.services.action_grants import (
    BIRTHDAY_MIN_ACCOUNT_AGE_DAYS,
    is_birthday_today,
)
from app.services.invitations import KIND_PERSON, snapshot_reward_points
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


async def _age_account(db_session, email: str, *, days: int) -> None:
    await db_session.execute(
        update(User)
        .where(User.email == email)
        .values(created_at=datetime.utcnow() - timedelta(days=days))
    )
    await db_session.commit()


async def _signup(client, capture_otp, email: str, postal_code: str) -> dict:
    """Alta de un vecino de ese código postal; devuelve cabeceras y usuario."""
    body = {"email": email, "postal_code": postal_code}
    await client.post("/api/v1/auth/request-otp", json=body)
    r = await client.post(
        "/api/v1/auth/verify-otp", json={**body, "code": capture_otp()}
    )
    assert r.status_code == 200, r.text
    return {
        "headers": {"Authorization": f"Bearer {r.json()['access_token']}"},
        "user": r.json()["user"],
    }


def _action(town, type_: str, *, points: int, active: bool) -> PointAction:
    return PointAction(
        town_id=town.id,
        type=type_,
        name=type_,
        description=type_,
        points=points,
        active=active,
        is_fake=False,
    )


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
    await _age_account(db_session, email, days=BIRTHDAY_MIN_ACCOUNT_AGE_DAYS + 1)

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


# ── Piloto: lo que el administrador apaga no paga; el cumpleaños no se
#    cobra el día del alta con una fecha elegida a propósito ────────────


@pytest.mark.asyncio
async def test_signup_action_switched_off_pays_nothing(
    client, capture_otp, db_session
):
    """Desactivar el alta daba los 100 puntos por defecto: ahora da cero."""
    town, cp = await _create_town(db_session, "SenseAlta", "08410")
    db_session.add(_action(town, "signup", points=100, active=False))
    await db_session.commit()

    out = await _signup(client, capture_otp, "apagada@test.cat", cp)

    assert out["user"]["points"] == 0


@pytest.mark.asyncio
async def test_signup_without_any_action_keeps_the_default(
    client, capture_otp, db_session
):
    """Un municipio que nunca tuvo la acción sigue con el valor por defecto."""
    _, cp = await _create_town(db_session, "SenseAccions", "08411")
    await db_session.commit()

    out = await _signup(client, capture_otp, "defecte@test.cat", cp)

    assert out["user"]["points"] == get_settings().welcome_points > 0


@pytest.mark.asyncio
async def test_invite_reward_switched_off_pays_nothing(db_session):
    town, cp = await _create_town(db_session, "SenseInvit", "08412")
    inviter = User(email="convida@test.cat", slug="convida", postal_code=cp)
    db_session.add(inviter)
    await db_session.commit()

    # Sin acción en el catálogo: el valor por defecto.
    points = await snapshot_reward_points(
        db_session, kind=KIND_PERSON, town_id=town.id, user=inviter
    )
    assert points == get_settings().invite_person_points > 0

    # Con la acción apagada por el administrador: nada.
    db_session.add(_action(town, "invite_person", points=100, active=False))
    await db_session.commit()
    points = await snapshot_reward_points(
        db_session, kind=KIND_PERSON, town_id=town.id, user=inviter
    )
    assert points == 0


@pytest.mark.asyncio
async def test_new_account_cannot_collect_a_birthday_made_up_today(
    client, capture_otp, db_session
):
    town, cp = await _create_town(db_session, "AniversariNou", "08413")
    db_session.add(_action(town, "birthday", points=500, active=True))
    db_session.add(_action(town, "signup", points=100, active=True))
    await db_session.commit()
    email = "avui@test.cat"
    out = await _signup(client, capture_otp, email, cp)
    headers = out["headers"]

    r = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"birth_date": date.today().isoformat()},
    )
    assert r.status_code == 200, r.text

    # Cuenta de hoy con el cumpleaños «hoy»: no cobra.
    r = await client.post("/api/v1/points/claim-birthday", headers=headers)
    assert r.status_code == 200
    assert (r.json()["awarded"], r.json()["points"]) == (False, 0)
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.json()["points"] == 100  # solo el alta

    # La víspera de cumplir el plazo, tampoco; al cumplirlo, sí.
    await _age_account(db_session, email, days=BIRTHDAY_MIN_ACCOUNT_AGE_DAYS - 1)
    r = await client.post("/api/v1/points/claim-birthday", headers=headers)
    assert r.json()["awarded"] is False
    await _age_account(db_session, email, days=BIRTHDAY_MIN_ACCOUNT_AGE_DAYS)
    r = await client.post("/api/v1/points/claim-birthday", headers=headers)
    assert (r.json()["awarded"], r.json()["points"]) == (True, 500)


@pytest.mark.asyncio
async def test_birth_date_is_set_once(client, capture_otp, db_session):
    _, cp = await _create_town(db_session, "DataFixa", "08414")
    await db_session.commit()
    email = "data@test.cat"
    headers = (await _signup(client, capture_otp, email, cp))["headers"]

    r = await client.patch(
        "/api/v1/users/me", headers=headers, json={"birth_date": "1990-05-17"}
    )
    assert r.json()["birth_date"] == "1990-05-17"

    # Cambiarla no tiene efecto, pero el resto del perfil se guarda.
    r = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"birth_date": date.today().isoformat(), "first_name": "Laia"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["birth_date"] == "1990-05-17"
    assert r.json()["first_name"] == "Laia"

    # Tampoco se puede borrar para volver a ponerla.
    r = await client.patch(
        "/api/v1/users/me", headers=headers, json={"birth_date": None}
    )
    assert r.json()["birth_date"] == "1990-05-17"
    stored = (
        await db_session.execute(
            select(User.birth_date)
            .where(User.email == email)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert stored == date(1990, 5, 17)
