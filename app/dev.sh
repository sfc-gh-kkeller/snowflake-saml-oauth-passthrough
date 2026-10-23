#!/usr/bin/env bash
set -e

PIXI_BIN="$(dirname "$0")/.pixi/envs/default/bin"
PGDATA="$(dirname "$0")/.pgdata"
DB_NAME="nanocortex"

export PATH="$PIXI_BIN:$PATH"

echo "==> Checking PostgreSQL..."
if ! pg_ctl status -D "$PGDATA" &>/dev/null; then
  if [ ! -f "$PGDATA/PG_VERSION" ]; then
    echo "    Initializing postgres cluster..."
    initdb -D "$PGDATA" --username="$USER" --auth=trust --no-instructions
  fi
  echo "    Starting postgres..."
  pg_ctl start -D "$PGDATA" -l "$PGDATA/postgres.log" -w
else
  echo "    Postgres already running."
fi

echo "==> Checking database '$DB_NAME'..."
if ! psql -h localhost -U "$USER" "$DB_NAME" -c "" &>/dev/null; then
  echo "    Creating database..."
  psql -h localhost -U "$USER" postgres -c "CREATE DATABASE $DB_NAME;"
  psql -h localhost -U "$USER" "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;"
  echo "    Running init migrations..."
  python -m backend.app.migrations.init_db
else
  echo "    Database exists."
fi

echo "==> Starting backend (port 9000)..."
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 9000 &
BACKEND_PID=$!

echo "==> Starting frontend (port 9001)..."
(cd "$(dirname "$0")/frontend" && npx vite --host 0.0.0.0 --port 9001) &
FRONTEND_PID=$!

echo ""
echo "  Backend:  http://localhost:9000"
echo "  Frontend: http://localhost:9001"
echo ""
echo "Press Ctrl+C to stop all services."

cleanup() {
  echo ""
  echo "==> Stopping services..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  pg_ctl stop -D "$PGDATA" -m fast 2>/dev/null
  echo "    Done."
}
trap cleanup INT TERM

wait "$BACKEND_PID" "$FRONTEND_PID"
