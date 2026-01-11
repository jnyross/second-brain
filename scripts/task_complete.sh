#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
TASKS_FILE="${ASSISTANT_HOME}/tasks/tasks.json"
HISTORY_FILE="${ASSISTANT_HOME}/tasks/history.json"

TASK_ID=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --id)
      TASK_ID="${2:-}"
      shift 2
      ;;
    *)
      echo "unknown arg: $1"
      exit 2
      ;;
  esac
done

if [ -z "${TASK_ID}" ]; then
  echo "usage: $0 --id <task-id>"
  exit 2
fi

if [ ! -f "${TASKS_FILE}" ] || [ ! -f "${HISTORY_FILE}" ]; then
  echo "✗ missing tasks files"
  exit 1
fi

MATCHES="$(jq -r --arg id "${TASK_ID}" '.tasks | map(select(.id == $id)) | length' "${TASKS_FILE}")"
if [ "${MATCHES}" -eq 0 ]; then
  echo "✗ task not found: ${TASK_ID}"
  exit 1
fi

TMP_TASKS="$(mktemp)"
TMP_HISTORY="$(mktemp)"

jq --arg id "${TASK_ID}" '.tasks |= map(if .id == $id then .status = "completed" else . end)' "${TASKS_FILE}" > "${TMP_TASKS}"

TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

jq \
  --arg task_id "${TASK_ID}" \
  --arg ts "${TS}" \
  '.history += [{"task_id": $task_id, "action": "completed", "timestamp": $ts}]' \
  "${HISTORY_FILE}" > "${TMP_HISTORY}"

mv "${TMP_TASKS}" "${TASKS_FILE}"
mv "${TMP_HISTORY}" "${HISTORY_FILE}"

echo "✓ Completed task ${TASK_ID}"
