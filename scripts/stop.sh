#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${RUN_DIR:-$ROOT_DIR/.run}"
PID_FILE="${PID_FILE:-$RUN_DIR/laofoye.pid}"
WAIT_SECONDS="${WAIT_SECONDS:-20}"

stop_langfuse_if_needed() {
  if [[ "${STOP_LANGFUSE:-0}" == "1" ]]; then
    echo "STOP_LANGFUSE=1 -> stopping bundled Langfuse stack ..."
    "$ROOT_DIR/scripts/langfuse-down.sh"
  fi
}

if [[ ! -f "$PID_FILE" ]]; then
  echo "PID file not found: $PID_FILE"
  echo "laofoye may already be stopped."
  stop_langfuse_if_needed
  exit 0
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -z "${PID:-}" ]]; then
  echo "PID file is empty, removing stale file."
  rm -f "$PID_FILE"
  stop_langfuse_if_needed
  exit 0
fi

if ! kill -0 "$PID" >/dev/null 2>&1; then
  echo "Process $PID is not running, removing stale PID file."
  rm -f "$PID_FILE"
  stop_langfuse_if_needed
  exit 0
fi

echo "Stopping laofoye (PID: $PID) ..."
kill "$PID" >/dev/null 2>&1 || true

for _ in $(seq 1 "$WAIT_SECONDS"); do
  if ! kill -0 "$PID" >/dev/null 2>&1; then
    rm -f "$PID_FILE"
    echo "Stopped gracefully."
    stop_langfuse_if_needed
    exit 0
  fi
  sleep 1
done

echo "Process still alive after ${WAIT_SECONDS}s, forcing kill -9 ..."
kill -9 "$PID" >/dev/null 2>&1 || true
rm -f "$PID_FILE"
echo "Stopped forcefully."
stop_langfuse_if_needed
