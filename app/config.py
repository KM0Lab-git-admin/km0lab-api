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
    # Cuánto dura la sesión. Sin renovación: al caducar se vuelve a entrar.
    jwt_expire_minutes: int = 60 * 24 * 90  # 90 días

    # OTP
    otp_ttl_minutes: int = 10
    # Límites por conexión (IP) y hora: cuántos códigos se piden y cuántas
    # entradas se intentan. Sin valor: 30 y 60 (600 en development). Se
    # suben por variable el día de una presentación con muchos vecinos en
    # la misma wifi.
    otp_requests_per_hour: int | None = None
    otp_verifies_per_hour: int | None = None
    # Códigos por hora al mismo correo, venga de donde venga la petición:
    # lo que impide usar la API para llenar el buzón de otra persona.
    otp_per_email_per_hour: int = 5
    otp_length: int = 6
    welcome_points: int = 100  # puntos de bienvenida al registrarse
    invite_person_points: int = 100
    invite_business_points: int = 500

    # Versión mínima de la app admitida (app/version.py). Vacía = todas.
    # Una app por debajo recibe 426 y enseña «actualiza la app».
    min_app_version: str = ""

    # Territorio QA (app/qa.py): clave de POST /qa/prepare. Vacía = cerrado.
    # Nunca se usa en production, aunque se configure.
    qa_token: str = ""

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
        "http://localhost:5173,http://localhost:5174,http://localhost:5175,"
        "http://localhost:3000,http://localhost:8080,http://localhost:8081,"
        "http://localhost:8082,http://127.0.0.1:5173,http://127.0.0.1:5174,"
        "http://127.0.0.1:5175,http://127.0.0.1:3000,http://127.0.0.1:8080,"
        "http://127.0.0.1:8081,http://127.0.0.1:8082"
    )
    # UAT/prod + Vite local en cualquier puerto (5173/5174/5175…).
    cors_origin_regex: str = (
        r"https://([a-z0-9-]+\.)*km0lab\.com"
        r"|http://localhost:\d+"
        r"|http://127\.0\.0\.1:\d+"
    )

    # Deep-link encoded in shop QR PNGs (app extracts ?c=token)
    qr_scan_base_url: str = "https://app.km0lab.com/scan"
    # Where a shop signs in to its panel. It goes in the email a shop
    # gets when it is registered; empty = that email is not sent.
    backoffice_url: str = ""

    # Entrar con una red social (app/services/social.py). Una red se
    # ofrece cuando está en AUTH_PROVIDERS (p. ej. "google,apple") y tiene
    # aquí su identificador de cliente, que es público. Vacío = apagada.
    auth_providers: str = ""
    google_client_id: str = ""
    facebook_client_id: str = ""
    apple_client_id: str = ""

    # OpenAI — used to auto-fill missing i18n languages on save.
    # If empty, the API copies the source text into empty languages.
    openai_api_key: str = ""
    openai_translate_model: str = "gpt-4o-mini"

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
