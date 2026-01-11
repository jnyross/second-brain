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

for i in {1..5}; do
  "${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 50 --file_changes 0
done

STATE=$(cat "${FIXTURE_DIR}/.ralph/loop_state.json")
NO_PROGRESS_COUNT=$(echo "${STATE}" | jq -r '.stuck.no_progress_count')
PAUSED=$(echo "${STATE}" | jq -r '.paused')

if [ "${NO_PROGRESS_COUNT}" -ne 5 ]; then
  echo "FAIL: no_progress_count should be 5, got ${NO_PROGRESS_COUNT}"
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

if ! grep -q "Stuck: No progress for 5 iterations" "${FIXTURE_DIR}/.ralph/NEEDS_INPUT.md"; then
  echo "FAIL: NEEDS_INPUT.md doesn't contain expected message"
  exit 1
fi

echo "PASS: No-progress detection works correctly"

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

"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 50 --file_changes 0
"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 150 --file_changes 0
"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 50 --file_changes 0

STATE=$(cat "${FIXTURE_DIR}/.ralph/loop_state.json")
NO_PROGRESS_COUNT=$(echo "${STATE}" | jq -r '.stuck.no_progress_count')

if [ "${NO_PROGRESS_COUNT}" -ne 1 ]; then
  echo "FAIL: Progress should reset counter, expected 1, got ${NO_PROGRESS_COUNT}"
  exit 1
fi

echo "PASS: Progress resets no-progress counter"

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

"${SCRIPT_DIR}/stuck_detector.sh" record_iteration --tokens 50 --file_changes 1

STATE=$(cat "${FIXTURE_DIR}/.ralph/loop_state.json")
NO_PROGRESS_COUNT=$(echo "${STATE}" | jq -r '.stuck.no_progress_count')

if [ "${NO_PROGRESS_COUNT}" -ne 0 ]; then
  echo "FAIL: File changes should reset counter, expected 0, got ${NO_PROGRESS_COUNT}"
  exit 1
fi

echo "PASS: File changes reset no-progress counter"

echo ""
echo "AT-005 Stuck Detection (No-Progress) test passed"
