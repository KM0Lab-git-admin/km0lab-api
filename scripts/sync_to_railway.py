"""Copia la BD MySQL local a Railway (esquema + datos) con pymysql.

Uso:
    python scripts/sync_to_railway.py --target "mysql://USER:PASS@HOST:PORT/DB"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

# Permite ejecutar: python scripts/sync_to_railway.py ...
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pymysql
from pymysql.constants import CLIENT

from app.config import get_settings


def parse_db_url(url: str) -> dict:
    if "+" in url.split("://", 1)[0]:
        scheme, rest = url.split("://", 1)
        url = f"{scheme.split('+', 1)[0]}://{rest}"
    p = urlparse(url)
    if p.scheme != "mysql" or not p.hostname or not p.path:
        raise ValueError(f"URL no válida: {url!r}")
    return {
        "host": p.hostname,
        "port": p.port or 3306,
        "user": unquote(p.username or ""),
        "password": unquote(p.password or ""),
        "database": p.path.lstrip("/"),
        "charset": "utf8mb4",
        "client_flag": CLIENT.MULTI_STATEMENTS,
    }


def connect(creds: dict):
    return pymysql.connect(**creds, cursorclass=pymysql.cursors.Cursor)


def list_tables(cur) -> list[str]:
    cur.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
    return [row[0] for row in cur.fetchall()]


def dump_create_table(cur, table: str) -> str:
    cur.execute(f"SHOW CREATE TABLE `{table}`")
    return cur.fetchone()[1]


def dump_rows(cur, table: str) -> list[tuple]:
    cur.execute(f"SELECT * FROM `{table}`")
    return cur.fetchall()


def column_names(cur, table: str) -> list[str]:
    cur.execute(f"SHOW COLUMNS FROM `{table}`")
    return [row[0] for row in cur.fetchall()]


def sync(local: dict, target: dict) -> None:
    print("Leyendo tablas locales...")
    with connect(local) as src, src.cursor() as scur:
        tables = [t for t in list_tables(scur) if t != "alembic_version"]
        print(f"  {len(tables)} tablas: {', '.join(tables)}")

        payloads: list[tuple[str, str, list[str], list[tuple]]] = []
        for table in tables:
            create_sql = dump_create_table(scur, table)
            cols = column_names(scur, table)
            rows = dump_rows(scur, table)
            payloads.append((table, create_sql, cols, rows))
            print(f"  · {table}: {len(rows)} filas")

    print("Escribiendo en Railway (reemplaza tablas existentes)...")
    with connect(target) as dst, dst.cursor() as dcur:
        dcur.execute("SET FOREIGN_KEY_CHECKS=0")
        for table, create_sql, cols, rows in payloads:
            dcur.execute(f"DROP TABLE IF EXISTS `{table}`")
            dcur.execute(create_sql)
            if rows:
                placeholders = ", ".join(["%s"] * len(cols))
                col_list = ", ".join(f"`{c}`" for c in cols)
                sql = f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders})"
                dcur.executemany(sql, rows)
            print(f"  ✓ {table} ({len(rows)} filas)")
        dcur.execute("SET FOREIGN_KEY_CHECKS=1")
        dst.commit()

    print("Sellando Alembic en head...")
    env = os.environ.copy()
    env.update(
        DB_HOST=target["host"],
        DB_PORT=str(target["port"]),
        DB_USER=target["user"],
        DB_PASSWORD=target["password"],
        DB_NAME=target["database"],
    )
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"alembic stamp head falló:\n{proc.stderr or proc.stdout}")
    print("Listo. Redeploya km0lab-api en Railway.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=os.environ.get("RAILWAY_DB_URL"),
        help="URL pública MySQL de Railway, o variable RAILWAY_DB_URL",
    )
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if not args.target:
        sys.exit(
            "Falta la URL de Railway.\n"
            "En Railway → MySQL → Variables → copia MYSQL_URL "
            "(o MYSQLHOST/USER/PASSWORD/PORT/DATABASE) y ejecuta:\n"
            '  python scripts/sync_to_railway.py --target "mysql://USER:PASS@HOST:PORT/DB"'
        )

    s = get_settings()
    local = {
        "host": s.db_host,
        "port": s.db_port,
        "user": s.db_user,
        "password": s.db_password,
        "database": s.db_name,
        "charset": "utf8mb4",
    }
    target = parse_db_url(args.target)

    if target["host"] in {"localhost", "127.0.0.1", "mysql"}:
        sys.exit(
            "Refusing to run against a local host. This script only replaces "
            "a remote Railway DB; it never wipes your local MySQL."
        )

    print(f"Origen : {local['user']}@{local['host']}/{local['database']}")
    print(f"Destino: {target['user']}@{target['host']}/{target['database']}")
    print("Esto BORRA y reemplaza las tablas del destino (Railway).")
    print("La BD local NO se modifica.")
    if not args.yes:
        if input("Escribe 'si' para continuar: ").strip().lower() not in {
            "si",
            "sí",
            "y",
            "yes",
        }:
            sys.exit("Cancelado.")

    sync(local, target)


if __name__ == "__main__":
    main()
