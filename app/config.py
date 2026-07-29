"""Configuración de la API (variables de entorno, tipadas)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Entorno: development | staging | production
    # Demo login (resident@/merchant@/admin@km0lab.com + 123456) activo
    # salvo en production.
    environment: str = "development"

    # Base de datos MySQL
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "km0lab"
    db_password: str = "km0lab"
    db_name: str = "km0lab"

    # JWT
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 30  # 30 días

    # OTP
    otp_ttl_minutes: int = 10
    otp_length: int = 6
    welcome_points: int = 100  # puntos de bienvenida al registrarse

    # Email: preferir Resend HTTP (RESEND_API_KEY). SMTP queda como fallback.
    # Sin key ni SMTP_HOST → el OTP se imprime en log (útil en local/UAT).
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "KM0 LAB <no-reply@email.km0lab.com>"

    # CORS: orígenes del frontend, separados por coma
    cors_origins: str = (
        "http://localhost:5173,http://localhost:5174,http://localhost:3000,"
        "http://localhost:8080,"
        "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:3000,"
        "http://127.0.0.1:8080"
    )

    # Deep-link encoded in shop QR PNGs (app extracts ?c=token)
    qr_scan_base_url: str = "https://app.km0lab.com/scan"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        """URL síncrona para Alembic (migraciones)."""
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
