#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

printf 'Checking prerequisites only; no packages or services will be installed.\n'
./scripts/validate.sh

failed=0
for command_name in docker nvidia-smi; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'BLOCKED: command not available: %s\n' "$command_name" >&2
    failed=1
  fi
done

if command -v docker >/dev/null 2>&1 &&
   ! docker compose version >/dev/null 2>&1; then
  printf 'BLOCKED: Docker Compose plugin is unavailable or inaccessible.\n' >&2
  failed=1
fi

if [[ ! -f sha256sums-2026-07-29.txt ]]; then
  printf 'BLOCKED: model checksum input is missing.\n' >&2
  failed=1
fi

if grep -Fq 'evidence_valid: false' operator-evidence/worker-node.txt; then
  printf 'BLOCKED: worker-node evidence is still a placeholder.\n' >&2
  failed=1
fi

if grep -Eq '(^|: )[\"'\'']?replace_me|: null$|status: not_configured|status: not_provided' \
  operator_inputs.yaml; then
  printf 'BLOCKED: operator_inputs.yaml still contains blocking placeholders.\n' >&2
  failed=1
fi

if (( failed != 0 )); then
  printf 'Bootstrap readiness check FAILED; nothing was installed or changed.\n' >&2
  exit 1
fi

printf 'Prerequisite checks passed; bootstrap still performs no installation.\n'
