#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
CONFIG_FILE="${ASSISTANT_HOME}/config.json"

DEFAULT_MODEL="claude-3-5-sonnet"
DEFAULT_MAX_TOKENS=4096
DEFAULT_TIMEOUT=60

get_config_value() {
  local key="$1"
  local default="$2"
  
  if [ -f "${CONFIG_FILE}" ]; then
    local value
    value=$(jq -r ".claude.${key} // \"${default}\"" "${CONFIG_FILE}" 2>/dev/null || echo "${default}")
    echo "${value}"
  else
    echo "${default}"
  fi
}

cmd_config() {
  local model
  model=$(get_config_value "model" "${DEFAULT_MODEL}")
  local max_tokens
  max_tokens=$(get_config_value "max_tokens" "${DEFAULT_MAX_TOKENS}")
  local timeout
  timeout=$(get_config_value "timeout" "${DEFAULT_TIMEOUT}")
  
  cat << EOF
Claude Adapter Configuration:
  model: ${model}
  max_tokens: ${max_tokens}
  timeout: ${timeout}s
  config_file: ${CONFIG_FILE}
EOF
}

cmd_check() {
  if ! command -v claude &> /dev/null; then
    echo "Error: claude CLI not found in PATH" >&2
    return 1
  fi
  
  if ! claude --version &> /dev/null; then
    echo "Error: claude CLI not working" >&2
    return 1
  fi
  
  echo "Claude CLI available: $(claude --version 2>&1 | head -1)"
  return 0
}

cmd_prompt() {
  local stream=false
  local tools=false
  local prompt=""
  
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --stream) stream=true; shift ;;
      --tools) tools=true; shift ;;
      *) prompt="$1"; shift ;;
    esac
  done
  
  if [ -z "${prompt}" ]; then
    echo "Error: prompt required" >&2
    exit 1
  fi
  
  local model
  model=$(get_config_value "model" "${DEFAULT_MODEL}")
  local max_tokens
  max_tokens=$(get_config_value "max_tokens" "${DEFAULT_MAX_TOKENS}")
  
  local args=("run")
  
  if [ "${stream}" = true ]; then
    args+=("--stream")
  fi
  
  if [ "${tools}" = true ]; then
    args+=("--tools")
  fi
  
  args+=("--model" "${model}")
  args+=("--max-tokens" "${max_tokens}")
  
  if command -v claude &> /dev/null; then
    claude "${args[@]}" <<< "${prompt}" 2>&1 || echo '{"error": "Claude CLI failed"}'
  else
    echo '{"error": "Claude CLI not available"}'
    return 1
  fi
}

cmd_run() {
  local prompt_file="$1"
  local working_dir="${2:-${ASSISTANT_HOME}}"
  
  if [ ! -f "${prompt_file}" ]; then
    echo "Error: prompt file not found: ${prompt_file}" >&2
    exit 1
  fi
  
  local model
  model=$(get_config_value "model" "${DEFAULT_MODEL}")
  local timeout
  timeout=$(get_config_value "timeout" "${DEFAULT_TIMEOUT}")
  
  if command -v claude &> /dev/null; then
    claude run \
      --prompt-file "${prompt_file}" \
      --working-directory "${working_dir}" \
      --model "${model}" \
      --timeout "${timeout}" \
      2>&1
  else
    echo '{"error": "Claude CLI not available"}'
    return 1
  fi
}

usage() {
  cat << 'EOF'
Usage: claude_adapter.sh <command> [options]

Commands:
  config                      Show adapter configuration
  check                       Check if Claude CLI is available
  prompt [--stream] [--tools] <text>  Send prompt to Claude
  run <prompt-file> [working-dir]     Run Claude with prompt file
EOF
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

command="$1"
shift

case "${command}" in
  config) cmd_config ;;
  check) cmd_check ;;
  prompt) cmd_prompt "$@" ;;
  run) [ $# -ge 1 ] || usage; cmd_run "$@" ;;
  *) usage ;;
esac
