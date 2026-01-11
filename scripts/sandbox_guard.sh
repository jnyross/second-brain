#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
SECURITY_LOG="${ASSISTANT_HOME}/.ralph/security_log.json"

ensure_security_log() {
  mkdir -p "${ASSISTANT_HOME}/.ralph"
  if [ ! -f "${SECURITY_LOG}" ]; then
    echo '{"security_events": []}' > "${SECURITY_LOG}"
  fi
}

get_timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_violation() {
  local path="$1"
  local reason="${2:-outside working directory}"
  ensure_security_log
  
  local timestamp
  timestamp=$(get_timestamp)
  
  local event
  event=$(jq -n --arg path "${path}" --arg ts "${timestamp}" --arg reason "${reason}" \
    '{event: "sandbox_violation", path: $path, reason: $reason, timestamp: $ts}')
  
  jq --argjson event "${event}" '.security_events += [$event]' \
    "${SECURITY_LOG}" > "${SECURITY_LOG}.tmp"
  mv "${SECURITY_LOG}.tmp" "${SECURITY_LOG}"
}

normalize_path() {
  local path="$1"
  local normalized
  
  if [[ "${path}" == /* ]]; then
    normalized="${path}"
  else
    normalized="${PWD}/${path}"
  fi
  
  normalized=$(cd "$(dirname "${normalized}")" 2>/dev/null && pwd)/$(basename "${normalized}") 2>/dev/null || echo "${normalized}"
  
  echo "${normalized}"
}

is_within_sandbox() {
  local check_path="$1"
  local sandbox_root="${ASSISTANT_HOME}"
  
  local normalized_check
  normalized_check=$(normalize_path "${check_path}")
  
  local normalized_root
  normalized_root=$(cd "${sandbox_root}" 2>/dev/null && pwd) || normalized_root="${sandbox_root}"
  
  if [[ "${normalized_check}" == "${normalized_root}"* ]]; then
    return 0
  else
    return 1
  fi
}

cmd_check_path() {
  local path="$1"
  
  if is_within_sandbox "${path}"; then
    return 0
  else
    log_violation "${path}" "Permission denied: Cannot access outside working directory"
    echo "Permission denied: Cannot access outside working directory" >&2
    return 1
  fi
}

cmd_list_violations() {
  ensure_security_log
  jq '.security_events' "${SECURITY_LOG}"
}

cmd_clear_log() {
  ensure_security_log
  echo '{"security_events": []}' > "${SECURITY_LOG}"
  echo "Security log cleared"
}

usage() {
  cat << 'EOF'
Usage: sandbox_guard.sh <command> [args]

Commands:
  check_path <path>   Check if path is within sandbox (exits 0 if allowed, 1 if blocked)
  list_violations     List all security violations
  clear_log           Clear security log
EOF
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

command="$1"
shift

case "${command}" in
  check_path)
    [ $# -ge 1 ] || usage
    cmd_check_path "$1"
    ;;
  list_violations)
    cmd_list_violations
    ;;
  clear_log)
    cmd_clear_log
    ;;
  *)
    usage
    ;;
esac
