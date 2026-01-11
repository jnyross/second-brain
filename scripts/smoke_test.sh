#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"

FAILED=0

fail() {
  echo "✗ $1"
  FAILED=$((FAILED + 1))
}

mkdir -p "${ASSISTANT_HOME}/tasks"

TEST_TASK='{"id": "test-001", "title": "Test task", "status": "pending", "priority": "low"}'
printf "%s\n" "${TEST_TASK}" > "${ASSISTANT_HOME}/tasks/test-task.json"

if [ ! -f "${ASSISTANT_HOME}/tasks/test-task.json" ]; then
  fail "Task creation failed"
fi

if ! jq -e '.user_id' "${ASSISTANT_HOME}/config.json" > /dev/null 2>&1; then
  fail "Configuration invalid"
fi

if [ ! -d "${ASSISTANT_HOME}/knowledge" ]; then
  fail "Knowledge base inaccessible"
fi

if ! jq -e '.schema_version == "1.0"' "${ASSISTANT_HOME}/tasks/tasks.json" > /dev/null 2>&1; then
  fail "Tasks file invalid"
fi

if [ "${FAILED}" -eq 0 ]; then
  echo "✓ Smoke test passed (4/4)"
  exit 0
fi

echo "✗ ${FAILED} check(s) failed"
exit 1
