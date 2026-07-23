"""Tests del flujo de auth OTP: registro→código→JWT→perfil, más los
casos de código inválido y corte por intentos."""

import pytest

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
        json={"name": "Marc", "town": "Malgrat de Mar", "lang": "es"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Marc"
    assert body["town"] == "Malgrat de Mar"
    assert body["lang"] == "es"


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
