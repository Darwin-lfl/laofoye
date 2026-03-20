#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${LANGFUSE_COMPOSE_FILE:-$ROOT_DIR/docker-compose.langfuse.yml}"
ENV_FILE="${LANGFUSE_ENV_FILE:-$ROOT_DIR/.env.langfuse}"
ENV_EXAMPLE_FILE="$ROOT_DIR/.env.langfuse.example"
PROJECT_NAME="${LANGFUSE_COMPOSE_PROJECT_NAME:-superlabor-langfuse}"
AUTO_INIT_ENV="${LANGFUSE_AUTO_INIT_ENV:-1}"

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

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ "$AUTO_INIT_ENV" == "1" ]] && [[ -f "$ENV_EXAMPLE_FILE" ]]; then
    cp "$ENV_EXAMPLE_FILE" "$ENV_FILE"
    echo "Created $ENV_FILE from template."
    echo "Please review secrets in $ENV_FILE before production use."
  else
    echo "Env file not found: $ENV_FILE"
    echo "Proceeding with compose defaults (development only)."
  fi
fi

COMPOSE_ARGS=(-p "$PROJECT_NAME" -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  COMPOSE_ARGS+=(--env-file "$ENV_FILE")
fi

docker compose "${COMPOSE_ARGS[@]}" up -d

echo "Langfuse is starting."
echo "Project: $PROJECT_NAME"
echo "Web UI: http://localhost:3000"
echo "Use scripts/langfuse-down.sh to stop."
