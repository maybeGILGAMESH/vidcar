#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

required_files=(
  README.md .gitignore .env.example Makefile operator_inputs.yaml
  agent_implementation_brief.md human_operator_setup.md
  "agent_implementation_brief (1).md" "human_operator_setup (1).md"
  docs/implementation_plan.md docs/architecture_decisions.md
  docs/assumptions_and_blockers.md docs/acceptance_tests.md
  docs/vehicle_size_taxonomy.md operator-evidence/main-node.txt
  operator-evidence/worker-node.txt scripts/bootstrap.sh scripts/validate.sh
  scripts/up.sh scripts/down.sh scripts/smoke.sh
)

required_dirs=(
  apps/web apps/mobile apps/api
  services/scheduler services/probe-worker services/gpu-worker
  services/result-writer services/maintenance services/external-db-adapter
  packages/contracts packages/schemas packages/model-manifest
  packages/api-client packages/common
  infra/compose infra/nginx infra/postgres infra/rabbitmq infra/keycloak
  infra/monitoring infra/storage models/manifests models/validation migrations
  tests/unit tests/integration tests/recovery tests/load tests/fixtures
)

failed=0
for path in "${required_files[@]}"; do
  if [[ ! -f "$path" ]]; then
    printf 'ERROR: required file missing: %s\n' "$path" >&2
    failed=1
  fi
done

for path in "${required_dirs[@]}"; do
  if [[ ! -d "$path" ]]; then
    printf 'ERROR: required directory missing: %s\n' "$path" >&2
    failed=1
  fi
done

for script in scripts/{bootstrap,validate,up,down,smoke}.sh; do
  if [[ ! -x "$script" ]]; then
    printf 'ERROR: script is not executable: %s\n' "$script" >&2
    failed=1
  fi
done

if ! grep -Eq '^  enabled: false$' operator_inputs.yaml ||
   ! grep -Eq '^  mode: stub$' operator_inputs.yaml; then
  printf 'ERROR: external database must remain disabled in stub mode\n' >&2
  failed=1
fi

if ! grep -Fq 'evidence_valid: false' operator-evidence/worker-node.txt; then
  printf 'ERROR: worker placeholder must be explicitly invalid\n' >&2
  failed=1
fi

if (( failed != 0 )); then
  printf 'Stage-1 validation FAILED.\n' >&2
  exit 1
fi

printf 'Stage-1 static scaffold validation passed; runtime readiness was not tested.\n'
