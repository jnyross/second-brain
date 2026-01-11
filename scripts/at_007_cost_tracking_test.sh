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

jq '.daily_budget = 5.00' "${FIXTURE_DIR}/config.json" > "${FIXTURE_DIR}/config.json.tmp"
mv "${FIXTURE_DIR}/config.json.tmp" "${FIXTURE_DIR}/config.json"

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

"${SCRIPT_DIR}/cost_tracker.sh" add 2.40
"${SCRIPT_DIR}/cost_tracker.sh" add 2.40

STATE=$(cat "${FIXTURE_DIR}/.ralph/loop_state.json")
DAILY_COST=$(echo "${STATE}" | jq -r '.metrics.daily_cost')
PAUSED=$(echo "${STATE}" | jq -r '.paused')

if [ "$(echo "${DAILY_COST} >= 4.80" | bc -l)" -ne 1 ]; then
  echo "FAIL: daily_cost should be 4.80, got ${DAILY_COST}"
  exit 1
fi

if [ "${PAUSED}" != "false" ]; then
  echo "FAIL: Should not pause below budget"
  exit 1
fi

echo "PASS: Cost tracking accumulates correctly"

"${SCRIPT_DIR}/cost_tracker.sh" add 0.30

STATE=$(cat "${FIXTURE_DIR}/.ralph/loop_state.json")
DAILY_COST=$(echo "${STATE}" | jq -r '.metrics.daily_cost')
PAUSED=$(echo "${STATE}" | jq -r '.paused')

if [ "$(echo "${DAILY_COST} >= 5.00" | bc -l)" -ne 1 ]; then
  echo "FAIL: daily_cost should be >= 5.00, got ${DAILY_COST}"
  exit 1
fi

if [ "${PAUSED}" != "true" ]; then
  echo "FAIL: Should pause when budget exceeded"
  exit 1
fi

if [ ! -f "${FIXTURE_DIR}/.ralph/NEEDS_INPUT.md" ]; then
  echo "FAIL: NEEDS_INPUT.md not created"
  exit 1
fi

if ! grep -q "Daily budget limit reached" "${FIXTURE_DIR}/.ralph/NEEDS_INPUT.md"; then
  echo "FAIL: NEEDS_INPUT.md doesn't contain budget message"
  exit 1
fi

echo "PASS: Budget enforcement pauses loop"

CURRENT_COST=$("${SCRIPT_DIR}/cost_tracker.sh" get)
if [ "$(echo "${CURRENT_COST} >= 5.00" | bc -l)" -ne 1 ]; then
  echo "FAIL: get command should return current cost, got ${CURRENT_COST}"
  exit 1
fi

echo "PASS: Cost query works"

"${SCRIPT_DIR}/cost_tracker.sh" reset

STATE=$(cat "${FIXTURE_DIR}/.ralph/loop_state.json")
DAILY_COST=$(echo "${STATE}" | jq -r '.metrics.daily_cost')

if [ "$(echo "${DAILY_COST} == 0" | bc -l)" -ne 1 ]; then
  echo "FAIL: Reset should zero cost, got ${DAILY_COST}"
  exit 1
fi

echo "PASS: Cost reset works"

echo ""
echo "AT-007 Cost Tracking test passed"
