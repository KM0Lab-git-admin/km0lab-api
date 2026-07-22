"""KM0 LAB API — backend de la app (usuarios + auth OTP por email).

MVP: solo usuarios. Puntos (libro mayor), comercios, QR y recompensas
están mockeados en la app y se añadirán aquí como módulos nuevos.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, users
from app.config import get_settings
from app.db import Base, engine

logging.basicConfig(level=logging.INFO)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev: crea las tablas si no existen. En producción, usar Alembic
    # (alembic upgrade head) y NO depender de esto.
    if settings.environment == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="KM0 LAB API",
    version="0.1.0",
    description="Backend de la app KM0 LAB: usuarios y autenticación.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_V1 = "/api/v1"
app.include_router(auth.router, prefix=API_V1)
app.include_router(users.router, prefix=API_V1)


@app.get(f"{API_V1}/health", tags=["health"])
async def health():
    return {"status": "healthy", "version": "0.1.0"}
