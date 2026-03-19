#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${RUN_DIR:-$ROOT_DIR/.run}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"
PID_FILE="${PID_FILE:-$RUN_DIR/laofoye.pid}"
STDOUT_LOG_FILE="${STDOUT_LOG_FILE:-$LOG_DIR/laofoye.out.log}"

mkdir -p "$RUN_DIR" "$LOG_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not found in PATH."
  echo "Install: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${OLD_PID:-}" ]] && kill -0 "$OLD_PID" >/dev/null 2>&1; then
    echo "laofoye is already running (PID: $OLD_PID)."
    echo "Use scripts/stop.sh first if you want to restart."
    exit 0
  fi
  echo "Removing stale PID file: $PID_FILE"
  rm -f "$PID_FILE"
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export EMPRESS_DOWAGER_LOG_FILE="${EMPRESS_DOWAGER_LOG_FILE:-$LOG_DIR/laofoye.app.log}"

cd "$ROOT_DIR"
nohup uv run empress-dowager start >>"$STDOUT_LOG_FILE" 2>&1 &
NEW_PID="$!"
echo "$NEW_PID" >"$PID_FILE"

echo "laofoye started."
echo "PID: $NEW_PID"
echo "PID file: $PID_FILE"
echo "stdout log: $STDOUT_LOG_FILE"
echo "app log: $EMPRESS_DOWAGER_LOG_FILE"
