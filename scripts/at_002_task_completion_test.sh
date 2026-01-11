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

"${REPO_ROOT}/scripts/task_create.sh" \
  --title "Buy groceries" \
  --due-date "2026-01-12T17:00:00" \
  --priority "medium"

TASK_ID="$(jq -r '.tasks[] | select(.title=="Buy groceries") | .id' "${TARGET_ROOT}/tasks/tasks.json")"

"${REPO_ROOT}/scripts/task_complete.sh" --id "${TASK_ID}"

jq -e '.tasks[] | select(.title=="Buy groceries") | .status == "completed"' "${TARGET_ROOT}/tasks/tasks.json" > /dev/null
jq -e '.history[] | select(.task_id=="'"${TASK_ID}"'" and .action=="completed")' "${TARGET_ROOT}/tasks/history.json" > /dev/null

echo "AT-002 passed"
