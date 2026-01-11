#!/usr/bin/env bash
set -euo pipefail

FAILED=0
ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"

fail() {
  echo "✗ $1"
  FAILED=$((FAILED + 1))
}

if [ ! -d "${ASSISTANT_HOME}/knowledge" ]; then
  fail "Knowledge base missing"
fi

if git -C "${ASSISTANT_HOME}" log --all --oneline 2>/dev/null | grep -qiE '(password|api.*key|secret)'; then
  fail "Sensitive data in git history"
fi

if [ ! -f "${ASSISTANT_HOME}/tasks/tasks.json" ]; then
  fail "Task file missing"
else
  if ! jq -e '.schema_version == "1.0"' "${ASSISTANT_HOME}/tasks/tasks.json" > /dev/null 2>&1; then
    fail "Task file corrupted or wrong version"
  fi
fi

if ! jq -e '.learnings' "${ASSISTANT_HOME}/knowledge/learning.json" > /dev/null 2>&1; then
  fail "Learning database corrupted"
fi

if ! command -v claude > /dev/null 2>&1; then
  fail "Claude CLI not found in PATH"
fi

if ! command -v docker > /dev/null 2>&1; then
  fail "Docker not available for sandbox"
fi

if ! git -C "${ASSISTANT_HOME}" rev-parse --is-inside-work-tree > /dev/null 2>&1; then
  fail "Not a git repository"
fi

if ! jq -e '.user_id' "${ASSISTANT_HOME}/config.json" > /dev/null 2>&1; then
  fail "Configuration invalid"
fi

if [ "${FAILED}" -eq 0 ]; then
  echo "✓ All checks passed (8/8)"
  exit 0
fi

echo "✗ ${FAILED} check(s) failed"
exit 1
