"""Descarga los datos de UNA población de Railway/UAT a la BD local.

Flujo Railway -> local (NUNCA escribe en Railway). Pensado para probar en
local cambios del Back Office con datos reales de UAT.

Ámbito de la población (town): towns, town_media, town_postal_codes, shops
(+ shop_media, promotions), point_actions, rewards (+ reward_media,
reward_shops), users (por CP de la población o tienda de la población),
shop_payments, redemptions (+ redemption_events), points_transactions,
qr_scans y el catálogo global shop_categories.

Estrategia: borra en local SOLO las filas del ámbito de esa población y
reinserta las de Railway (las PKs son UUIDs, no hace falta remapear IDs).
No toca datos de otras poblaciones. otp_codes no se copian (son transitorios
de login).

Uso:
    python scripts/pull_from_railway.py --postal-code 08380 --dry-run
    python scripts/pull_from_railway.py --postal-code 08380 --yes
    python scripts/pull_from_railway.py --town "Malgrat de Mar" --yes
    python scripts/pull_from_railway.py --town-id <uuid> --yes

Origen: --source mysql://USER:PASS@HOST:PORT/DB o env RAILWAY_DB_URL
(la misma URL pública de Railway -> MySQL -> Variables).
Destino: la BD local según .env (DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Permite ejecutar: python scripts/pull_from_railway.py ...
_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
for p in (str(_SCRIPTS), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pymysql

from sync_to_railway import parse_db_url  # helper compartido

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.config import get_settings

HOSTS_LOCALES = {"localhost", "127.0.0.1", "mysql"}


def connect(creds: dict):
    """Conexión con cursor de diccionarios (el connect de sync_to_railway
    usa tuplas; aquí trabajamos por nombre de columna)."""
    return pymysql.connect(**creds, cursorclass=pymysql.cursors.DictCursor)


def _in_clause(column: str, ids: list[str] | set[str]) -> tuple[str, tuple]:
    """'column IN (%s,%s)' + params. Devuelve ('1=0', ()) si está vacío."""
    ids = sorted(ids)
    if not ids:
        return "1=0", ()
    marks = ", ".join(["%s"] * len(ids))
    return f"{column} IN ({marks})", tuple(ids)


def fetch_all(cur, sql: str, params=()) -> list[dict]:
    cur.execute(sql, params)
    return list(cur.fetchall())


def fetch_ids(cur, sql: str, column: str, params=()) -> set[str]:
    return {r[column] for r in fetch_all(cur, sql, params)}


def insert_rows(cur, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    col_list = ", ".join(f"`{c}`" for c in cols)
    marks = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO `{table}` ({col_list}) VALUES ({marks})"
    cur.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])


def upsert_rows(cur, table: str, rows: list[dict], pk: str) -> None:
    """INSERT ... ON DUPLICATE KEY UPDATE (para catálogos globales que ya
    existen en local, p.ej. shop_categories)."""
    if not rows:
        return
    cols = list(rows[0].keys())
    col_list = ", ".join(f"`{c}`" for c in cols)
    marks = ", ".join(["%s"] * len(cols))
    updates = ", ".join(f"`{c}`=VALUES(`{c}`)" for c in cols if c != pk)
    sql = (f"INSERT INTO `{table}` ({col_list}) VALUES ({marks}) "
           f"ON DUPLICATE KEY UPDATE {updates}")
    cur.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])


# ---------------------------------------------------------------------------
# Resolución de la población en el ORIGEN
# ---------------------------------------------------------------------------

def resolve_town_id(src, args) -> str:
    if args.town_id:
        row = fetch_all(src, "SELECT id, name FROM towns WHERE id=%s",
                        (args.town_id,))
        if not row:
            sys.exit(f"town_id no encontrado en Railway: {args.town_id}")
        return row[0]["id"]
    if args.postal_code:
        row = fetch_all(
            src,
            "SELECT town_id FROM town_postal_codes WHERE postal_code=%s",
            (args.postal_code.strip(),),
        )
        if not row:
            sys.exit(f"CP {args.postal_code} no existe en Railway "
                     "(town_postal_codes)")
        return row[0]["town_id"]
    # --town: por nombre o slug
    row = fetch_all(src,
                    "SELECT id FROM towns WHERE name=%s OR slug=%s LIMIT 1",
                    (args.town, args.town))
    if not row:
        sys.exit(f"Población no encontrada en Railway: {args.town!r}")
    return row[0]["id"]


# ---------------------------------------------------------------------------
# Lectura del ámbito en el ORIGEN (Railway, solo lectura)
# ---------------------------------------------------------------------------

def read_scope(src, town_id: str) -> dict[str, list[dict]]:
    scope: dict[str, list[dict]] = {}
    scope["towns"] = fetch_all(src, "SELECT * FROM towns WHERE id=%s", (town_id,))
    scope["town_media"] = fetch_all(
        src, "SELECT * FROM town_media WHERE town_id=%s", (town_id,))
    scope["town_postal_codes"] = fetch_all(
        src, "SELECT * FROM town_postal_codes WHERE town_id=%s", (town_id,))

    cps = {r["postal_code"] for r in scope["town_postal_codes"]}
    shops = fetch_all(src, "SELECT * FROM shops WHERE town_id=%s", (town_id,))
    scope["shops"] = shops
    shop_ids = {s["id"] for s in shops}
    shop_in, shop_params = _in_clause("shop_id", shop_ids)

    scope["shop_media"] = fetch_all(
        src, f"SELECT * FROM shop_media WHERE {shop_in}", shop_params)
    scope["promotions"] = fetch_all(
        src, f"SELECT * FROM promotions WHERE {shop_in}", shop_params)
    scope["point_actions"] = fetch_all(
        src, "SELECT * FROM point_actions WHERE town_id=%s", (town_id,))

    rewards = fetch_all(src, "SELECT * FROM rewards WHERE town_id=%s", (town_id,))
    scope["rewards"] = rewards
    reward_ids = {r["id"] for r in rewards}
    reward_in, reward_params = _in_clause("reward_id", reward_ids)
    scope["reward_media"] = fetch_all(
        src, f"SELECT * FROM reward_media WHERE {reward_in}", reward_params)
    scope["reward_shops"] = fetch_all(
        src, f"SELECT * FROM reward_shops WHERE {reward_in}", reward_params)

    # Usuarios: CP de la población o merchant de una tienda de la población
    cp_in, cp_params = _in_clause("postal_code", cps)
    shopid_in, shopid_params = _in_clause("shop_id", shop_ids)
    users = fetch_all(
        src, f"SELECT * FROM users WHERE {cp_in} OR {shopid_in}",
        cp_params + shopid_params)
    scope["users"] = users
    user_ids = {u["id"] for u in users}

    scope["shop_payments"] = fetch_all(
        src, "SELECT * FROM shop_payments WHERE town_id=%s", (town_id,))
    redemptions = fetch_all(
        src, "SELECT * FROM redemptions WHERE town_id=%s", (town_id,))
    scope["redemptions"] = redemptions
    red_ids = {r["id"] for r in redemptions}
    red_in, red_params = _in_clause("redemption_id", red_ids)
    scope["redemption_events"] = fetch_all(
        src, f"SELECT * FROM redemption_events WHERE {red_in}", red_params)

    user_in, user_params = _in_clause("user_id", user_ids)
    scope["points_transactions"] = fetch_all(
        src,
        f"SELECT * FROM points_transactions WHERE town_id=%s OR {user_in}",
        (town_id,) + user_params)
    scope["qr_scans"] = fetch_all(
        src,
        f"SELECT * FROM qr_scans WHERE {user_in} OR {shopid_in}",
        user_params + shopid_params)

    # Catálogo global (shops.categories referencia slugs por JSON, sin FK)
    scope["shop_categories"] = fetch_all(src, "SELECT * FROM shop_categories")
    return scope


# ---------------------------------------------------------------------------
# Borrado del ámbito en el DESTINO (local) — hijos antes que padres
# ---------------------------------------------------------------------------

def delete_scope(dst, town_id: str) -> dict[str, int]:
    deleted: dict[str, int] = {}

    def _delete(table: str, sql: str, params=()) -> None:
        cur_count = dst.execute(sql, params)
        deleted[table] = deleted.get(table, 0) + (cur_count or 0)

    cps = fetch_ids(dst,
                    "SELECT postal_code FROM town_postal_codes WHERE town_id=%s",
                    "postal_code", (town_id,))
    shop_ids = fetch_ids(dst, "SELECT id FROM shops WHERE town_id=%s",
                         "id", (town_id,))
    cp_in, cp_params = _in_clause("postal_code", cps)
    shop_in, shop_params = _in_clause("shop_id", shop_ids)
    user_ids = fetch_ids(
        dst, f"SELECT id FROM users WHERE {cp_in} OR {shop_in}",
        "id", cp_params + shop_params)
    reward_ids = fetch_ids(dst, "SELECT id FROM rewards WHERE town_id=%s",
                           "id", (town_id,))
    red_ids = fetch_ids(dst, "SELECT id FROM redemptions WHERE town_id=%s",
                        "id", (town_id,))

    red_in, red_params = _in_clause("redemption_id", red_ids)
    _delete("redemption_events",
            f"DELETE FROM redemption_events WHERE {red_in}", red_params)
    _delete("redemptions", "DELETE FROM redemptions WHERE town_id=%s", (town_id,))

    user_in, user_params = _in_clause("user_id", user_ids)
    _delete("points_transactions",
            f"DELETE FROM points_transactions WHERE town_id=%s OR {user_in}",
            (town_id,) + user_params)
    shopid_in, shopid_params = _in_clause("shop_id", shop_ids)
    _delete("qr_scans",
            f"DELETE FROM qr_scans WHERE {user_in} OR {shopid_in}",
            user_params + shopid_params)

    reward_in, reward_params = _in_clause("reward_id", reward_ids)
    _delete("reward_shops",
            f"DELETE FROM reward_shops WHERE {reward_in} OR {shopid_in}",
            reward_params + shopid_params)
    _delete("reward_media", f"DELETE FROM reward_media WHERE {reward_in}",
            reward_params)
    _delete("rewards", "DELETE FROM rewards WHERE town_id=%s", (town_id,))
    _delete("point_actions", "DELETE FROM point_actions WHERE town_id=%s",
            (town_id,))
    _delete("promotions", f"DELETE FROM promotions WHERE {shop_in}", shop_params)
    _delete("shop_media", f"DELETE FROM shop_media WHERE {shop_in}", shop_params)
    _delete("shop_payments", "DELETE FROM shop_payments WHERE town_id=%s",
            (town_id,))

    userid_in, userid_params = _in_clause("id", user_ids)
    _delete("users", f"DELETE FROM users WHERE {userid_in}", userid_params)
    _delete("shops", "DELETE FROM shops WHERE town_id=%s", (town_id,))
    _delete("town_media", "DELETE FROM town_media WHERE town_id=%s", (town_id,))
    _delete("town_postal_codes",
            "DELETE FROM town_postal_codes WHERE town_id=%s", (town_id,))
    _delete("towns", "DELETE FROM towns WHERE id=%s", (town_id,))
    return deleted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

INSERT_ORDER = [
    "towns", "town_postal_codes", "town_media", "shop_categories",
    "shops", "shop_media", "promotions", "point_actions",
    "rewards", "reward_media", "reward_shops", "users",
    "shop_payments", "redemptions", "redemption_events",
    "points_transactions", "qr_scans",
]


def pull(args) -> None:
    s = get_settings()
    local = {
        "host": s.db_host, "port": s.db_port, "user": s.db_user,
        "password": s.db_password, "database": s.db_name, "charset": "utf8mb4",
    }
    source_url = args.source or os.environ.get("RAILWAY_DB_URL")
    if not source_url:
        sys.exit("Falta el origen. Usa --source mysql://... o define "
                 "RAILWAY_DB_URL (Railway -> MySQL -> Variables -> URL pública).")
    remote = parse_db_url(source_url)

    if remote["host"] in HOSTS_LOCALES:
        sys.exit("El origen parece local. Este script solo LEE de Railway.")
    if local["host"] not in HOSTS_LOCALES:
        sys.exit(f"El destino no es local ({local['host']}). Abortando: "
                 "este script NUNCA escribe fuera de tu MySQL local.")
    if (remote["host"], remote["port"], remote["database"]) == \
       (local["host"], local["port"], local["database"]):
        sys.exit("Origen y destino son la misma BD. Abortando.")

    print(f"Origen (solo lectura): {remote['user']}@{remote['host']}:{remote['port']}/{remote['database']}")
    print(f"Destino (escritura):   {local['user']}@{local['host']}:{local['port']}/{local['database']}")

    conn_r = connect(remote)
    conn_l = connect(local)
    try:
        with conn_r.cursor() as src:
            town_id = resolve_town_id(src, args)
            town = fetch_all(src, "SELECT name, slug FROM towns WHERE id=%s",
                             (town_id,))[0]
            print(f"Población: {town['name']} (slug={town['slug']}, id={town_id})")
            scope = read_scope(src, town_id)

        total = sum(len(v) for v in scope.values())
        for table in INSERT_ORDER:
            print(f"  · {table}: {len(scope.get(table, []))} filas en Railway")
        print(f"  TOTAL: {total} filas")

        if args.dry_run:
            print("DRY-RUN: no se escribe nada en local.")
            return

        if not args.yes:
            resp = input(
                "Esto BORRA en local las filas de esa población y las "
                "reemplaza con las de Railway. Escribe 'si' para continuar: "
            ).strip().lower()
            if resp not in {"si", "sí", "y", "yes"}:
                sys.exit("Cancelado.")

        with conn_l.cursor() as dst:
            dst.execute("SET FOREIGN_KEY_CHECKS=0")
            deleted = delete_scope(dst, town_id)
            for table in INSERT_ORDER:
                if table == "shop_categories":
                    # Catálogo global compartido entre poblaciones: upsert
                    upsert_rows(dst, table, scope.get(table, []), pk="slug")
                else:
                    insert_rows(dst, table, scope.get(table, []))
            dst.execute("SET FOREIGN_KEY_CHECKS=1")
        conn_l.commit()

        resumen_del = ", ".join(f"{t}={n}" for t, n in deleted.items() if n)
        print(f"Borrado local previo: {resumen_del or 'nada (la población no existía)'}")
        print(f"OK: población '{town['name']}' volcada de Railway a local "
              f"({total} filas).")
    except Exception:
        conn_l.rollback()
        raise
    finally:
        conn_r.close()
        conn_l.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--postal-code", default=None,
                       help="CP de la población (ej. 08380; 00000 = Demo KM0)")
    grupo.add_argument("--town", default=None,
                       help="Nombre o slug de la población (ej. 'Malgrat de Mar')")
    grupo.add_argument("--town-id", default=None, help="UUID de la población")
    ap.add_argument("--source", default=None,
                    help="URL pública MySQL de Railway (o env RAILWAY_DB_URL)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Solo lee de Railway y muestra conteos; no escribe en local")
    ap.add_argument("--yes", action="store_true", help="No pedir confirmación")
    args = ap.parse_args()
    pull(args)


if __name__ == "__main__":
    main()
