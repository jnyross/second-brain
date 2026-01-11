#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
STATE_FILE="${ASSISTANT_HOME}/.ralph/loop_state.json"
CONFIG_FILE="${ASSISTANT_HOME}/config.json"
NEEDS_INPUT_FILE="${ASSISTANT_HOME}/.ralph/NEEDS_INPUT.md"

ensure_state_file() {
  mkdir -p "${ASSISTANT_HOME}/.ralph"
  if [ ! -f "${STATE_FILE}" ]; then
    cat > "${STATE_FILE}" << 'EOF'
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
  fi
}

get_daily_budget() {
  if [ -f "${CONFIG_FILE}" ]; then
    jq -r '.daily_budget // 10.0' "${CONFIG_FILE}"
  else
    echo "10.0"
  fi
}

create_needs_input() {
  local reason="$1"
  cat > "${NEEDS_INPUT_FILE}" << EOF
# NEEDS_INPUT

## Reason
${reason}

## Questions
1. Should the daily budget be increased?
2. Should the loop continue despite exceeding budget?

## Context
- Loop has been paused due to budget limit
- Current daily cost has reached or exceeded the configured limit
EOF
}

cmd_add() {
  local cost="$1"
  ensure_state_file
  
  local state
  state=$(cat "${STATE_FILE}")
  
  local current_cost
  current_cost=$(echo "${state}" | jq -r '.metrics.daily_cost')
  
  local new_cost
  new_cost=$(echo "${current_cost} + ${cost}" | bc -l)
  
  local budget
  budget=$(get_daily_budget)
  
  local paused="false"
  if [ "$(echo "${new_cost} >= ${budget}" | bc -l)" -eq 1 ]; then
    paused="true"
    create_needs_input "Daily budget limit reached (\$${budget}). Paused."
  fi
  
  local new_state
  new_state=$(echo "${state}" | jq --argjson cost "${new_cost}" --argjson paused "${paused}" \
    '.metrics.daily_cost = $cost | .paused = $paused')
  
  echo "${new_state}" > "${STATE_FILE}"
  
  if [ "${paused}" = "true" ]; then
    echo "Budget limit reached. Loop paused."
  fi
}

cmd_get() {
  ensure_state_file
  jq -r '.metrics.daily_cost' "${STATE_FILE}"
}

cmd_reset() {
  ensure_state_file
  local state
  state=$(cat "${STATE_FILE}")
  
  local new_state
  new_state=$(echo "${state}" | jq '.metrics.daily_cost = 0.0 | .paused = false')
  
  echo "${new_state}" > "${STATE_FILE}"
  rm -f "${NEEDS_INPUT_FILE}"
  echo "Daily cost reset to 0"
}

cmd_status() {
  ensure_state_file
  local cost
  cost=$(jq -r '.metrics.daily_cost' "${STATE_FILE}")
  local budget
  budget=$(get_daily_budget)
  echo "Daily cost: \$${cost} / \$${budget}"
}

usage() {
  cat << 'EOF'
Usage: cost_tracker.sh <command> [args]

Commands:
  add <amount>   Add cost for an iteration
  get            Get current daily cost
  reset          Reset daily cost to 0
  status         Show cost status with budget
EOF
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

command="$1"
shift

case "${command}" in
  add)
    [ $# -ge 1 ] || usage
    cmd_add "$1"
    ;;
  get)
    cmd_get
    ;;
  reset)
    cmd_reset
    ;;
  status)
    cmd_status
    ;;
  *)
    usage
    ;;
esac
