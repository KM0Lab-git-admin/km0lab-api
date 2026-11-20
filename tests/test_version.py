"""Versión del producto y versión mínima admitida de la app."""

import pytest

from app.config import get_settings
from app.version import API_VERSION, is_too_old, parse_version

pytestmark = pytest.mark.asyncio

API = "/api/v1"


async def test_version_numbers():
    assert parse_version("1.2.0") == (1, 2, 0)
    assert parse_version(" 10.0.3 ") == (10, 0, 3)
    assert parse_version("1.2") is None
    assert parse_version("v1.2.0") is None
    assert parse_version(None) is None
    assert parse_version(API_VERSION) is not None


async def test_too_old_only_when_both_versions_are_valid(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "min_app_version", "")
    assert is_too_old("0.0.1") is False

    monkeypatch.setattr(settings, "min_app_version", "1.10.0")
    assert is_too_old("1.9.0") is True  # se compara por número, no por letras
    assert is_too_old("1.10.0") is False
    assert is_too_old("2.0.0") is False
    assert is_too_old(None) is False
    assert is_too_old("no-es-una-version") is False

    monkeypatch.setattr(settings, "min_app_version", "tonteria")
    assert is_too_old("0.0.1") is False


async def test_health_reports_version_and_minimum(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "min_app_version", "1.1.0")
    r = await client.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json()["version"] == API_VERSION
    assert r.json()["min_app_version"] == "1.1.0"


async def test_old_app_is_asked_to_update(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "min_app_version", "1.1.0")
    r = await client.get(
        f"{API}/towns/public",
        params={"postal_code": "08380"},
        headers={"X-App-Version": "1.0.1", "X-App-Platform": "android"},
    )
    assert r.status_code == 426
    assert r.json()["detail"] == {
        "code": "app_update_required",
        "min_version": "1.1.0",
        "your_version": "1.0.1",
    }


async def test_current_app_and_clients_without_header_pass(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "min_app_version", "1.1.0")
    params = {"postal_code": "08380"}

    for headers in (
        {"X-App-Version": "1.1.0"},
        {"X-App-Version": "2.3.4"},
        {},  # backoffice, pruebas y apps anteriores al mecanismo
        {"X-App-Version": "cualquier-cosa"},
    ):
        r = await client.get(f"{API}/towns/public", params=params, headers=headers)
        assert r.status_code != 426, headers


async def test_health_is_never_blocked(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "min_app_version", "9.0.0")
    r = await client.get(f"{API}/health", headers={"X-App-Version": "1.0.0"})
    assert r.status_code == 200


async def test_update_answer_carries_cors_headers(client, monkeypatch):
    """Sin cabeceras CORS el navegador no dejaría leer el 426 a la app."""
    monkeypatch.setattr(get_settings(), "min_app_version", "1.1.0")
    r = await client.get(
        f"{API}/towns/public",
        params={"postal_code": "08380"},
        headers={"X-App-Version": "1.0.1", "Origin": "http://localhost:5173"},
    )
    assert r.status_code == 426
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
