"""Fixtures de test: app FastAPI con una BD SQLite en memoria (compartida
vía StaticPool) sustituyendo MySQL, y un cliente HTTP async."""

import logging

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.db as db_module
from app.db import Base, get_db
from app.main import app


@pytest.fixture(scope="session")
def event_loop_policy():
    import asyncio

    return asyncio.get_event_loop_policy()


@pytest_asyncio.fixture
async def client(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
def capture_otp(caplog):
    """Devuelve una función que extrae el último OTP registrado en el log
    (en dev sin SMTP, el código se loguea)."""

    def _last_code() -> str | None:
        for record in reversed(caplog.records):
            msg = record.getMessage()
            if "OTP para" in msg:
                return msg.split(":")[-1].split("(")[0].strip()
        return None

    caplog.set_level(logging.WARNING, logger="km0lab-api.email")
    return _last_code
