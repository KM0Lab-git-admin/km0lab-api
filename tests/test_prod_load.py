"""Production is a different database, and the load scripts only add what is missing."""

import os

import pytest
from sqlalchemy import delete, func, select

from app.models import Reward, Shop, ShopCategory, User
from app.services.prod_seed import (
    ensure_shop_categories,
    production_counts,
    seed_catalog,
)
from scripts._target import guard_write, point_at

_DB_KEYS = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")


def _restore_db(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_production_is_never_the_uat_variable(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.delenv("PROD_DB_URL", raising=False)
    monkeypatch.setenv("RAILWAY_DB_URL", "mysql://uat:secret@uat.example:3306/uatdb")
    with pytest.raises(SystemExit, match="PROD_DB_URL"):
        point_at("production")
    assert os.environ.get("DB_HOST") != "uat.example"


def test_production_uses_its_own_url_and_refuses_a_wrong_name(monkeypatch, capsys):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_args, **_kwargs: None)
    previous = {key: os.environ.get(key) for key in _DB_KEYS}
    monkeypatch.setenv(
        "PROD_DB_URL", "mysql://prod:secret@prod.example:3306/km0lab_prod"
    )
    try:
        _production_url(capsys)
    finally:
        _restore_db(previous)


def _production_url(capsys):
    label = point_at("production")
    assert "PRODUCCIÓN" in label
    assert "km0lab_prod" in label
    assert "secret" not in label
    assert os.environ["DB_HOST"] == "prod.example"
    assert os.environ["DB_NAME"] == "km0lab_prod"

    with pytest.raises(SystemExit, match="no coincide"):
        guard_write("production", apply=True, confirm="uatdb")
    guard_write("production", apply=True, confirm="km0lab_prod")
    assert "ESCRIBE EN PRODUCCIÓN" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="--confirm"):
        guard_write("production", apply=True, confirm=None)


@pytest.mark.asyncio
async def test_categories_and_catalog_are_idempotent_and_have_no_people(db_session):
    await db_session.execute(delete(ShopCategory).where(ShopCategory.slug == "bakery"))
    await db_session.commit()

    missing = await ensure_shop_categories(db_session, apply=False)
    assert missing == ["bakery"]
    assert await db_session.get(ShopCategory, "bakery") is None

    assert await ensure_shop_categories(db_session, apply=True) == ["bakery"]
    await db_session.commit()
    assert await ensure_shop_categories(db_session, apply=True) == []

    created, _images = await seed_catalog(db_session, apply=True)
    await db_session.commit()
    assert created > 0
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Shop)) == 0
    rewards = await db_session.scalar(select(func.count()).select_from(Reward))
    assert rewards == created

    again, _images = await seed_catalog(db_session, apply=True)
    assert again == 0
    counts = await production_counts(db_session)
    assert counts["accounts"] == 0
    assert counts["shops"] == 0
    assert counts["administrators"] == 0
    assert any(town["name"] == "Demo KM0" for town in counts["municipalities"])
    assert counts["postal_codes"] >= 1
