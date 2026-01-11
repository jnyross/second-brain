#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_ROOT="${REPO_ROOT}/.tmp/ai-assistant"

trap 'rm -rf "${TARGET_ROOT}"' EXIT

rm -rf "${TARGET_ROOT}"
mkdir -p "${TARGET_ROOT}"

export AI_ASSISTANT_HOME="${TARGET_ROOT}"

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

"${REPO_ROOT}/scripts/bootstrap.sh"
"${REPO_ROOT}/scripts/bootstrap.sh"

for dir in knowledge tasks calendar contacts security; do
  if [ ! -d "${TARGET_ROOT}/${dir}" ]; then
    echo "Missing directory: ${dir}"
    exit 1
  fi
done

if [ ! -f "${TARGET_ROOT}/config.json" ]; then
  echo "Missing config.json"
  exit 1
fi

if [ ! -f "${TARGET_ROOT}/knowledge/learning.json" ]; then
  echo "Missing learning.json"
  exit 1
fi

jq -e '.' "${TARGET_ROOT}/config.json" > /dev/null
jq -e '.' "${TARGET_ROOT}/knowledge/learning.json" > /dev/null

if [ ! -d "${TARGET_ROOT}/.git" ]; then
  echo "Missing git repository"
  exit 1
fi

echo "Bootstrap test passed"
