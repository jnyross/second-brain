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

cat > "${FIXTURE_DIR}/.ralph/loop_state.json" << 'EOF'
{
  "iteration": 0,
  "stuck": {
    "no_progress_count": 0,
    "same_error_repeats": 0,
    "last_error_hash": null
  },
  "metrics": {
    "daily_cost": 0.0
  },
  "paused": false
}
EOF

ERROR_MSG="API rate limit exceeded"

"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 200 --file_changes 1 --error "${ERROR_MSG}"
"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 200 --file_changes 1 --error "${ERROR_MSG}"
"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 200 --file_changes 1 --error "${ERROR_MSG}"

STATE=$(cat "${FIXTURE_DIR}/.ralph/loop_state.json")
SAME_ERROR_REPEATS=$(echo "${STATE}" | jq -r '.stuck.same_error_repeats')
PAUSED=$(echo "${STATE}" | jq -r '.paused')

if [ "${SAME_ERROR_REPEATS}" -ne 3 ]; then
  echo "FAIL: same_error_repeats should be 3, got ${SAME_ERROR_REPEATS}"
  exit 1
fi

if [ "${PAUSED}" != "true" ]; then
  echo "FAIL: paused should be true, got ${PAUSED}"
  exit 1
fi

if [ ! -f "${FIXTURE_DIR}/.ralph/NEEDS_INPUT.md" ]; then
  echo "FAIL: NEEDS_INPUT.md not created"
  exit 1
fi

if ! grep -q "Stuck: Same error 'API rate limit exceeded' repeated 3 times" "${FIXTURE_DIR}/.ralph/NEEDS_INPUT.md"; then
  echo "FAIL: NEEDS_INPUT.md doesn't contain expected message"
  cat "${FIXTURE_DIR}/.ralph/NEEDS_INPUT.md"
  exit 1
fi

echo "PASS: Same-error detection triggers after 3 repeats"

cat > "${FIXTURE_DIR}/.ralph/loop_state.json" << 'EOF'
{
  "iteration": 0,
  "stuck": {
    "no_progress_count": 0,
    "same_error_repeats": 0,
    "last_error_hash": null
  },
  "metrics": {
    "daily_cost": 0.0
  },
  "paused": false
}
EOF

rm -f "${FIXTURE_DIR}/.ralph/NEEDS_INPUT.md"

"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 200 --file_changes 1 --error "Error A"
"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 200 --file_changes 1 --error "Error B"
"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 200 --file_changes 1 --error "Error C"

STATE=$(cat "${FIXTURE_DIR}/.ralph/loop_state.json")
SAME_ERROR_REPEATS=$(echo "${STATE}" | jq -r '.stuck.same_error_repeats')
PAUSED=$(echo "${STATE}" | jq -r '.paused')

if [ "${SAME_ERROR_REPEATS}" -ne 1 ]; then
  echo "FAIL: Different errors should reset counter to 1, got ${SAME_ERROR_REPEATS}"
  exit 1
fi

if [ "${PAUSED}" != "false" ]; then
  echo "FAIL: Should not pause for different errors"
  exit 1
fi

echo "PASS: Different errors reset counter"

cat > "${FIXTURE_DIR}/.ralph/loop_state.json" << 'EOF'
{
  "iteration": 0,
  "stuck": {
    "no_progress_count": 0,
    "same_error_repeats": 2,
    "last_error_hash": "abc123"
  },
  "metrics": {
    "daily_cost": 0.0
  },
  "paused": false
}
EOF

"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 200 --file_changes 1

STATE=$(cat "${FIXTURE_DIR}/.ralph/loop_state.json")
SAME_ERROR_REPEATS=$(echo "${STATE}" | jq -r '.stuck.same_error_repeats')

if [ "${SAME_ERROR_REPEATS}" -ne 0 ]; then
  echo "FAIL: No error should reset counter to 0, got ${SAME_ERROR_REPEATS}"
  exit 1
fi

echo "PASS: Success clears error counter"

echo ""
echo "AT-006 Stuck Detection (Same-Error) test passed"
