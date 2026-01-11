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

mkdir -p "${FIXTURE_DIR}/knowledge"
cat > "${FIXTURE_DIR}/knowledge/preferences.md" << 'EOF'
# User Preferences

## Display Settings
User prefers dark mode for all applications.

## Language
Primary language is English.
EOF

cat > "${FIXTURE_DIR}/knowledge/projects.md" << 'EOF'
# Active Projects

## Project Alpha
Status: In progress
Due: 2026-02-01

## Project Beta
Status: Planning
EOF

"${SCRIPT_DIR}/knowledge_search.sh" index

if [ ! -f "${FIXTURE_DIR}/knowledge/.index.json" ]; then
  echo "FAIL: Index file not created"
  exit 1
fi

echo "PASS: Index created"

RESULT=$("${SCRIPT_DIR}/knowledge_search.sh" search "dark mode")

if ! echo "${RESULT}" | grep -q "knowledge/preferences.md"; then
  echo "FAIL: Search should return citation to preferences.md"
  echo "Got: ${RESULT}"
  exit 1
fi

if ! echo "${RESULT}" | grep -q "prefers dark mode"; then
  echo "FAIL: Search should include matching content"
  echo "Got: ${RESULT}"
  exit 1
fi

echo "PASS: Search returns citation with content"

RESULT=$("${SCRIPT_DIR}/knowledge_search.sh" search "display preferences")

if ! echo "${RESULT}" | grep -q "knowledge/preferences.md"; then
  echo "FAIL: Keyword search should find preferences.md"
  exit 1
fi

echo "PASS: Keyword search works"

RESULT=$("${SCRIPT_DIR}/knowledge_search.sh" search "Project Alpha")

if ! echo "${RESULT}" | grep -q "knowledge/projects.md"; then
  echo "FAIL: Should find projects.md for Project Alpha"
  exit 1
fi

echo "PASS: Multi-file search works"

RESULT=$("${SCRIPT_DIR}/knowledge_search.sh" search "nonexistent xyz 12345")

if [ -n "${RESULT}" ] && ! echo "${RESULT}" | grep -q "No results"; then
  echo "FAIL: Should return empty or 'No results' for nonexistent query"
  exit 1
fi

echo "PASS: No results for unknown query"

FILES=$("${SCRIPT_DIR}/knowledge_search.sh" list)
COUNT=$(echo "${FILES}" | wc -l)

if [ "${COUNT}" -lt 2 ]; then
  echo "FAIL: List should show at least 2 indexed files"
  exit 1
fi

echo "PASS: List indexed files works"

echo ""
echo "Knowledge Search test passed"
