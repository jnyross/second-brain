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

RESULT=$("${SCRIPT_DIR}/task_engine.sh" create --title "Buy groceries" --due-date "2026-01-12T17:00:00" --priority "medium")
TASK_ID=$(echo "${RESULT}" | grep -oE "T-[0-9]+")

if [ -z "${TASK_ID}" ]; then
  echo "FAIL: Task creation should return task ID"
  exit 1
fi

if ! jq -e --arg id "${TASK_ID}" '.tasks[] | select(.id == $id and .title == "Buy groceries")' "${FIXTURE_DIR}/tasks/tasks.json" > /dev/null; then
  echo "FAIL: Task not found in tasks.json"
  exit 1
fi

echo "PASS: Create task works"

TASK=$("${SCRIPT_DIR}/task_engine.sh" read --id "${TASK_ID}")
if [ -z "${TASK}" ]; then
  echo "FAIL: Read should return task"
  exit 1
fi

TITLE=$(echo "${TASK}" | jq -r '.title')
if [ "${TITLE}" != "Buy groceries" ]; then
  echo "FAIL: Read returned wrong title: ${TITLE}"
  exit 1
fi

echo "PASS: Read task works"

"${SCRIPT_DIR}/task_engine.sh" update --id "${TASK_ID}" --priority "high"

UPDATED_PRIORITY=$(jq -r --arg id "${TASK_ID}" '.tasks[] | select(.id == $id) | .priority' "${FIXTURE_DIR}/tasks/tasks.json")
if [ "${UPDATED_PRIORITY}" != "high" ]; then
  echo "FAIL: Update should change priority to 'high', got ${UPDATED_PRIORITY}"
  exit 1
fi

echo "PASS: Update task works"

"${SCRIPT_DIR}/task_engine.sh" complete --id "${TASK_ID}"

STATUS=$(jq -r --arg id "${TASK_ID}" '.tasks[] | select(.id == $id) | .status' "${FIXTURE_DIR}/tasks/tasks.json")
if [ "${STATUS}" != "completed" ]; then
  echo "FAIL: Complete should set status to 'completed', got ${STATUS}"
  exit 1
fi

if ! jq -e --arg id "${TASK_ID}" '.history[] | select(.task_id == $id and .action == "completed")' "${FIXTURE_DIR}/tasks/history.json" > /dev/null; then
  echo "FAIL: History entry not created"
  exit 1
fi

echo "PASS: Complete task works with history"

"${SCRIPT_DIR}/task_engine.sh" create --title "Temp task" --due-date "2026-01-12T10:00:00" --priority "low" > /dev/null
TEMP_ID=$("${SCRIPT_DIR}/task_engine.sh" list | jq -r '.[] | select(.title == "Temp task") | .id')

"${SCRIPT_DIR}/task_engine.sh" delete --id "${TEMP_ID}"

if jq -e --arg id "${TEMP_ID}" '.tasks[] | select(.id == $id)' "${FIXTURE_DIR}/tasks/tasks.json" > /dev/null 2>&1; then
  echo "FAIL: Delete should remove task"
  exit 1
fi

echo "PASS: Delete task works"

ALL_TASKS=$("${SCRIPT_DIR}/task_engine.sh" list)
COUNT=$(echo "${ALL_TASKS}" | jq 'length')
if [ "${COUNT}" -lt 1 ]; then
  echo "FAIL: List should return tasks"
  exit 1
fi

echo "PASS: List tasks works"

if [ ! -f "${FIXTURE_DIR}/conversation/log.jsonl" ]; then
  echo "Note: Notification logging not yet integrated (conversation log missing)"
else
  echo "PASS: Notifications logged"
fi

echo ""
echo "Task Engine test passed"
