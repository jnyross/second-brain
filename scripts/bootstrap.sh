#!/usr/bin/env bash
set -euo pipefail

if ! command -v jq > /dev/null 2>&1; then
  echo "jq is required but not installed"
  exit 1
fi

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

mkdir -p "${ASSISTANT_HOME}/knowledge" \
  "${ASSISTANT_HOME}/tasks" \
  "${ASSISTANT_HOME}/calendar" \
  "${ASSISTANT_HOME}/contacts" \
  "${ASSISTANT_HOME}/security" \
  "${ASSISTANT_HOME}/conversation" \
  "${ASSISTANT_HOME}/.ralph"

if [ ! -f "${ASSISTANT_HOME}/config.json" ]; then
  cat > "${ASSISTANT_HOME}/config.json" << 'EOF'
{
  "user_id": "user@example.com",
  "preferences": {
    "time_zone": "America/Los_Angeles",
    "language": "en",
    "privacy_level": "high"
  },
  "integrations": {
    "calendar": {"enabled": false, "provider": null},
    "email": {"enabled": false, "provider": null},
    "task_manager": {"enabled": false, "provider": null}
  }
}
EOF
fi

if [ ! -f "${ASSISTANT_HOME}/knowledge/learning.json" ]; then
  cat > "${ASSISTANT_HOME}/knowledge/learning.json" << 'EOF'
{
  "version": "1.0",
  "learnings": [],
  "last_updated": null,
  "schema": {
    "id": "string",
    "pattern": "string",
    "correction": "string",
    "count": "integer",
    "confidence": "float"
  }
}
EOF
fi

if [ ! -f "${ASSISTANT_HOME}/tasks/tasks.json" ]; then
  cat > "${ASSISTANT_HOME}/tasks/tasks.json" << 'EOF'
{
  "schema_version": "1.0",
  "tasks": []
}
EOF
fi

if [ ! -f "${ASSISTANT_HOME}/tasks/history.json" ]; then
  cat > "${ASSISTANT_HOME}/tasks/history.json" << 'EOF'
{
  "history": []
}
EOF
fi

jq -e '.user_id' "${ASSISTANT_HOME}/config.json" > /dev/null
jq -e '.learnings' "${ASSISTANT_HOME}/knowledge/learning.json" > /dev/null
jq -e '.schema_version == "1.0"' "${ASSISTANT_HOME}/tasks/tasks.json" > /dev/null
jq -e '.history' "${ASSISTANT_HOME}/tasks/history.json" > /dev/null

if [ ! -d "${ASSISTANT_HOME}/.git" ]; then
  git init "${ASSISTANT_HOME}"

  GIT_DIR="${ASSISTANT_HOME}/.git"
  GIT_WORK_TREE="${ASSISTANT_HOME}"

  GIT_DIR="${GIT_DIR}" GIT_WORK_TREE="${GIT_WORK_TREE}" git add config.json knowledge/learning.json tasks/tasks.json tasks/history.json

  if ! GIT_DIR="${GIT_DIR}" GIT_WORK_TREE="${GIT_WORK_TREE}" git diff --cached --quiet; then
    GIT_DIR="${GIT_DIR}" GIT_WORK_TREE="${GIT_WORK_TREE}" git commit -m "chore: bootstrap AI assistant structure"
  fi
fi

echo "✓ Bootstrap complete"
