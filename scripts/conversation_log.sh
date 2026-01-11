#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
CONV_DIR="${ASSISTANT_HOME}/conversation"
LOG_FILE="${CONV_DIR}/log.jsonl"

ROLE=""
CONTENT=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --role)
      ROLE="${2:-}"
      shift 2
      ;;
    --content)
      CONTENT="${2:-}"
      shift 2
      ;;
    *)
      echo "unknown arg: $1"
      exit 2
      ;;
  esac
done

if [ -z "${ROLE}" ] || [ -z "${CONTENT}" ]; then
  echo "usage: $0 --role <user|assistant> --content <message>"
  exit 2
fi

if [ ! -d "${CONV_DIR}" ]; then
  mkdir -p "${CONV_DIR}"
fi

TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

ENTRY="$(jq -n \
  --arg role "${ROLE}" \
  --arg content "${CONTENT}" \
  --arg ts "${TIMESTAMP}" \
  '{role: $role, content: $content, timestamp: $ts}')"

printf "%s\n" "${ENTRY}" >> "${LOG_FILE}"

echo "✓ Logged ${ROLE} message"
