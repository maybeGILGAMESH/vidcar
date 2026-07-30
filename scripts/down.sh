#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

compose_file="infra/compose/compose.yaml"

if ! command -v docker >/dev/null 2>&1; then
  printf 'BLOCKED: Docker is not installed; stack state cannot be verified.\n' >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  printf 'BLOCKED: Docker Compose is unavailable; stack state cannot be verified.\n' >&2
  exit 1
fi

if [[ ! -f "$compose_file" ]]; then
  printf 'BLOCKED: %s is not implemented; nothing was claimed stopped.\n' "$compose_file" >&2
  exit 1
fi

docker compose -f "$compose_file" down
printf 'Compose stack stopped. Named volumes were preserved.\n'
