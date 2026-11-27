# Territorio de pruebas (QA)

El piloto corre en UAT con **una sola base de datos**. Las pruebas
automáticas necesitan escribir (dar de alta vecinos, escanear, canjear) sin
tocar a vecinos reales ni la demo comercial. Para eso existe un territorio
aparte dentro de la misma base de datos, que se puede borrar entero.

## Los tres territorios

| Territorio   | Código postal            | Partición        | Quién escribe                    |
| ------------ | ------------------------ | ---------------- | -------------------------------- |
| Real         | 08380 y los que se creen | `is_fake=false`  | Vecinos, comercios, ayuntamiento |
| Demostración | 00000 «Demo KM0»         | `is_fake=true`   | Presentaciones comerciales       |
| **Pruebas**  | 99999 «[QA] QA KM0»      | `is_fake=true`   | El robot de pruebas              |

Las pruebas nunca escriben en los dos primeros.

## Cómo se reconoce un dato de prueba

Todo lo que crea una prueba cumple las tres:

1. Cuelga de un municipio QA (códigos postales `99990`–`99999`) o de una
   cuenta QA (`qa+loquesea@km0lab.com`).
2. Está en la partición `is_fake`.
3. Su nombre visible empieza por `[QA]`.

Las reglas están en `app/qa.py`.

## Cuentas

Las cuentas `qa+…@km0lab.com` entran con el código fijo de
`LOCAL-ACCOUNTS.md`, **solo** con `ENVIRONMENT=development` o `staging`. En
`production` no existen: el acceso responde 403.

A diferencia de las cuentas de demostración, siguen el alta normal: la
primera vez que entra `qa+nuevo-123@km0lab.com` se crea el vecino, recibe
la bienvenida y, si llega con un enlace de invitación, se abona al que
invitó. Así se prueba el alta de punta a punta sin buzón de correo.

Una cuenta QA no puede salir del territorio: siempre vive en un código
postal 9999x y siempre es `is_fake`.

Cuentas fijas, que crea el sembrado. Las pruebas **solo leen** con ellas;
para escribir crean cuentas nuevas en cada ejecución.

| Cuenta                 | Rol                                  |
| ---------------------- | ------------------------------------ |
| `qa+vecino@km0lab.com` | vecino con 1000 puntos               |
| `qa+comerc@km0lab.com` | comercio («[QA] Forn de proves»)     |
| `qa+admin@km0lab.com`  | admin del municipio QA               |

## Qué hay sembrado

- Municipio «[QA] QA KM0», CP 99999, 20 puntos por escaneo.
- 3 comercios activos con QR fijo: `qa-shop-1`, `qa-shop-2`, `qa-shop-3`.
- 5 premios: vale (50), saldo (80), producto (30), uno inalcanzable y uno
  sin existencias.
- 5 acciones: registro (200), escaneo, invitar vecino (150), invitar
  comercio (500) y una personalizada.
- 1 promoción.

## Comandos

Actúan sobre la base de datos del entorno (la local, salvo que se ejecuten
dentro del servicio de UAT). Ninguno funciona en `production`.

```bash
python -m scripts.seed_qa                  # crea o repara el territorio
python -m scripts.purge_qa                 # ENSEÑA lo que borraría
python -m scripts.purge_qa --apply         # borra lo que crearon las pruebas
python -m scripts.purge_qa --all --apply   # borra el territorio entero
python -m scripts.check_flows_mysql        # flujos completos contra MySQL local
```

`purge_qa` sin `--apply` no cambia nada. Con `--older-than-minutes N` deja
en paz lo creado en los últimos N minutos (una ejecución en curso).

### Los seguros del borrado

Antes del primer `DELETE` comprueba, y si algo falla **no borra nada**:

- Todo municipio con un código postal 9999x se llama `[QA] …` y su slug
  empieza por `qa-`, y no tiene códigos postales fuera de ese rango.
- Todas las filas a borrar (cuentas, comercios, movimientos, escaneos,
  canjes, premios, acciones) son `is_fake`.
- En el borrado total, ninguna cuenta de fuera tiene actividad dentro.

## Desde el robot: `POST /api/v1/qa/prepare`

Borra lo que crearon ejecuciones anteriores y repara el sembrado.

- Cerrado por defecto: responde **404** si `QA_TOKEN` está vacío o el
  entorno es `production`.
- Exige la cabecera `X-QA-Token` con ese valor.
- Las peticiones que traen esa cabecera válida no cuentan para los límites
  por IP (acceso, alta de comercio): una ejecución da de alta una docena de
  vecinos y no debe frenarse ni gastar el cupo de los vecinos reales.
- `?older_than_minutes=120` (por defecto): no toca ejecuciones recientes.
- `?dry_run=true`: solo informa.

Para activarlo en UAT hay que crear la variable `QA_TOKEN` en el servicio
de Railway (un valor largo y aleatorio) y guardar el mismo valor como
secreto en GitHub. No va en el repositorio.

## Pruebas

- `tests/test_qa_territory.py` (pytest, SQLite): reglas, alta con código
  fijo, que no se activa en producción, flujos y seguros del borrado.
- `scripts/check_flows_mysql.py`: lo que SQLite no ve — claves foráneas y
  peticiones simultáneas. Corre en GitHub tras aplicar las migraciones
  desde cero (`.github/workflows/tests.yml`).
