# km0lab-api

Backend de la app **KM0 LAB** (usuarios + autenticación). FastAPI + MySQL.

Es un repo hermano de `km0lab` (app) y `events-query` (API de eventos y
noticias, solo lectura). **Este backend NO toca eventos/noticias**: solo
persiste el dominio de la app (usuarios y, más adelante, puntos,
comercios, QR y recompensas).

## Alcance actual (MVP)

Solo **usuarios** y **auth por OTP de email**. El resto del dominio
(puntos como libro mayor, comercios, escaneos QR, recompensas, canjes)
está **mockeado en la app** por ahora y se añadirá aquí como módulos
nuevos. Los textos e idiomas (i18n) viven en la app (`km0lab`), NO aquí.

Arquitectura y modelo de datos completos: `docs/BACKEND.md` en `km0lab`.

## Stack

- **FastAPI** + **SQLAlchemy 2.0 async** + **aiomysql** (MySQL 8)
- **Alembic** para migraciones (BD que puede crecer)
- **JWT** (python-jose) · **OTP por email** (aiosmtplib)

## Endpoints (v1)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/auth/request-otp` | Envía un código OTP al email |
| POST | `/api/v1/auth/verify-otp` | Verifica el código; crea el usuario si no existe (con 100 puntos de bienvenida) y devuelve un JWT |
| GET | `/api/v1/users/me` | Perfil del usuario autenticado |
| PATCH | `/api/v1/users/me` | Actualiza nombre, idioma, CP, población |
| GET | `/api/v1/health` | Health check |

Swagger interactivo en `/docs`.

## Desarrollo local

### Opción A — Docker (recomendada)

```bash
cp .env.example .env
docker compose up --build
# API en http://localhost:8000  · Swagger en http://localhost:8000/docs
```

En `ENVIRONMENT=development`, las tablas se crean solas al arrancar. Sin
SMTP configurado, el código OTP se imprime en el log del contenedor
(útil para probar el login sin enviar correos reales).

### Opción B — local con MySQL propio

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # ajusta DB_* a tu MySQL
uvicorn app.main:app --reload
```

## Migraciones (Alembic)

En **producción** NO se usa el `create_all` de desarrollo: se aplican
migraciones.

```bash
alembic upgrade head                       # aplicar migraciones
alembic revision --autogenerate -m "..."   # crear una nueva al cambiar modelos
```

La migración inicial (`0001_initial`) crea `users` y `otp_codes`.

## Flujo de auth (OTP email)

1. `POST /auth/request-otp { email }` → genera un código de 6 dígitos,
   lo guarda hasheado (TTL 10 min) y lo envía por email.
2. `POST /auth/verify-otp { email, code }` → valida el código; si el
   usuario no existía lo crea con 100 puntos de bienvenida; devuelve
   `{ access_token, user }`.
3. El frontend guarda el `access_token` y lo manda como
   `Authorization: Bearer <token>` en las rutas protegidas.

## Producción (Railway)

- Variables: `ENVIRONMENT=production`, `DB_*` del MySQL gestionado,
  `JWT_SECRET` largo y aleatorio, `CORS_ORIGINS` con los dominios de la
  app, y email:
  - **Recomendado:** `RESEND_API_KEY` + `SMTP_FROM` (API HTTP de Resend;
    evita timeouts SMTP:587 en Railway).
  - Alternativa: `SMTP_*` clásico.
- Pipeline de arranque: `alembic upgrade head` y luego `uvicorn`.
- Sin `RESEND_API_KEY` ni `SMTP_HOST` el OTP solo se imprime en el log.
