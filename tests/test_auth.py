"""Tests del flujo de auth OTP: registro→código→JWT→perfil, más los
casos de código inválido y corte por intentos."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models import OtpCode, User
from app.ratelimit import MAX_LIVE_OTP_CODES
from app.security import verify_otp

pytestmark = pytest.mark.asyncio

EMAIL = "veci@malgrat.cat"


async def test_health(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


async def test_full_login_flow_creates_user_with_welcome_points(
    client, capture_otp
):
    r = await client.post("/api/v1/auth/request-otp", json={"email": EMAIL})
    assert r.status_code == 200

    code = capture_otp()
    assert code and len(code) == 6

    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": EMAIL, "code": code}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user"]["email"] == EMAIL
    assert data["user"]["points"] == 100  # bienvenida
    assert data["user"]["lang"] == "ca"
    token = data["access_token"]

    # /me con el token
    r = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert r.json()["email"] == EMAIL

    # actualizar perfil
    r = await client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"first_name": "Marc", "last_name": "Puig", "lang": "es"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["first_name"] == "Marc"
    assert body["last_name"] == "Puig"
    assert body["name"] == "Marc Puig"
    assert body["lang"] == "es"
    assert body["slug"]


async def test_second_login_reuses_user(client, capture_otp):
    for _ in range(2):
        await client.post("/api/v1/auth/request-otp", json={"email": EMAIL})
        code = capture_otp()
        r = await client.post(
            "/api/v1/auth/verify-otp", json={"email": EMAIL, "code": code}
        )
        assert r.status_code == 200
    # sigue siendo el mismo usuario con 100 puntos (no se duplican)
    assert r.json()["user"]["points"] == 100


async def test_wrong_code_rejected(client, capture_otp):
    await client.post("/api/v1/auth/request-otp", json={"email": EMAIL})
    capture_otp()
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": EMAIL, "code": "000000"}
    )
    assert r.status_code == 400


async def test_me_requires_token(client):
    r = await client.get("/api/v1/users/me")
    assert r.status_code == 403  # HTTPBearer sin credenciales


async def test_otp_invalidated_after_max_attempts(client, capture_otp):
    await client.post("/api/v1/auth/request-otp", json={"email": EMAIL})
    good_code = capture_otp()

    # 5 intentos fallidos → el código queda invalidado
    for _ in range(5):
        r = await client.post(
            "/api/v1/auth/verify-otp", json={"email": EMAIL, "code": "111111"}
        )
        assert r.status_code == 400

    # aunque ahora usemos el código correcto, ya no vale
    r = await client.post(
        "/api/v1/auth/verify-otp", json={"email": EMAIL, "code": good_code}
    )
    assert r.status_code == 400


# ── Entrar sin tropiezos: varios códigos, motivos claros, envío fallido ──


async def _request(client):
    return await client.post("/api/v1/auth/request-otp", json={"email": EMAIL})


async def _verify(client, code: str):
    return await client.post(
        "/api/v1/auth/verify-otp", json={"email": EMAIL, "code": code}
    )


async def test_asking_again_keeps_the_earlier_code_valid(client, capture_otp):
    """Quien pide dos códigos y abre el primer correo también entra."""
    await _request(client)
    first = capture_otp()
    await _request(client)
    second = capture_otp()

    r = await _verify(client, first)
    assert r.status_code == 200, r.text

    # Un código, una entrada: el otro deja de valer con él.
    r = await _verify(client, second)
    assert r.status_code == 400


async def test_each_refusal_says_why(client, capture_otp, db_session):
    # Nunca se pidió código para este correo.
    r = await _verify(client, "123123")
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "otp_invalid")

    await _request(client)
    good = capture_otp()
    wrong = "000000" if good != "000000" else "111111"

    r = await _verify(client, wrong)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "otp_invalid")
    assert r.json()["detail"]["message"]

    # Caducado: el código era bueno, pero ya ha pasado su tiempo.
    await db_session.execute(
        update(OtpCode).values(expires_at=datetime.utcnow() - timedelta(minutes=1))
    )
    await db_session.commit()
    r = await _verify(client, good)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "otp_expired")


async def test_wrong_guesses_count_against_every_live_code(client, capture_otp):
    """Pedir más códigos no da más intentos."""
    await _request(client)
    first = capture_otp()
    await _request(client)
    second = capture_otp()
    wrong = next(c for c in ("000000", "111111", "222222") if c not in (first, second))

    for attempt in range(1, 6):
        r = await _verify(client, wrong)
        expected = "otp_too_many_attempts" if attempt == 5 else "otp_invalid"
        assert (r.status_code, r.json()["detail"]["code"]) == (400, expected)

    for code in (first, second):
        r = await _verify(client, code)
        assert r.json()["detail"]["code"] == "otp_too_many_attempts"


async def test_failed_email_leaves_the_earlier_code_usable(
    client, capture_otp, monkeypatch
):
    await _request(client)
    earlier = capture_otp()

    async def broken_send(to: str, code: str, lang: str | None = None) -> None:
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.api.auth.send_otp_email", broken_send)
    r = await _request(client)
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "otp_send_failed"

    # El código que sí llegó sigue sirviendo.
    r = await _verify(client, earlier)
    assert r.status_code == 200, r.text


async def test_failed_first_email_leaves_nothing_half_done(
    client, monkeypatch, db_session
):
    async def broken_send(to: str, code: str, lang: str | None = None) -> None:
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.api.auth.send_otp_email", broken_send)
    r = await _request(client)
    assert r.status_code == 503

    # El código que no salió no queda vivo, y no se ha creado ninguna cuenta.
    live = (
        await db_session.execute(select(OtpCode).where(OtpCode.consumed == 0))
    ).scalars().all()
    assert live == []
    assert (await db_session.execute(select(User))).scalars().all() == []


async def _live_codes(db_session) -> int:
    rows = (
        await db_session.execute(
            select(OtpCode)
            .where(OtpCode.email == EMAIL, OtpCode.consumed == 0)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return len(rows)


async def _age_codes(db_session, ages: dict[str, int]) -> None:
    """Fecha cada código pedido: {código: hace cuántos minutos}.

    Varios códigos pedidos en el mismo segundo comparten ``created_at``; en
    la vida real los separa la espera de reenvío de la app.
    """
    rows = (
        await db_session.execute(select(OtpCode).where(OtpCode.email == EMAIL))
    ).scalars().all()
    for row in rows:
        for code, minutes_ago in ages.items():
            if verify_otp(code, row.code_hash):
                row.created_at = datetime.utcnow() - timedelta(minutes=minutes_ago)
    await db_session.commit()


async def test_at_most_three_codes_stay_live(client, capture_otp, db_session):
    """Cada intento se compara con todos los códigos vivos: que sean pocos."""
    assert MAX_LIVE_OTP_CODES == 3
    codes = []
    for n in range(3):
        await _request(client)
        codes.append(capture_otp())
    # Los tres primeros, pedidos hace 6, 4 y 2 minutos.
    await _age_codes(db_session, dict(zip(codes, [6, 4, 2])))
    assert await _live_codes(db_session) == 3

    # El cuarto retira el más antiguo; el quinto, el siguiente.
    await _request(client)
    codes.append(capture_otp())
    assert await _live_codes(db_session) == 3
    await _age_codes(db_session, {codes[3]: 1})
    await _request(client)
    codes.append(capture_otp())
    assert await _live_codes(db_session) == 3

    # Los dos más antiguos ya no entran (salvo que coincidan por azar con uno vivo).
    for old in codes[:2]:
        if old in codes[2:]:
            continue
        r = await _verify(client, old)
        assert r.status_code == 400
    # Cualquiera de los tres últimos, sí.
    r = await _verify(client, codes[2])
    assert r.status_code == 200, r.text


async def test_failed_email_does_not_retire_older_codes(
    client, capture_otp, db_session, monkeypatch
):
    codes = []
    for _ in range(3):
        await _request(client)
        codes.append(capture_otp())
    await _age_codes(db_session, dict(zip(codes, [6, 4, 2])))

    async def broken_send(to: str, code: str, lang: str | None = None) -> None:
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.api.auth.send_otp_email", broken_send)
    r = await _request(client)
    assert r.status_code == 503

    # Los tres que llegaron siguen vivos, también el más antiguo.
    assert await _live_codes(db_session) == 3
    r = await _verify(client, codes[0])
    assert r.status_code == 200, r.text
