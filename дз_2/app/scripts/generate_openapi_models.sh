#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC_PATH="${SCRIPT_DIR}/../src/resources/openapi/marketplace.yaml"
OUT_DIR="${SCRIPT_DIR}/../src/generated"
PYTHON_BIN="${PYTHON_BIN:-python}"

mkdir -p "${OUT_DIR}"
"${PYTHON_BIN}" -m datamodel_code_generator \
  --input "${SPEC_PATH}" \
  --input-file-type openapi \
  --output "${OUT_DIR}/models.py" \
  --output-model-type pydantic_v2.BaseModel \
  --use-schema-description \
  --use-field-description \
  --target-python-version 3.11 \
  --use-annotated

if [ ! -f "${OUT_DIR}/__init__.py" ]; then
  touch "${OUT_DIR}/__init__.py"
fi
