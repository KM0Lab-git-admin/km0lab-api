"""Modelos SQLAlchemy. MVP: solo usuarios y códigos OTP.

El resto del dominio (puntos como libro mayor, comercios, escaneos QR,
recompensas, canjes) está mockeado en la app por ahora; se añadirá aquí
como tablas nuevas cuando se implemente. Ver docs/BACKEND.md en km0lab.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), default=None)
    lang: Mapped[str] = mapped_column(String(5), default="ca")  # ca | es | en
    postal_code: Mapped[str | None] = mapped_column(String(10), default=None)
    town: Mapped[str | None] = mapped_column(String(120), default=None)
    # Saldo de puntos. El registro siembra welcome_points (100). El libro
    # mayor de transacciones (QR, canjes) llegará como tabla aparte.
    points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OtpCode(Base):
    """Código OTP de un solo uso enviado por email. Se guarda el hash,
    nunca el código en claro."""

    __tablename__ = "otp_codes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed: Mapped[int] = mapped_column(Integer, default=0)  # 0 | 1
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
