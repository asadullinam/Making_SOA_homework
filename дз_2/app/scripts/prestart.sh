#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/.."

"${SCRIPT_DIR}/generate_openapi_models.sh"
cd "${APP_DIR}"
export PYTHONPATH="${APP_DIR}/src"

PYTHON_BIN="${PYTHON_BIN:-python}"
"${PYTHON_BIN}" -m alembic upgrade head

exec "${PYTHON_BIN}" -m uvicorn src.main:app --host 0.0.0.0 --port 8000
