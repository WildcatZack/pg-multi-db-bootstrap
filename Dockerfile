FROM python:3.12-slim

LABEL maintainer="YOUR NAME <you@example.com>" \
      org.opencontainers.image.title="Postgres Multi-DB Bootstrap" \
      org.opencontainers.image.description="Idempotent sidecar that provisions multiple Postgres databases and roles on startup." \
      org.opencontainers.image.source="https://github.com/YOUR_GITHUB/pg-multi-db-bootstrap" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install Python deps. psycopg[binary] bundles libpq, so no system libs needed.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir "psycopg[binary]==3.2.*"

# Copy version and app
COPY VERSION /app/VERSION
COPY db_bootstrap.py /app/db_bootstrap.py

# One-shot job: run the bootstrapper and exit
ENTRYPOINT ["python", "/app/db_bootstrap.py"]
