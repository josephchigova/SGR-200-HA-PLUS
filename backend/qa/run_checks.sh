#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$(cd "$BACKEND_DIR/.." && pwd)"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Backend interpreter not found: %s\n' "$PYTHON_BIN" >&2
  printf 'Create/configure backend/.venv first.\n' >&2
  exit 2
fi

printf '\n[1/3] Django checks and migration drift\n'
"$PYTHON_BIN" "$BACKEND_DIR/manage.py" check
"$PYTHON_BIN" "$BACKEND_DIR/manage.py" makemigrations --check --dry-run

printf '\n[2/3] Backend automated tests, statement/branch coverage, JUnit\n'
"$PYTHON_BIN" -m pytest \
  --cov=apps \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=json:"$BACKEND_DIR/qa-coverage.json" \
  --junitxml="$BACKEND_DIR/qa-junit.xml" \
  "$BACKEND_DIR/apps" -q

printf '\n[3/3] Frontend lint and production build\n'
(
  cd "$PROJECT_DIR/frontend"
  npm run lint:evidence
  npm run build
)

printf '\nEvidence files:\n- %s\n- %s\n- %s\n' \
  "$BACKEND_DIR/qa-junit.xml" \
  "$BACKEND_DIR/qa-coverage.json" \
  "$PROJECT_DIR/frontend/qa-lint.json"
printf '\nChecks completed. See backend/qa/TEST_PLAN.md for live defense steps.\n'
