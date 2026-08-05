#!/usr/bin/env bash
set -euo pipefail

# Wait for Postgres to be ready
: ${DATABASE_URL:=postgresql+asyncpg://docuser:docpass@db:5432/docdb}

echo "Waiting for Postgres..."
MAX_WAIT=60
i=0
until pg_isready -h ${DB_HOST:-db} -p ${DB_PORT:-5432} -U ${DB_USER:-docuser} || [ $i -ge $MAX_WAIT ]; do
  i=$((i+1))
  sleep 1
done

if [ $i -ge $MAX_WAIT ]; then
  echo "Postgres did not become ready in time" >&2
  exit 1
fi

# Run migrations if alembic present
if [ -f /app/alembic.ini ]; then
  echo "Running alembic upgrade head"
  alembic upgrade head || true
fi

# Start uvicorn
exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
