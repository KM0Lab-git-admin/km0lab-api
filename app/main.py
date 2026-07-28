"""KM0 LAB API — domain backend (auth, towns, shops, points, rewards)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import (
    actions,
    auth,
    promotions,
    redemptions,
    residents,
    rewards,
    scans,
    shops,
    stats,
    towns,
    users,
)
from app.config import get_settings
from app.db import Base, engine
from app.ratelimit import limiter

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
    version="0.2.0",
    description=(
        "Backend KM0 LAB: auth OTP, towns, shops, promotions, "
        "point actions, rewards, redemptions, QR scans."
    ),
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
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
    promotions,
    actions,
    rewards,
    redemptions,
    scans,
    residents,
    stats,
):
    app.include_router(module.router, prefix=API_V1)


@app.get(f"{API_V1}/health", tags=["health"])
async def health():
    return {"status": "healthy", "version": "0.2.0"}
