#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${FLOW_BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${FLOW_BACKEND_PORT:-8000}"
FRONTEND_HOST="${FLOW_FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FLOW_FRONTEND_PORT:-5173}"
DB_PATH="${FLOW_DB_PATH:-$ROOT_DIR/data/flow.sqlite3}"

if [[ "$DB_PATH" != /* ]]; then
  DB_PATH="$ROOT_DIR/$DB_PATH"
fi
mkdir -p "$(dirname "$DB_PATH")"

backend_pid=""
frontend_pid=""
cleanup() {
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
  wait "$backend_pid" 2>/dev/null || true
  wait "$frontend_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(
  cd "$ROOT_DIR/backend"
  FLOW_DB_PATH="$DB_PATH" uv run uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT"
) &
backend_pid=$!

(
  cd "$ROOT_DIR/frontend"
  npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
) &
frontend_pid=$!

echo "Frontend: http://10.97.128.2:${FRONTEND_PORT}/"
echo "Backend:  http://10.97.128.2:${BACKEND_PORT}/docs"
wait -n "$backend_pid" "$frontend_pid"
