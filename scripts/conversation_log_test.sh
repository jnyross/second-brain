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

"${REPO_ROOT}/scripts/conversation_log.sh" \
  --role "user" \
  --content "Create task: Submit report"

"${REPO_ROOT}/scripts/conversation_log.sh" \
  --role "assistant" \
  --content "Created task T-123 with status pending"

if [ ! -f "${TARGET_ROOT}/conversation/log.jsonl" ]; then
  echo "✗ conversation log file not created"
  exit 1
fi

if ! grep -q "Create task: Submit report" "${TARGET_ROOT}/conversation/log.jsonl"; then
  echo "✗ user message not in log"
  exit 1
fi

if ! grep -q "Created task T-123" "${TARGET_ROOT}/conversation/log.jsonl"; then
  echo "✗ assistant message not in log"
  exit 1
fi

echo "Conversation log test passed"
