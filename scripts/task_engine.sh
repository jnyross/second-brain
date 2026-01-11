#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
TASKS_FILE="${ASSISTANT_HOME}/tasks/tasks.json"
HISTORY_FILE="${ASSISTANT_HOME}/tasks/history.json"
CONV_LOG="${ASSISTANT_HOME}/conversation/log.jsonl"

ensure_files() {
  mkdir -p "${ASSISTANT_HOME}/tasks" "${ASSISTANT_HOME}/conversation"
  if [ ! -f "${TASKS_FILE}" ]; then
    echo '{"schema_version": "1.0", "tasks": []}' > "${TASKS_FILE}"
  fi
  if [ ! -f "${HISTORY_FILE}" ]; then
    echo '{"history": []}' > "${HISTORY_FILE}"
  fi
}

get_timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_notification() {
  local message="$1"
  local timestamp
  timestamp=$(get_timestamp)
  
  mkdir -p "$(dirname "${CONV_LOG}")"
  echo "{\"role\": \"system\", \"content\": \"${message}\", \"timestamp\": \"${timestamp}\"}" >> "${CONV_LOG}"
}

generate_id() {
  local count
  count=$(jq -r '.tasks | length' "${TASKS_FILE}")
  printf "T-%03d" "$((count + 1))"
}

cmd_create() {
  local title="" due_date="" priority="medium"
  
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --title) title="$2"; shift 2 ;;
      --due-date) due_date="$2"; shift 2 ;;
      --priority) priority="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  
  if [ -z "${title}" ]; then
    echo "Error: --title required" >&2
    exit 1
  fi
  
  ensure_files
  
  local task_id
  task_id=$(generate_id)
  
  local timestamp
  timestamp=$(get_timestamp)
  
  jq --arg id "${task_id}" \
     --arg title "${title}" \
     --arg due_date "${due_date}" \
     --arg priority "${priority}" \
     --arg created "${timestamp}" \
     '.tasks += [{
       "id": $id,
       "title": $title,
       "due_date": $due_date,
       "status": "pending",
       "priority": $priority,
       "created_at": $created
     }]' "${TASKS_FILE}" > "${TASKS_FILE}.tmp"
  mv "${TASKS_FILE}.tmp" "${TASKS_FILE}"
  
  jq --arg task_id "${task_id}" --arg ts "${timestamp}" \
     '.history += [{"task_id": $task_id, "action": "created", "timestamp": $ts}]' \
     "${HISTORY_FILE}" > "${HISTORY_FILE}.tmp"
  mv "${HISTORY_FILE}.tmp" "${HISTORY_FILE}"
  
  log_notification "Task created: ${title} (${task_id})"
  
  echo "Created task ${task_id}: ${title}"
}

cmd_read() {
  local task_id=""
  
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --id) task_id="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  
  if [ -z "${task_id}" ]; then
    echo "Error: --id required" >&2
    exit 1
  fi
  
  ensure_files
  
  jq -e --arg id "${task_id}" '.tasks[] | select(.id == $id)' "${TASKS_FILE}"
}

cmd_update() {
  local task_id="" title="" due_date="" priority="" status=""
  
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --id) task_id="$2"; shift 2 ;;
      --title) title="$2"; shift 2 ;;
      --due-date) due_date="$2"; shift 2 ;;
      --priority) priority="$2"; shift 2 ;;
      --status) status="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  
  if [ -z "${task_id}" ]; then
    echo "Error: --id required" >&2
    exit 1
  fi
  
  ensure_files
  
  local update_expr=".tasks |= map(if .id == \$id then . "
  
  [ -n "${title}" ] && update_expr+="| .title = \$title "
  [ -n "${due_date}" ] && update_expr+="| .due_date = \$due_date "
  [ -n "${priority}" ] && update_expr+="| .priority = \$priority "
  [ -n "${status}" ] && update_expr+="| .status = \$status "
  
  update_expr+="else . end)"
  
  jq --arg id "${task_id}" \
     --arg title "${title}" \
     --arg due_date "${due_date}" \
     --arg priority "${priority}" \
     --arg status "${status}" \
     "${update_expr}" "${TASKS_FILE}" > "${TASKS_FILE}.tmp"
  mv "${TASKS_FILE}.tmp" "${TASKS_FILE}"
  
  local timestamp
  timestamp=$(get_timestamp)
  
  jq --arg task_id "${task_id}" --arg ts "${timestamp}" \
     '.history += [{"task_id": $task_id, "action": "updated", "timestamp": $ts}]' \
     "${HISTORY_FILE}" > "${HISTORY_FILE}.tmp"
  mv "${HISTORY_FILE}.tmp" "${HISTORY_FILE}"
  
  log_notification "Task updated: ${task_id}"
  
  echo "Updated task ${task_id}"
}

cmd_complete() {
  local task_id=""
  
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --id) task_id="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  
  if [ -z "${task_id}" ]; then
    echo "Error: --id required" >&2
    exit 1
  fi
  
  ensure_files
  
  jq --arg id "${task_id}" \
     '.tasks |= map(if .id == $id then .status = "completed" else . end)' \
     "${TASKS_FILE}" > "${TASKS_FILE}.tmp"
  mv "${TASKS_FILE}.tmp" "${TASKS_FILE}"
  
  local timestamp
  timestamp=$(get_timestamp)
  
  jq --arg task_id "${task_id}" --arg ts "${timestamp}" \
     '.history += [{"task_id": $task_id, "action": "completed", "timestamp": $ts}]' \
     "${HISTORY_FILE}" > "${HISTORY_FILE}.tmp"
  mv "${HISTORY_FILE}.tmp" "${HISTORY_FILE}"
  
  log_notification "Task completed: ${task_id}"
  
  echo "Completed task ${task_id}"
}

cmd_delete() {
  local task_id=""
  
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --id) task_id="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  
  if [ -z "${task_id}" ]; then
    echo "Error: --id required" >&2
    exit 1
  fi
  
  ensure_files
  
  jq --arg id "${task_id}" '.tasks |= map(select(.id != $id))' \
     "${TASKS_FILE}" > "${TASKS_FILE}.tmp"
  mv "${TASKS_FILE}.tmp" "${TASKS_FILE}"
  
  local timestamp
  timestamp=$(get_timestamp)
  
  jq --arg task_id "${task_id}" --arg ts "${timestamp}" \
     '.history += [{"task_id": $task_id, "action": "deleted", "timestamp": $ts}]' \
     "${HISTORY_FILE}" > "${HISTORY_FILE}.tmp"
  mv "${HISTORY_FILE}.tmp" "${HISTORY_FILE}"
  
  log_notification "Task deleted: ${task_id}"
  
  echo "Deleted task ${task_id}"
}

cmd_list() {
  ensure_files
  jq '.tasks' "${TASKS_FILE}"
}

usage() {
  cat << 'EOF'
Usage: task_engine.sh <command> [options]

Commands:
  create   --title <title> [--due-date <iso>] [--priority <priority>]
  read     --id <task-id>
  update   --id <task-id> [--title] [--due-date] [--priority] [--status]
  complete --id <task-id>
  delete   --id <task-id>
  list
EOF
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

command="$1"
shift

case "${command}" in
  create) cmd_create "$@" ;;
  read) cmd_read "$@" ;;
  update) cmd_update "$@" ;;
  complete) cmd_complete "$@" ;;
  delete) cmd_delete "$@" ;;
  list) cmd_list ;;
  *) usage ;;
esac
