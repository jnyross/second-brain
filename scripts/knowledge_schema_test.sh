#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

"${REPO_ROOT}/scripts/knowledge_validate.sh" "${REPO_ROOT}/schemas/knowledge_index.example.json"

echo "Knowledge schema test passed"
