# km0lab-api

Backend de **KM0 LAB** (app + backoffice). FastAPI + MySQL.

Hermano de `km0lab` (app), `km0lab-backoffice` (panel) y `events-query`
(noticias/agenda, solo lectura). **Este backend NO sirve eventos/noticias**:
persiste el dominio de negocio (usuarios, puntos, comercios, QR, recompensas).

## Dominio (v0.2)

| Área | Tablas |
|------|--------|
| Identidad | `users` (email único; `postal_code` → `town_postal_codes` → `towns`; roles multi), `otp_codes`, `towns`, `town_postal_codes` |
| Comercios | `shops`, `promotions` |
| Catálogo | `point_actions`, `rewards`, `reward_shops` |
| Ledger / QR / canjes | `points_transactions`, `qr_scans`, `redemptions`, `redemption_events` |

Naming en **inglés**. Auth: OTP email + JWT (`roles[]`, `town_id`, `shop_id`).
Misma identidad (email) puede usar app y backoffice según roles.
Header opcional `X-Active-Role` para fijar el contexto de la petición.

## Stack

- **FastAPI** + **SQLAlchemy 2.0 async** + **aiomysql** (MySQL 8)
- **Alembic** para migraciones
- **JWT** (python-jose) · **OTP por email** (Resend / SMTP)

## Endpoints (v1)

| Método | Ruta | Rol |
|--------|------|-----|
| POST | `/api/v1/auth/request-otp` | público |
| POST | `/api/v1/auth/verify-otp` | público |
| GET/PATCH | `/api/v1/users/me` | autenticado |
| GET/PATCH | `/api/v1/towns/{id}` | admin |
| CRUD | `/api/v1/shops` · `/shops/me` · `/shops/me/qr` | admin / merchant |
| CRUD | `/api/v1/promotions` | merchant |
| CRUD | `/api/v1/actions` | admin |
| CRUD | `/api/v1/rewards` | admin (+ lectura resident) |
| POST/GET/PATCH | `/api/v1/redemptions` | resident / admin / merchant |
| POST | `/api/v1/scans` | resident |
| GET | `/api/v1/residents` | admin |
| GET | `/api/v1/stats/admin` · `/stats/merchant` | admin / merchant |
| GET | `/api/v1/health` | público |

Swagger en `/docs`.

## Desarrollo local

### Opción A — Docker

```bash
cp .env.example .env
docker compose up --build
# API http://localhost:8000  · Swagger http://localhost:8000/docs
```

En `ENVIRONMENT=development` las tablas se crean al arrancar. Sin SMTP/Resend,
el OTP se imprime en el log.

### Opción B — local

```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## Migraciones

```bash
alembic upgrade head
alembic revision --autogenerate -m "..."
```

Revisiones de dominio: `0003_towns_roles` … `0010_is_fake`.

## Seed

```bash
alembic upgrade head
python -m scripts.seed
```

Crea Malgrat / Blanes / Lloret con admin, shop piloto y catálogo de ejemplo.

## Demo (development / staging)

Cuentas fijas (código **123456**, sin email OTP). Solo ven filas `is_fake=true`:

| Email | Roles |
|-------|--------|
| `resident@km0lab.com` | resident |
| `merchant@km0lab.com` | resident + merchant |
| `admin@km0lab.com` | resident + admin |

```bash
python -m scripts.seed          # towns reales (Malgrat…)
python -m scripts.seed_demo     # usuarios + catálogo fake Malgrat
```

Desactivado automáticamente si `ENVIRONMENT=production`.

## Tests

```bash
pytest
```
