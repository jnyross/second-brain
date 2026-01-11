#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
TASKS_FILE="${ASSISTANT_HOME}/tasks/tasks.json"

TITLE=""
DUE_DATE=""
PRIORITY=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --title)
      TITLE="${2:-}"
      shift 2
      ;;
    --due-date)
      DUE_DATE="${2:-}"
      shift 2
      ;;
    --priority)
      PRIORITY="${2:-}"
      shift 2
      ;;
    *)
      echo "unknown arg: $1"
      exit 2
      ;;
  esac
done

if [ -z "${TITLE}" ] || [ -z "${DUE_DATE}" ] || [ -z "${PRIORITY}" ]; then
  echo "usage: $0 --title <title> --due-date <iso> --priority <priority>"
  exit 2
fi

if [ ! -f "${TASKS_FILE}" ]; then
  echo "✗ missing tasks file"
  exit 1
fi

COUNT="$(jq -r '.tasks | length' "${TASKS_FILE}")"
NEXT=$((COUNT + 1))
TASK_ID="$(printf "T-%03d" "${NEXT}")"

TMP_FILE="$(mktemp)"

jq \
  --arg id "${TASK_ID}" \
  --arg title "${TITLE}" \
  --arg due_date "${DUE_DATE}" \
  --arg priority "${PRIORITY}" \
  '.tasks += [{"id": $id, "title": $title, "due_date": $due_date, "status": "pending", "priority": $priority}]' \
  "${TASKS_FILE}" > "${TMP_FILE}"

mv "${TMP_FILE}" "${TASKS_FILE}"

echo "✓ Created task ${TASK_ID}"
