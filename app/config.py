"""Configuración de la API (variables de entorno, tipadas)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Entorno
    environment: str = "development"  # development | production

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

    # Email (SMTP). Si no hay host, en development el código se imprime en log.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "KM0 LAB <no-reply@km0lab.com>"

    # CORS: orígenes permitidos, separados por coma
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

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
