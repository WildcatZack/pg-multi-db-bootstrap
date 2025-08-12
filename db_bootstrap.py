#!/usr/bin/env python3
"""
Postgres Multi-DB Bootstrap (Sidecar)

Ensures that a declared set of databases and matching login roles exist,
assigns ownership, and applies basic grants. Safe to run repeatedly.
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime

import psycopg
from psycopg import sql

# ---------- Logging ----------

def log(level: str, msg: str):
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"[{level}] {ts} {msg}", flush=True)

def fatal(msg: str, code: int = 2):
    log("ERROR", msg)
    sys.exit(code)

# ---------- Helpers ----------

def env(name: str, default=None):
    v = os.getenv(name, default)
    return v

def parse_dbs(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
            return [str(x).strip() for x in arr if str(x).strip()]
        except Exception as e:
            fatal(f"POSTGRES_DBS looks like JSON but failed to parse: {e}")
    # comma-separated
    return [x.strip() for x in raw.split(",") if x.strip()]

def wait_for_pg(connect_args: dict, timeout: int):
    start = time.time()
    last_err = None
    while time.time() - start <= timeout:
        try:
            with psycopg.connect(**connect_args, dbname="postgres") as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    return
        except Exception as e:
            last_err = e
            time.sleep(1)
    fatal(f"Postgres not ready after {timeout}s: {last_err}")

def role_exists(cur, role: str) -> bool:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s;", (role,))
    return cur.fetchone() is not None

def db_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (name,))
    return cur.fetchone() is not None

def ensure_role(cur, role: str, password: str, dry_run: bool, ensure_password: bool):
    if role_exists(cur, role):
        log("INFO", f"role exists: {role}")
        if ensure_password:
            if dry_run:
                log("INFO", f"[dry-run] would ALTER ROLE {role} WITH PASSWORD *****")
            else:
                q = sql.SQL("ALTER ROLE {} WITH PASSWORD {};").format(
                    sql.Identifier(role),
                    sql.Literal(password)
                )
                cur.execute(q)
                log("INFO", f"password ensured for role: {role}")
        return

    if dry_run:
        log("INFO", f"[dry-run] would CREATE ROLE {role} LOGIN PASSWORD *****")
        return

    # NOTE: Postgres doesn't accept bind params for PASSWORD; use a literal
    q = sql.SQL("CREATE ROLE {} LOGIN PASSWORD {};").format(
        sql.Identifier(role),
        sql.Literal(password)
    )
    cur.execute(q)
    log("INFO", f"role created: {role}")

def ensure_db(super_conn, super_cur, name: str, owner: str, dry_run: bool):
    if not db_exists(super_cur, name):
        if dry_run:
            log("INFO", f"[dry-run] would CREATE DATABASE {name} OWNER {owner}")
        else:
            # CREATE DATABASE must be outside a transaction
            super_conn.autocommit = True
            q = sql.SQL("CREATE DATABASE {} OWNER {};").format(
                sql.Identifier(name),
                sql.Identifier(owner)
            )
            super_cur.execute(q)
            log("INFO", f"database created: {name} (owner {owner})")
    else:
        log("INFO", f"database exists: {name}")
        if dry_run:
            log("INFO", f"[dry-run] would ALTER DATABASE {name} OWNER TO {owner}")
        else:
            q = sql.SQL("ALTER DATABASE {} OWNER TO {};").format(
                sql.Identifier(name),
                sql.Identifier(owner)
            )
            super_cur.execute(q)

    if dry_run:
        log("INFO", f"[dry-run] would set schema ownership and grants in {name}")
        return

    # Connect to target DB to assert schema/grants (autocommit OK)
    with psycopg.connect(
        host=super_conn.info.host,
        port=super_conn.info.port,
        user=super_conn.info.user,
        password=super_conn.info.password,
        dbname=name,
        connect_timeout=10
    ) as dbconn:
        dbconn.autocommit = True
        with dbconn.cursor() as cur:
            # Ownership and permissive grants for the owner on public schema
            cur.execute(sql.SQL("ALTER SCHEMA public OWNER TO {};").format(sql.Identifier(owner)))
            cur.execute(sql.SQL("GRANT ALL PRIVILEGES ON SCHEMA public TO {};").format(sql.Identifier(owner)))
            # Existing objects in schema
            cur.execute(sql.SQL("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {};").format(sql.Identifier(owner)))
            cur.execute(sql.SQL("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {};").format(sql.Identifier(owner)))
            cur.execute(sql.SQL("GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO {};").format(sql.Identifier(owner)))
    log("INFO", f"ownership & grants ensured in db: {name}")

def sanitize_names(names: list[str]) -> list[str]:
    seen = set()
    out = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        if not n.replace("_", "").isalnum():
            log("WARN", f"'{n}' contains characters outside [A-Za-z0-9_] and will be quoted; ensure client tooling supports quoted identifiers.")
    return out

# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description="Provision multiple Postgres databases and roles (idempotent sidecar).")
    parser.add_argument("--host", default=env("POSTGRES_HOST"), help="Postgres host (env: POSTGRES_HOST)")
    parser.add_argument("--port", type=int, default=int(env("POSTGRES_PORT", "5432")), help="Postgres port (env: POSTGRES_PORT, default 5432)")
    parser.add_argument("--superuser", default=env("POSTGRES_SUPERUSER", "postgres"), help="Superuser name (env: POSTGRES_SUPERUSER, default postgres)")
    parser.add_argument("--password", default=env("POSTGRES_PASSWORD"), help="Superuser password (env: POSTGRES_PASSWORD)")
    parser.add_argument("--dbs", default=env("POSTGRES_DBS"), help="DB list (comma-separated or JSON) (env: POSTGRES_DBS)")
    parser.add_argument("--non-root-password", dest="nonroot_pw", default=env("POSTGRES_NON_ROOT_PASSWORD"), help="Password for all created roles (env: POSTGRES_NON_ROOT_PASSWORD)")
    parser.add_argument("--timeout", type=int, default=int(env("BOOTSTRAP_TIMEOUT", "120")), help="Seconds to wait for Postgres readiness (env: BOOTSTRAP_TIMEOUT, default 120)")
    parser.add_argument("--sslmode", default=env("POSTGRES_SSLMODE", "prefer"), help="Postgres sslmode (env: POSTGRES_SSLMODE, default prefer)")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; do not apply changes")
    parser.add_argument("--ensure-password", action="store_true", help="Also ALTER ROLE ... PASSWORD for existing roles")

    args = parser.parse_args()

    missing = []
    for k in ("host", "password", "dbs", "nonroot_pw"):
        if not getattr(args, k):
            missing.append(k)
    if missing:
        fatal(f"Missing required configuration: {', '.join(missing)}. "
              f"Use envs (POSTGRES_HOST, POSTGRES_PASSWORD, POSTGRES_DBS, POSTGRES_NON_ROOT_PASSWORD) or CLI flags.")

    db_names = sanitize_names(parse_dbs(args.dbs))
    if not db_names:
        fatal("No databases provided. Set POSTGRES_DBS or --dbs.")

    connect_args = dict(
        host=args.host,
        port=args.port,
        user=args.superuser,
        password=args.password,
        target_session_attrs="read-write",
        connect_timeout=10,
        sslmode=args.sslmode
    )

    log("INFO", f"connecting to {args.host}:{args.port} as {args.superuser} (timeout={args.timeout}s, dry_run={args.dry_run})")
    wait_for_pg(connect_args, args.timeout)
    log("INFO", "postgres is ready")

    # superuser connection
    with psycopg.connect(**connect_args, dbname="postgres") as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for name in db_names:
                user = name  # convention: user == db name
                ensure_role(cur, user, args.nonroot_pw, args.dry_run, args.ensure_password)
                ensure_db(conn, cur, name, user, args.dry_run)

    log("INFO", "bootstrap complete")
    return 0

if __name__ == "__main__":
    sys.exit(main())
