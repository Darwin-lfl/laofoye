#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${LANGFUSE_COMPOSE_FILE:-$ROOT_DIR/docker-compose.langfuse.yml}"
ENV_FILE="${LANGFUSE_ENV_FILE:-$ROOT_DIR/.env.langfuse}"
PROJECT_NAME="${LANGFUSE_COMPOSE_PROJECT_NAME:-superlabor-langfuse}"
REMOVE_VOLUMES="${LANGFUSE_REMOVE_VOLUMES:-0}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but not found in PATH."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is required but unavailable."
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Compose file not found: $COMPOSE_FILE"
  exit 1
fi

COMPOSE_ARGS=(-p "$PROJECT_NAME" -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  COMPOSE_ARGS+=(--env-file "$ENV_FILE")
fi

DOWN_ARGS=(down)
if [[ "$REMOVE_VOLUMES" == "1" ]]; then
  DOWN_ARGS+=(--volumes)
fi

docker compose "${COMPOSE_ARGS[@]}" "${DOWN_ARGS[@]}"

echo "Langfuse stopped (project: $PROJECT_NAME)."
if [[ "$REMOVE_VOLUMES" == "1" ]]; then
  echo "Volumes removed."
fi
