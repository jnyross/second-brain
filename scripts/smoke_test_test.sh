#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_ROOT="${REPO_ROOT}/.tmp/ai-assistant"

trap 'rm -rf "${TARGET_ROOT}"' EXIT

rm -rf "${TARGET_ROOT}"
mkdir -p "${TARGET_ROOT}"

export AI_ASSISTANT_HOME="${TARGET_ROOT}"

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

"${REPO_ROOT}/scripts/bootstrap.sh"

"${REPO_ROOT}/scripts/smoke_test.sh"

echo "Smoke test test passed"
