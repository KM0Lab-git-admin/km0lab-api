"""Test fixtures: in-memory SQLite + HTTP client; OTP capture without email."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import ShopCategory
from app.catalog.shop_categories import (
    DEFAULT_SHOP_CATEGORIES,
    DEFAULT_SHOP_CATEGORY_EMOJIS,
)
from app.ratelimit import limiter


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(eng, expire_on_commit=False)
    async with session_maker() as session:
        for slug, order in DEFAULT_SHOP_CATEGORIES:
            session.add(
                ShopCategory(
                    slug=slug,
                    sort_order=order,
                    active=True,
                    emoji=DEFAULT_SHOP_CATEGORY_EMOJIS.get(slug),
                )
            )
        await session.commit()

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def client(engine, monkeypatch):
    # Disable rate limits in tests (shared IP would hit 5/hour across cases).
    monkeypatch.setattr(limiter, "enabled", False)

    last_otp: dict[str, str] = {"code": ""}

    async def fake_send_otp(to: str, code: str, lang: str | None = None) -> None:
        last_otp["code"] = code
        last_otp["lang"] = lang

    monkeypatch.setattr("app.api.auth.send_otp_email", fake_send_otp)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.state.last_otp = last_otp  # type: ignore[attr-defined]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def capture_otp(client):
    """Return the last OTP issued by the fake email sender."""

    def _last_code() -> str | None:
        code = getattr(app.state, "last_otp", {}).get("code") or None
        return code

    return _last_code
