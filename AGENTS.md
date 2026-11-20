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
python -m scripts.seed_qa          # territorio de pruebas (CP 99999)
python -m scripts.check_flows_mysql  # flujos y concurrencia contra MySQL local
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
9. **Datos de prueba solo en el territorio QA.** El piloto corre en UAT con
   una sola base de datos. Lo que cree una prueba vive en CP 9999x, con
   cuentas `qa+…@km0lab.com`, `is_fake=true` y nombre `[QA]`, para poder
   borrarlo con `scripts/purge_qa.py`. Nunca escribas datos de prueba en un
   municipio real ni en Demo KM0 (00000). Ver `docs/QA-TERRITORY.md`.
10. **Puntos bajo bloqueo.** Un endpoint que comprueba y luego modifica el
    saldo llama primero a `lock_user_points` (`app/services/points.py`) y
    hace sus comprobaciones con lecturas `with_for_update`. SQLite no lo
    detecta: se verifica con `scripts/check_flows_mysql.py`.

## Versiones y compatibilidad

La versión del producto está en el fichero `VERSION` de la raíz. **No se
edita a mano**: la cambia el comando de publicar de `km0lab`
(`km0lab/docs/VERSIONES.md`). `/api/v1/health` la devuelve junto al commit.

La app nativa se publica menos a menudo que esta API (más o menos una vez
al mes), así que **en los móviles hay siempre una app más antigua que el
servidor**. Mientras esa app esté admitida:

- **Añade, no quites.** Un campo nuevo es compatible. Quitar o renombrar un
  campo, cambiar su tipo o volver obligatorio uno opcional rompe a la app
  publicada. Si hay que hacerlo, primero se añade lo nuevo, se publica la
  app que lo usa, y solo después se retira lo viejo.
- **Versión mínima.** `MIN_APP_VERSION` es la app más antigua admitida. A
  una app por debajo se le contesta 426 con `app_update_required`
  (`app/version.py`) y enseña «actualiza la app». Súbela cuando retires
  algo que una app antigua todavía usa.

La comprobación automática vive en `km0lab`: cada noche se lanzan los
recorridos de la última app publicada contra esta API en UAT.

## Git

Rama de trabajo `develop` (despliega a UAT). `main` es producción y solo
recibe merges decididos por una persona. Conventional Commits con subject
de 50 caracteres como máximo. Sin `--amend` ni `--force` salvo petición.

## Qué se prueba y cuándo

Dos tramos, para no frenar el trabajo diario:

- **Rápido, en tu máquina.** Al subir `develop` o `main`, el gancho
  `.githooks/pre-push` lanza `pytest` (unos 15 segundos, sin MySQL). Si
  falla, no se sube. Se activa una vez por copia del repositorio:
  `git config core.hooksPath .githooks`.
- **Lento, en GitHub, ya subido.** `.github/workflows/tests.yml` repite
  `pytest` y añade las migraciones desde cero y los flujos sobre MySQL.
  No bloquea el despliegue de UAT: avisa.

`python -m scripts.check_flows_mysql` se puede lanzar en local a mano
cuando el cambio toca puntos, canjes o la base de datos.

## Antes de cerrar una tarea

- [ ] `pytest` en verde.
- [ ] `python -m scripts.check_flows_mysql` en verde si tocaste puntos,
      escaneos, canjes, invitaciones o el territorio QA.
- [ ] Migración incluida si cambió `app/models.py`.
- [ ] Test de ámbito municipal si el endpoint devuelve o modifica datos de
      una població.
- [ ] Clientes de app y backoffice revisados si cambió un contrato.
