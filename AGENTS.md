# AGENTS.md — km0lab-api

Reglas para agentes de IA en este repositorio. Contexto del ecosistema:
`km0lab/docs/START-HERE-AI.md` y `km0lab/docs/BACKEND.md` (repo hermano
`km0lab`). El detalle de endpoints, seeds y cuentas de prueba está en
`README.md` y `docs/`.

## Qué es

Backend de **negocio** de KM0 LAB: identidad, roles, municipios, comercios,
promociones, puntos, QR, recompensas, canjes, pagos de comercio e
invitaciones. Lo consumen la app (`km0lab`) y el backoffice
(`km0lab-backoffice`). **No** sirve eventos ni noticias: eso es
`events-query`.

Stack: FastAPI, SQLAlchemy 2.0 async, aiomysql (MySQL 8), Alembic, JWT,
OTP por email (Resend o SMTP).

## Dónde va cada cosa

| Qué                          | Dónde                          |
| ---------------------------- | ------------------------------ |
| Endpoints (`/api/v1/...`)    | `app/api/<dominio>.py`         |
| Lógica de negocio            | `app/services/`                |
| Modelos SQLAlchemy           | `app/models.py`                |
| Esquemas Pydantic            | `app/schemas/`                 |
| Auth, roles y dependencias   | `app/security.py`, `app/roles.py`, `app/deps.py` |
| Migraciones                  | `migrations/versions/`         |
| Seeds y sincronización       | `scripts/`                     |
| Tests                        | `tests/`                       |

Los routers se registran en `app/main.py`. Naming en **inglés**.

## Comandos

```bash
cp .env.example .env
docker compose up --build          # API en :8000, Swagger en /docs
# o en local:
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
alembic upgrade head
python -m scripts.seed             # pueblos reales + cuentas QA
pytest                             # usa SQLite en memoria, no necesita MySQL
```

## Reglas

1. **Todo cambio de modelo lleva migración Alembic.** Las tablas solo se
   crean solas con `ENVIRONMENT=development`; UAT y producción dependen de
   `alembic upgrade head`. La versión vigente es la última de
   `migrations/versions/`, no la que cite el README.
2. **Ámbito por municipio.** Un admin gestiona su població y un comerç solo
   su comercio. Cualquier endpoint nuevo debe filtrar por el `town_id` o
   `shop_id` del contexto autenticado; conviene cubrirlo con un test que
   use dos municipios.
3. **Puntos por ledger.** La fuente de verdad es `points_transactions`;
   `users.points` es un saldo cacheado. No modifiques el saldo sin
   registrar su movimiento.
4. **Código OTP fijo `123456`** solo existe con `ENVIRONMENT=development`
   o `staging`. No lo actives ni lo simules en producción.
5. **Datos: Railway → local.** `scripts/pull_from_railway.py` es el flujo
   diario y nunca escribe en Railway. `scripts/sync_to_railway.py`
   **sobrescribe la base remota**: solo se ejecuta cuando el usuario pide
   publicar.
6. **Contrato con los frontends.** Si cambias la forma de una respuesta,
   revisa los clientes: `km0lab/packages/app/services/` y
   `km0lab-backoffice/src/services/`.
7. **Textos de interfaz** no viven aquí. Este backend persiste datos; la
   traducción automática de campos de entidad está en
   `app/services/translation.py`.
8. **Secretos** solo en `.env` (no commiteado) y en las variables de Railway.

## Git

Rama de trabajo `develop` (despliega a UAT). `main` es producción y solo
recibe merges decididos por una persona. Conventional Commits con subject
de 50 caracteres como máximo. Sin `--amend` ni `--force` salvo petición.

## Antes de cerrar una tarea

- [ ] `pytest` en verde.
- [ ] Migración incluida si cambió `app/models.py`.
- [ ] Test de ámbito municipal si el endpoint devuelve o modifica datos de
      una població.
- [ ] Clientes de app y backoffice revisados si cambió un contrato.
