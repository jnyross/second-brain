#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
CONFIG_FILE="${ASSISTANT_HOME}/config.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEFAULT_MAX_ITERATIONS=100
DEFAULT_CHECKPOINT_INTERVAL=10
DEFAULT_TIMEOUT=3600
DEFAULT_MODEL="claude-3-5-sonnet"
DEFAULT_COMPLETION_PROMISE="ASSISTANT_TASKS_COMPLETE"

get_config_value() {
  local key="$1"
  local default="$2"
  
  if [ -f "${CONFIG_FILE}" ]; then
    local value
    value=$(jq -r ".${key} // \"${default}\"" "${CONFIG_FILE}" 2>/dev/null || echo "${default}")
    if [ "${value}" = "null" ]; then
      echo "${default}"
    else
      echo "${value}"
    fi
  else
    echo "${default}"
  fi
}

cmd_config() {
  local max_iterations
  max_iterations=$(get_config_value "max_iterations" "${DEFAULT_MAX_ITERATIONS}")
  local checkpoint_interval
  checkpoint_interval=$(get_config_value "checkpoint_interval" "${DEFAULT_CHECKPOINT_INTERVAL}")
  local timeout
  timeout=$(get_config_value "timeout" "${DEFAULT_TIMEOUT}")
  local model
  model=$(get_config_value "model" "${DEFAULT_MODEL}")
  local completion_promise
  completion_promise=$(get_config_value "completion_promise" "${DEFAULT_COMPLETION_PROMISE}")
  
  cat << EOF
Run Configuration:
  working_directory: ${ASSISTANT_HOME}
  max_iterations: ${max_iterations}
  checkpoint_interval: ${checkpoint_interval}
  timeout: ${timeout}s
  model: ${model}
  completion_promise: ${completion_promise}
EOF
}

cmd_check() {
  local errors=0
  
  if ! command -v claude &> /dev/null; then
    echo "✗ Claude CLI not found in PATH"
    errors=$((errors + 1))
  else
    echo "✓ Claude CLI available"
  fi
  
  if [ ! -d "${ASSISTANT_HOME}" ]; then
    echo "✗ Working directory missing: ${ASSISTANT_HOME}"
    errors=$((errors + 1))
  else
    echo "✓ Working directory exists"
  fi
  
  if [ ! -f "${CONFIG_FILE}" ]; then
    echo "✗ Config file missing"
    errors=$((errors + 1))
  else
    echo "✓ Config file exists"
  fi
  
  if [ -f "${SCRIPT_DIR}/verify.sh" ]; then
    if "${SCRIPT_DIR}/verify.sh" > /dev/null 2>&1; then
      echo "✓ Verification passes"
    else
      echo "✗ Verification failed"
      errors=$((errors + 1))
    fi
  fi
  
  if [ "${errors}" -eq 0 ]; then
    echo ""
    echo "All pre-run checks passed"
    return 0
  else
    echo ""
    echo "${errors} check(s) failed"
    return 1
  fi
}

cmd_start() {
  local prompt_file=""
  local dry_run=false
  
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --prompt-file) prompt_file="$2"; shift 2 ;;
      --dry-run) dry_run=true; shift ;;
      *) shift ;;
    esac
  done
  
  if [ -z "${prompt_file}" ]; then
    prompt_file="${SCRIPT_DIR}/../Prompt.md"
  fi
  
  if [ ! -f "${prompt_file}" ]; then
    echo "Error: Prompt file not found: ${prompt_file}" >&2
    exit 1
  fi
  
  local max_iterations
  max_iterations=$(get_config_value "max_iterations" "${DEFAULT_MAX_ITERATIONS}")
  local checkpoint_interval
  checkpoint_interval=$(get_config_value "checkpoint_interval" "${DEFAULT_CHECKPOINT_INTERVAL}")
  local timeout
  timeout=$(get_config_value "timeout" "${DEFAULT_TIMEOUT}")
  local model
  model=$(get_config_value "model" "${DEFAULT_MODEL}")
  local completion_promise
  completion_promise=$(get_config_value "completion_promise" "${DEFAULT_COMPLETION_PROMISE}")
  
  if [ "${dry_run}" = true ]; then
    echo "DRY RUN - would execute:"
    echo "  claude run \\"
    echo "    --prompt-file ${prompt_file} \\"
    echo "    --working-directory ${ASSISTANT_HOME} \\"
    echo "    --max-iterations ${max_iterations} \\"
    echo "    --checkpoint-interval ${checkpoint_interval} \\"
    echo "    --timeout ${timeout} \\"
    echo "    --completion-promise \"${completion_promise}\" \\"
    echo "    --model ${model}"
    return 0
  fi
  
  if ! cmd_check > /dev/null 2>&1; then
    echo "Pre-run checks failed. Run 'run.sh check' for details." >&2
    exit 1
  fi
  
  echo "Starting Claude Personal Assistant..."
  echo "  Working directory: ${ASSISTANT_HOME}"
  echo "  Max iterations: ${max_iterations}"
  echo "  Completion promise: ${completion_promise}"
  echo ""
  
  claude run \
    --prompt-file "${prompt_file}" \
    --working-directory "${ASSISTANT_HOME}" \
    --max-iterations "${max_iterations}" \
    --checkpoint-interval "${checkpoint_interval}" \
    --timeout "${timeout}" \
    --completion-promise "${completion_promise}" \
    --model "${model}"
}

cmd_help() {
  cat << 'EOF'
Usage: run.sh <command> [options]

Commands:
  config                          Show run configuration
  check                           Run pre-flight checks
  start [--prompt-file <file>] [--dry-run]  Start the assistant loop
  help                            Show this help

Options:
  --prompt-file <file>   Use custom prompt file (default: Prompt.md)
  --dry-run              Show command without executing

Environment:
  AI_ASSISTANT_HOME      Working directory (default: ~/.ai-assistant)
EOF
}

if [ $# -lt 1 ]; then
  cmd_help
  exit 0
fi

command="$1"
shift

case "${command}" in
  config) cmd_config ;;
  check) cmd_check ;;
  start) cmd_start "$@" ;;
  help|--help|-h) cmd_help ;;
  *) cmd_help; exit 1 ;;
esac
