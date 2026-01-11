#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <knowledge_index.json>"
  exit 2
fi

FILE="$1"

if [ ! -f "$FILE" ]; then
  echo "✗ missing file: $FILE"
  exit 1
fi

jq -e '.schema_version == "1.0"' "$FILE" > /dev/null
jq -e 'has("documents") and (.documents | type == "array")' "$FILE" > /dev/null
jq -e '.documents[] | (has("id") and ( .id | type == "string" ) and ( .id | length > 0 ))' "$FILE" > /dev/null
jq -e '.documents[] | (has("path") and ( .path | type == "string" ) and ( .path | length > 0 ))' "$FILE" > /dev/null
jq -e '.documents[] | (has("content_type") and ( .content_type | type == "string" ) and ( .content_type | length > 0 ))' "$FILE" > /dev/null
jq -e '.documents[] | (has("sha256") and ( .sha256 | type == "string" ) and ( .sha256 | test("^[a-f0-9]{64}$") ))' "$FILE" > /dev/null
jq -e '.documents[] | (has("tags") and ( .tags | type == "array" ) and ( [ .tags[] | type == "string" ] | all ))' "$FILE" > /dev/null
jq -e '.documents[] | (has("added_at") and ( .added_at | type == "string" ) and ( .added_at | length > 0 ))' "$FILE" > /dev/null

if jq -e '.documents[] | has("updated_at")' "$FILE" > /dev/null 2>&1; then
  jq -e '.documents[] | ( .updated_at | type == "string" )' "$FILE" > /dev/null
fi

echo "✓ Knowledge index valid"
