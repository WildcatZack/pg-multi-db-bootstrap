# Postgres Multi-DB Bootstrap (Sidecar)

A lightweight, idempotent sidecar that provisions **multiple PostgreSQL databases** and matching **login roles** at startup. Designed for Docker Compose/Kubernetes “declare and reconcile” workflows—run it every time you start your stack without wiping volumes.

- **Idempotent:** safe to run repeatedly
- **Env-first** with **CLI overrides**
- **Dry-run mode** to preview changes
- **Works remotely:** connect over LAN or via SSH tunnel
- **Small & fast:** Python 3.12 + psycopg (binary wheels)

---

## What it does

Given a list of database names, for each name `X` it:

1. Ensures a role `X` exists (`LOGIN`, password = `POSTGRES_NON_ROOT_PASSWORD`)
2. Ensures database `X` exists and is **owned by** `X`
3. Re-asserts ownership and broad grants on `public` (idempotent)
4. Exits with code 0 upon success

> Convention: **user name == database name** (simple app wiring, easy to reason about).

---

## Environment variables

| Name                         | Required | Default    | Description                                                                                          |
| ---------------------------- | :------: | ---------- | ---------------------------------------------------------------------------------------------------- |
| `POSTGRES_HOST`              |    ✅    | —          | Hostname/IP of the Postgres server (reachable from the container)                                    |
| `POSTGRES_PORT`              |          | `5432`     | Postgres port                                                                                        |
| `POSTGRES_SUPERUSER`         |          | `postgres` | Superuser to connect as                                                                              |
| `POSTGRES_PASSWORD`          |    ✅    | —          | Password for the superuser                                                                           |
| `POSTGRES_DBS`               |    ✅    | —          | Databases to ensure. Comma-separated (`n8n,cloudbeaver`) **or** JSON array (`["n8n","cloudbeaver"]`) |
| `POSTGRES_NON_ROOT_PASSWORD` |    ✅    | —          | Password to set for all created roles (you can rotate later)                                         |
| `POSTGRES_SSLMODE`           |          | `prefer`   | libpq sslmode (`disable`, `prefer`, `require`, etc.)                                                 |
| `BOOTSTRAP_TIMEOUT`          |          | `120`      | Seconds to wait for Postgres readiness                                                               |

### CLI flags (override envs)

`--host`, `--port`, `--superuser`, `--password`, `--dbs`, `--non-root-password`, `--timeout`, `--sslmode`, `--dry-run`, `--ensure-password`

- `--dry-run` → plan only; do not apply changes
- `--ensure-password` → also `ALTER ROLE ... PASSWORD` for existing roles

---

## Quickstart (LAN)

If your Postgres server is listening on `<DB_HOST_IP>:5432`:

```bash
docker run --rm \
  -e POSTGRES_HOST=<DB_HOST_IP> \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_SUPERUSER=postgres \
  -e POSTGRES_PASSWORD=<SUPERUSER_PASSWORD> \
  -e POSTGRES_DBS="n8n,cloudbeaver,analytics" \
  -e POSTGRES_NON_ROOT_PASSWORD=<NON_ROOT_PASSWORD> \
  YOUR_DOCKERHUB_USERNAME/pg-multi-db-bootstrap:0.1.1 --dry-run
```

Remove `--dry-run` to apply changes.

---

## Quickstart (SSH tunnel; no open ports)

Forward server’s 5432 to your local 5433:

```bash
ssh -N -L 5433:127.0.0.1:5432 user@<server>
```

Then from Docker on macOS, use the host gateway:

```bash
docker run --rm \
  -e POSTGRES_HOST=host.docker.internal \
  -e POSTGRES_PORT=5433 \
  -e POSTGRES_SUPERUSER=postgres \
  -e POSTGRES_PASSWORD=<SUPERUSER_PASSWORD> \
  -e POSTGRES_DBS='["n8n","cloudbeaver","analytics"]' \
  -e POSTGRES_NON_ROOT_PASSWORD=<NON_ROOT_PASSWORD> \
  YOUR_DOCKERHUB_USERNAME/pg-multi-db-bootstrap:0.1.1
```

---

## Compose pattern (as a one-shot sidecar)

Make Postgres report healthy, then run the sidecar **once** and exit; your apps depend on both.

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -h 127.0.0.1 -p 5432"]
      interval: 2s
      timeout: 3s
      retries: 30
    volumes:
      - pgdata:/var/lib/postgresql/data
    # ports:
    #   - "5432:5432"  # expose if you want LAN access

  db-bootstrap:
    image: YOUR_DOCKERHUB_USERNAME/pg-multi-db-bootstrap:0.1.1
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: 5432
      POSTGRES_SUPERUSER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DBS: ${POSTGRES_DBS} # e.g. "n8n,cloudbeaver,analytics"
      POSTGRES_NON_ROOT_PASSWORD: ${POSTGRES_NON_ROOT_PASSWORD}
    restart: "no"

  my-app:
    image: my/app:latest
    depends_on:
      - postgres
      - db-bootstrap
    environment:
      DB_HOST: postgres
      DB_PORT: 5432
      DB_NAME: n8n
      DB_USER: n8n
      DB_PASSWORD: ${POSTGRES_NON_ROOT_PASSWORD}

volumes:
  pgdata:
```

> Add new DBs by editing `POSTGRES_DBS` and restarting your stack; the sidecar will create only what’s missing.

---

## Idempotency & password rotation

- Re-runs are safe; it only **creates missing** roles/dbs and re-asserts ownership/grants.
- To **rotate passwords** for existing roles: add `--ensure-password` (or use it in a CI job).
- No dropping of objects or user data.

---

## Exit codes

- `0` success
- `2` configuration/connectivity errors

---

## Versioning & tags

Semantic Versioning: `MAJOR.MINOR.PATCH`.

Recommended Docker tags:

- `:0.1.1` (exact)
- `:0.1` (minor)
- `:latest` (moving)

> Replace `YOUR_DOCKERHUB_USERNAME` with your actual namespace when publishing.

---

## Security notes

- Keep `POSTGRES_PASSWORD` and `POSTGRES_NON_ROOT_PASSWORD` secret (env files, secrets managers).
- Consider using distinct per-DB passwords via future JSON input—planned enhancement.

---

## Troubleshooting

- **Syntax errors around `PASSWORD $1`** → Ensure you're using version **>= 0.1.1** (uses proper SQL literals).
- **Connection refused / timeout** → Verify host/port, healthcheck, firewall, or SSH tunnel.
- **Auth failed** → Confirm the superuser password matches your Postgres container config.

---

## License

MIT — see [LICENSE](./LICENSE).

---

## Credits

Built for repeatable infra: declare DBs once, reconcile every start. PRs welcome.
