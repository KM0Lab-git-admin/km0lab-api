"""KM0 LAB API — domain backend (auth, towns, shops, points, rewards)."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import (
    actions,
    auth,
    invites,
    payments,
    points,
    promotions,
    qa,
    redemptions,
    residents,
    rewards,
    scans,
    shop_categories,
    shops,
    stats,
    towns,
    users,
)
from app.config import get_settings
from app.db import Base, engine
from app.ratelimit import limiter
from app.version import API_VERSION, AppVersionMiddleware, min_app_version

logging.basicConfig(level=logging.INFO)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="KM0 LAB API",
    version=API_VERSION,
    description=(
        "Backend KM0 LAB: auth OTP, towns, shops, promotions, "
        "point actions, rewards, redemptions, QR scans, invitations."
    ),
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Antes que CORS: así la respuesta 426 también sale con sus cabeceras CORS
# y el navegador deja que la app la lea.
app.add_middleware(AppVersionMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_V1 = "/api/v1"
for module in (
    auth,
    users,
    towns,
    shops,
    shop_categories,
    promotions,
    actions,
    points,
    rewards,
    redemptions,
    payments,
    scans,
    residents,
    stats,
    invites,
    qa,
):
    app.include_router(module.router, prefix=API_V1)
app.include_router(invites.admin_router, prefix=API_V1)


def _deployed_commit() -> str | None:
    """Commit that Railway built this deployment from (None in local)."""
    sha = os.getenv("RAILWAY_GIT_COMMIT_SHA", "").strip()
    return sha or None


@app.get(f"{API_V1}/health", tags=["health"])
async def health():
    return {
        "status": "healthy",
        "version": API_VERSION,
        "min_app_version": min_app_version() or None,
        "environment": settings.environment,
        "commit": _deployed_commit(),
    }
