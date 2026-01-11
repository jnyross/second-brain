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

"${SCRIPT_DIR}/learning_db.sh" add_correction "buy [item]" "priority=low"

if ! jq -e '.learnings[] | select(.pattern=="buy [item]" and .correction=="priority=low")' "${FIXTURE_DIR}/knowledge/learning.json" > /dev/null; then
  echo "FAIL: Learning entry not created"
  exit 1
fi

ENTRY=$(jq '.learnings[] | select(.pattern=="buy [item]")' "${FIXTURE_DIR}/knowledge/learning.json")
COUNT=$(echo "${ENTRY}" | jq -r '.count')
CONFIDENCE=$(echo "${ENTRY}" | jq -r '.confidence')

if [ "${COUNT}" -ne 1 ]; then
  echo "FAIL: Count should be 1, got ${COUNT}"
  exit 1
fi

if [ "$(echo "${CONFIDENCE} == 0.5" | bc -l)" -ne 1 ]; then
  echo "FAIL: Initial confidence should be 0.5, got ${CONFIDENCE}"
  exit 1
fi

echo "PASS: Correction stored with correct schema"

"${SCRIPT_DIR}/learning_db.sh" add_correction "buy [item]" "priority=low"
"${SCRIPT_DIR}/learning_db.sh" add_correction "buy [item]" "priority=low"

ENTRY=$(jq '.learnings[] | select(.pattern=="buy [item]")' "${FIXTURE_DIR}/knowledge/learning.json")
COUNT=$(echo "${ENTRY}" | jq -r '.count')
CONFIDENCE=$(echo "${ENTRY}" | jq -r '.confidence')

if [ "${COUNT}" -ne 3 ]; then
  echo "FAIL: Count should be 3, got ${COUNT}"
  exit 1
fi

if [ "$(echo "${CONFIDENCE} > 0.5" | bc -l)" -ne 1 ]; then
  echo "FAIL: Confidence should increase, got ${CONFIDENCE}"
  exit 1
fi

echo "PASS: Repeated corrections increase count and confidence"

MATCH=$("${SCRIPT_DIR}/learning_db.sh" match "buy milk")
if [ -z "${MATCH}" ]; then
  echo "FAIL: Should match 'buy milk' against 'buy [item]'"
  exit 1
fi

CORRECTION=$(echo "${MATCH}" | jq -r '.correction')
if [ "${CORRECTION}" != "priority=low" ]; then
  echo "FAIL: Should return correction 'priority=low', got ${CORRECTION}"
  exit 1
fi

echo "PASS: Pattern matching works for 'buy milk'"

MATCH=$("${SCRIPT_DIR}/learning_db.sh" match "buy eggs")
if [ -z "${MATCH}" ]; then
  echo "FAIL: Should match 'buy eggs' against 'buy [item]'"
  exit 1
fi

echo "PASS: Pattern matching works for 'buy eggs'"

MATCH=$("${SCRIPT_DIR}/learning_db.sh" match "call mom")
if [ -n "${MATCH}" ] && [ "${MATCH}" != "null" ]; then
  echo "FAIL: Should not match 'call mom', got ${MATCH}"
  exit 1
fi

echo "PASS: Non-matching input returns empty"

ALL=$("${SCRIPT_DIR}/learning_db.sh" list)
if [ "$(echo "${ALL}" | jq 'length')" -lt 1 ]; then
  echo "FAIL: List should return at least 1 learning"
  exit 1
fi

echo "PASS: List works"

echo ""
echo "AT-009 Learning Database test passed"
