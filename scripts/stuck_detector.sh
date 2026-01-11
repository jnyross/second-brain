#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
STATE_FILE="${ASSISTANT_HOME}/.ralph/loop_state.json"
NEEDS_INPUT_FILE="${ASSISTANT_HOME}/.ralph/NEEDS_INPUT.md"

NO_PROGRESS_THRESHOLD=5
SAME_ERROR_THRESHOLD=3
TOKEN_THRESHOLD=100

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

get_state() {
  cat "${STATE_FILE}"
}

update_state() {
  local new_state="$1"
  echo "${new_state}" > "${STATE_FILE}"
}

create_needs_input() {
  local reason="$1"
  cat > "${NEEDS_INPUT_FILE}" << EOF
# NEEDS_INPUT

## Reason
${reason}

## Questions
1. What should the assistant do to make progress?

## Context
- Loop has been paused due to stuck detection
- Review recent iteration logs for details
EOF
}

compute_error_hash() {
  local error_msg="$1"
  echo -n "${error_msg}" | md5sum | cut -d' ' -f1
}

cmd_record_iteration() {
  local tokens=0
  local file_changes=0
  local error_msg=""
  
  while [[ $# -gt 0 ]]; do
    case $1 in
      --tokens)
        tokens="$2"
        shift 2
        ;;
      --file_changes)
        file_changes="$2"
        shift 2
        ;;
      --error)
        error_msg="$2"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done
  
  ensure_state_file
  local state
  state=$(get_state)
  
  local iteration
  iteration=$(echo "${state}" | jq -r '.iteration')
  iteration=$((iteration + 1))
  
  local no_progress_count
  no_progress_count=$(echo "${state}" | jq -r '.stuck.no_progress_count')
  
  local same_error_repeats
  same_error_repeats=$(echo "${state}" | jq -r '.stuck.same_error_repeats')
  
  local last_error_hash
  last_error_hash=$(echo "${state}" | jq -r '.stuck.last_error_hash // empty')
  
  if [ "${tokens}" -lt "${TOKEN_THRESHOLD}" ] && [ "${file_changes}" -eq 0 ]; then
    no_progress_count=$((no_progress_count + 1))
  else
    no_progress_count=0
  fi
  
  if [ -n "${error_msg}" ]; then
    local current_hash
    current_hash=$(compute_error_hash "${error_msg}")
    
    if [ "${current_hash}" = "${last_error_hash}" ]; then
      same_error_repeats=$((same_error_repeats + 1))
    else
      same_error_repeats=1
      last_error_hash="${current_hash}"
    fi
  else
    same_error_repeats=0
    last_error_hash="null"
  fi
  
  local paused="false"
  
  if [ "${no_progress_count}" -ge "${NO_PROGRESS_THRESHOLD}" ]; then
    paused="true"
    create_needs_input "Stuck: No progress for ${NO_PROGRESS_THRESHOLD} iterations. Please provide guidance."
  fi
  
  if [ "${same_error_repeats}" -ge "${SAME_ERROR_THRESHOLD}" ]; then
    paused="true"
    create_needs_input "Stuck: Same error '${error_msg}' repeated ${SAME_ERROR_THRESHOLD} times."
  fi
  
  local new_state
  new_state=$(jq -n \
    --argjson iteration "${iteration}" \
    --argjson no_progress_count "${no_progress_count}" \
    --argjson same_error_repeats "${same_error_repeats}" \
    --arg last_error_hash "${last_error_hash}" \
    --argjson paused "${paused}" \
    --argjson daily_cost "$(echo "${state}" | jq -r '.metrics.daily_cost')" \
    '{
      iteration: $iteration,
      stuck: {
        no_progress_count: $no_progress_count,
        same_error_repeats: $same_error_repeats,
        last_error_hash: (if $last_error_hash == "null" then null else $last_error_hash end)
      },
      metrics: {
        daily_cost: $daily_cost
      },
      paused: $paused
    }')
  
  update_state "${new_state}"
  
  if [ "${paused}" = "true" ]; then
    echo "Loop paused due to stuck detection"
    return 1
  fi
  
  return 0
}

cmd_reset() {
  ensure_state_file
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
  rm -f "${NEEDS_INPUT_FILE}"
  echo "Loop state reset"
}

cmd_status() {
  ensure_state_file
  cat "${STATE_FILE}" | jq .
}

usage() {
  cat << 'EOF'
Usage: stuck_detector.sh <command> [options]

Commands:
  record_iteration   Record an iteration and check for stuck conditions
    --tokens N       Number of output tokens
    --file_changes N Number of file changes
    --error MSG      Error message (if any)
  
  reset              Reset loop state
  status             Show current loop state
EOF
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

command="$1"
shift

case "${command}" in
  record_iteration)
    cmd_record_iteration "$@" || true
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
