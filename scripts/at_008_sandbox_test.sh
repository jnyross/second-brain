#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="${SCRIPT_DIR}/../.tmp/ai-assistant"

cleanup() {
  rm -rf "${SCRIPT_DIR}/../.tmp"
}

trap cleanup EXIT
cleanup

export AI_ASSISTANT_HOME="${FIXTURE_DIR}"
"${SCRIPT_DIR}/bootstrap.sh"

mkdir -p "${FIXTURE_DIR}/.ralph"

if "${SCRIPT_DIR}/sandbox_guard.sh" check_path "/etc/passwd"; then
  echo "FAIL: Should reject /etc/passwd"
  exit 1
fi

if ! grep -q "sandbox_violation" "${FIXTURE_DIR}/.ralph/security_log.json" 2>/dev/null; then
  echo "FAIL: Security event not logged for /etc/passwd"
  exit 1
fi

if ! jq -e '.security_events[] | select(.event=="sandbox_violation" and .path=="/etc/passwd")' "${FIXTURE_DIR}/.ralph/security_log.json" > /dev/null; then
  echo "FAIL: Security log missing expected fields"
  exit 1
fi

echo "PASS: Blocks access to /etc/passwd and logs violation"

if ! "${SCRIPT_DIR}/sandbox_guard.sh" check_path "${FIXTURE_DIR}/tasks/tasks.json"; then
  echo "FAIL: Should allow access to tasks.json in working directory"
  exit 1
fi

echo "PASS: Allows access within working directory"

if "${SCRIPT_DIR}/sandbox_guard.sh" check_path "${FIXTURE_DIR}/../../../etc/passwd"; then
  echo "FAIL: Should reject path traversal attempt"
  exit 1
fi

echo "PASS: Blocks path traversal attempts"

if "${SCRIPT_DIR}/sandbox_guard.sh" check_path "/tmp/sensitive"; then
  echo "FAIL: Should reject /tmp access"
  exit 1
fi

echo "PASS: Blocks access to /tmp"

VIOLATIONS=$("${SCRIPT_DIR}/sandbox_guard.sh" list_violations)
if [ "$(echo "${VIOLATIONS}" | jq 'length')" -lt 3 ]; then
  echo "FAIL: Should have logged at least 3 violations"
  exit 1
fi

echo "PASS: Violation list works"

echo ""
echo "AT-008 Sandbox Enforcement test passed"
