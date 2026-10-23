#!/usr/bin/env bash
# Start the SSO passthrough demo: local postgres, built frontend, backend on :9000.
set -euo pipefail
cd "$(dirname "$0")"
pixi install >/dev/null
export PATH="$PWD/.pixi/envs/default/bin:$PATH"

if [ ! -f .pgdata/PG_VERSION ]; then
  initdb -D .pgdata --username="$USER" --auth=trust --no-instructions >/dev/null
fi
pg_ctl status -D .pgdata >/dev/null 2>&1 || pg_ctl start -D .pgdata -l .pgdata/postgres.log -w >/dev/null
if ! psql -h localhost -U "$USER" nanocortex -c "" >/dev/null 2>&1; then
  psql -h localhost -U "$USER" postgres -c "CREATE DATABASE nanocortex;" >/dev/null
  psql -h localhost -U "$USER" nanocortex -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
  python -m backend.app.migrations.init_db >/dev/null
fi

(cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund >/dev/null; } && npx vite build --outDir ../backend/static --emptyOutDir >/dev/null)
echo "SSO passthrough demo on http://localhost:9000"
exec uvicorn backend.app.main:app --host 127.0.0.1 --port 9000
