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
   o `staging`. No lo actives ni lo simules en producción. Las cuentas que
   lo usan son una lista cerrada en `app/demo.py`: no la amplíes sin que
   se pida. Incluye, **de forma temporal**, a los administradores de
   Malgrat y de Baix Montseny (`PILOT_ADMIN_EMAILS`, un correo
   `<municipio>@km0lab.com` por municipio), que son municipios reales: hay
   que quitar cada uno antes de que el suyo tenga vecinos o comercios de
   verdad.
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

## Municipio y poblaciones

- **Municipio** (`towns`): el cliente. Un administrador, unas reglas de
  puntos, unas acciones y unos premios, **compartidos** por todas sus
  poblaciones. Su nombre no se enseña en la app.
- **Población** (`localities`): lo que el vecino llama «mi pueblo». Tiene
  nombre, códigos postales e ilustración. Un comercio es de una población.
  Dos poblaciones no comparten código postal.

Un municipio de un solo pueblo tiene una población con su mismo nombre.
`GET /towns/public?postal_code=` contesta desde la población de ese código
postal (`name`, `art_url`…) y añade `municipality_*` y `localities`.

Dar de alta un pueblo: `scripts/add_town.py`. Agrupar varios en un
municipio: `scripts/group_towns.py` (sin `--apply` solo enseña; se niega si
alguno ya tiene premios, canjes, movimientos o administrador propios).
Dar de alta a su administrador: `scripts/add_admin.py` (una cuenta por
municipio; entra con su correo y el código, sin contraseña).

Al crear un comercio la API decide su población: la que se le diga
(`locality_id`), o la del código postal del comercio, o la única que haya.
Con varias poblaciones y sin ninguna pista contesta 422 `locality_required`:
no se adivina. `GET /towns/me` devuelve `localities` para que el backoffice
las ofrezca.

## Alta de un comercio

Un comercio entra por dos caminos (`app/services/shop_review.py`):

- **Lo da de alta el administrador** (`POST /shops`): nace `pending`, con
  su QR, y pasa a `active` cuando su dueño entra con el correo de contacto.
- **Lo pide el propio comercio** (`POST /shops/public-signup`, con la sesión
  de quien lo pide): nace `review`, sin QR, y **no existe en público** hasta
  que el administrador de su municipio lo aprueba (`POST /shops/{id}/approve`)
  o lo rechaza con un motivo (`POST /shops/{id}/reject`, queda `rejected`).

Reglas:

- Nada activa un comercio en `review` salvo aprobarlo: ni entrar con su
  correo ni el `PATCH` del administrador (409 `shop_in_review`).
- Lo que la máquina sabe comprobar (dígito de control del NIF, NIE o CIF,
  código postal, duplicados) se rechaza al enviar; lo demás lo ve el
  administrador en `GET /shops/{id}/review`.
- A quien invitó al comercio se le paga **al aprobar**, no antes.
- El motivo del rechazo viaja en el correo y se guarda en
  `shops.review_note` para que el comercio lo lea en su pantalla. Las
  rechazadas se borran a los 30 días con `scripts/purge_rejected_shops.py`
  (sin `--apply` solo enseña); una rechazada no se edita.
- `/users/me` y el login devuelven `shop_request` (`review` o `rejected`,
  con `reason` si fue rechazada).

## Cómo entra cada cuenta

Una cuenta sigue siendo **un correo** (`users.email`, único y obligatorio).
Lo que se guarda aparte es **por dónde entra** la persona: una fila de
`user_identities` por puerta (`app/services/identities.py`).

- Puertas: `email_code` (el código por correo), `google`, `facebook`,
  `apple`. La primera que usó la cuenta es su **origen** (`is_first`) y no
  cambia al enlazar otra. El administrador lo ve en la ficha del vecino y,
  agregado, en `/stats/admin` (`signups_by_provider`). La cifra de todos
  los municipios: `python -m scripts.identities_report` (solo lee).
- **Una red es un verificador pequeño** (`app/services/social.py`,
  `VERIFIERS`): recibe la credencial que la red dio a la app y dice quién
  es esa persona allí. Todo lo demás (crear la cuenta, condiciones, aforo,
  invitación, comercio en espera) es el mismo camino que el código por
  correo: `_sign_in` en `app/api/auth.py`. No dupliques ese camino.
- **Encender una red no es desplegar:** se ofrece cuando está en
  `AUTH_PROVIDERS`, tiene su `<RED>_CLIENT_ID` y tiene verificador.
  `GET /auth/providers` dice a la app qué botones enseñar según la
  plataforma (web: las encendidas; app Android: ninguna; iPhone: Apple).
- **Solo un correo verificado abre una cuenta que ya existe.** Si la red no
  da correo o no lo garantiza, `POST /auth/social/{red}` contesta 409
  `email_missing` con un `link_token` de 15 minutos; la persona confirma un
  correo con el código y `verify-otp` enlaza la red. Nunca se inventa un
  correo ni se une una cuenta por un correo sin verificar.
- Una puerta que ya abre una cuenta **no se mueve** a otra (409
  `identifier_taken`). Con sesión abierta, la misma llamada enlaza la red a
  esa cuenta.
- Administradores, cuentas de prueba y de código fijo entran **solo por
  correo** (403 `use_email`).
- **No se guarda ninguna credencial** de Google, Facebook ni Apple.

## Sesión: se entra una vez

Quien usa la App o el panel **no vuelve a identificarse**
(`app/services/sessions.py`).

- La credencial vale `SESSION_IDLE_DAYS` (365; 30 para un administrador)
  **desde la última renovación**. Las apps la renuevan solas al abrirse
  (`POST /auth/renew`). Solo vuelve a entrar quien pasa ese tiempo sin
  usarlas.
- **Nada de esto puede echar a nadie por mala conexión.** Renovar no gasta
  la credencial anterior; si la respuesta se pierde, la que tiene sigue
  valiendo. No añadas un paso que la invalide al renovar.
- **Cerrar sesiones desde el servidor** es por cuenta entera: cada cuenta
  tiene un contador (`users.session_epoch`) que viaja en la credencial;
  sumarle uno deja sin validez todas las anteriores. Lo hacen
  `POST /auth/logout-all` (la propia persona) y
  `python -m scripts.close_sessions --email …` (móvil perdido; sin
  `--apply` solo enseña). No se puede cerrar un solo dispositivo.
- **`JWT_SECRET` no se cambia nunca** cuando ya hay cuentas de verdad:
  cambiarlo cierra la sesión de todo el mundo. Cada entorno tiene la suya.
  Con el valor de ejemplo la API **no arranca** en producción y lo avisa
  en el registro en UAT.
- Una credencial emitida antes de existir el contador vale como 0: nadie
  sale al publicar esto.

## Catálogo de premios

El catálogo es **uno y el mismo para todos los municipios**. Se edita en un
solo sitio, Demo KM0 (CP 00000, partición `is_fake`), con el backoffice y
la cuenta de demostración. Cada municipio real tiene una copia.

- **El administrador de un municipio solo enciende y apaga.** Sobre un
  premio real, `PATCH /rewards/{id}` admite únicamente `status` con
  `active` o `inactive`. Crear, borrar, cambiar puntos, textos, existencias
  o imagen contesta 403 `reward_catalog_locked`. `RewardOut.content_locked`
  se lo dice al backoffice.
- **La copia la hace `scripts/seed_real_rewards.py`** (`--town` o `--all`;
  sin `--apply` solo enseña). Un premio nuevo nace **activo** (con el
  estado que tenga en el catálogo) y el administrador puede apagarlo; uno que ya
  estaba recibe textos, puntos e imagen del catálogo y **conserva su estado
  y sus existencias**; uno que ya no está en el catálogo se borra si nadie
  lo canjeó y, si no, se queda apagado; uno que no viene del catálogo no se
  toca. Mira siempre la salida sin `--apply`: avisa de cada cambio de puntos.
- La copia se reconoce por `rewards.catalog_id`, así que renombrar un
  premio del catálogo renombra sus copias en vez de duplicarlas.
- **Las existencias son de cada municipio** (bajan con cada canje) y no hay
  pantalla que las cambie: `scripts/set_reward_stock.py --town … --reward …
  --stock N` (sin `--apply` solo enseña). Sirve para poner tope a un piloto
  y para reponer. A cero el premio queda agotado; al reponer vuelve a
  ofrecerse, salvo que el administrador lo tenga apagado.
- Las acciones de puntos **no** son del catálogo: cada municipio configura
  las suyas. **Una acción apagada da cero puntos**: el valor por defecto de
  la configuración (`welcome_points`, `invite_*_points`) solo se usa en un
  municipio que nunca tuvo esa acción.

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
