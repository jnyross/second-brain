#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
LEARNING_FILE="${ASSISTANT_HOME}/knowledge/learning.json"

ensure_learning_file() {
  mkdir -p "${ASSISTANT_HOME}/knowledge"
  if [ ! -f "${LEARNING_FILE}" ]; then
    cat > "${LEARNING_FILE}" << 'EOF'
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
}

generate_id() {
  local count
  count=$(jq '.learnings | length' "${LEARNING_FILE}")
  printf "L-%03d" "$((count + 1))"
}

get_timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

calculate_confidence() {
  local count="$1"
  local confidence
  confidence=$(echo "scale=2; 0.5 + (${count} - 1) * 0.1" | bc -l)
  if [ "$(echo "${confidence} > 0.95" | bc -l)" -eq 1 ]; then
    confidence="0.95"
  fi
  echo "${confidence}"
}

pattern_to_regex() {
  local pattern="$1"
  local regex="${pattern}"
  regex="${regex//\[item\]/[a-zA-Z0-9 ]+}"
  regex="${regex//\[name\]/[a-zA-Z ]+}"
  regex="${regex//\[number\]/[0-9]+}"
  regex="${regex//\[date\]/[0-9-]+}"
  regex="${regex//\[time\]/[0-9:]+}"
  echo "^${regex}$"
}

cmd_add_correction() {
  local pattern="$1"
  local correction="$2"
  ensure_learning_file
  
  local existing
  existing=$(jq -r --arg pattern "${pattern}" '.learnings[] | select(.pattern == $pattern)' "${LEARNING_FILE}")
  
  local timestamp
  timestamp=$(get_timestamp)
  
  if [ -n "${existing}" ]; then
    local new_count
    new_count=$(echo "${existing}" | jq -r '.count + 1')
    local new_confidence
    new_confidence=$(calculate_confidence "${new_count}")
    
    jq --arg pattern "${pattern}" --argjson count "${new_count}" --arg conf "${new_confidence}" --arg ts "${timestamp}" \
      '(.learnings[] | select(.pattern == $pattern)) |= . + {count: $count, confidence: ($conf | tonumber)}
       | .last_updated = $ts' \
      "${LEARNING_FILE}" > "${LEARNING_FILE}.tmp"
    mv "${LEARNING_FILE}.tmp" "${LEARNING_FILE}"
  else
    local id
    id=$(generate_id)
    local confidence
    confidence=$(calculate_confidence 1)
    
    local new_entry
    new_entry=$(jq -n --arg id "${id}" --arg pattern "${pattern}" --arg correction "${correction}" --arg conf "${confidence}" \
      '{id: $id, pattern: $pattern, correction: $correction, count: 1, confidence: ($conf | tonumber)}')
    
    jq --argjson entry "${new_entry}" --arg ts "${timestamp}" \
      '.learnings += [$entry] | .last_updated = $ts' \
      "${LEARNING_FILE}" > "${LEARNING_FILE}.tmp"
    mv "${LEARNING_FILE}.tmp" "${LEARNING_FILE}"
  fi
  
  echo "Learning recorded: ${pattern} -> ${correction}"
}

cmd_match() {
  local input="$1"
  ensure_learning_file
  
  local learnings
  learnings=$(jq -c '.learnings[]' "${LEARNING_FILE}" 2>/dev/null || echo "")
  
  if [ -z "${learnings}" ]; then
    echo ""
    return 0
  fi
  
  local best_match=""
  local best_confidence=0
  
  while IFS= read -r learning; do
    [ -z "${learning}" ] && continue
    
    local pattern
    pattern=$(echo "${learning}" | jq -r '.pattern')
    local confidence
    confidence=$(echo "${learning}" | jq -r '.confidence')
    
    local regex
    regex=$(pattern_to_regex "${pattern}")
    
    if echo "${input}" | grep -qE "${regex}" 2>/dev/null; then
      if [ "$(echo "${confidence} > ${best_confidence}" | bc -l)" -eq 1 ]; then
        best_match="${learning}"
        best_confidence="${confidence}"
      fi
    fi
  done <<< "${learnings}"
  
  if [ -n "${best_match}" ]; then
    echo "${best_match}"
  else
    echo ""
  fi
}

cmd_list() {
  ensure_learning_file
  jq '.learnings' "${LEARNING_FILE}"
}

cmd_clear() {
  ensure_learning_file
  jq '.learnings = [] | .last_updated = null' "${LEARNING_FILE}" > "${LEARNING_FILE}.tmp"
  mv "${LEARNING_FILE}.tmp" "${LEARNING_FILE}"
  echo "Learning database cleared"
}

usage() {
  cat << 'EOF'
Usage: learning_db.sh <command> [args]

Commands:
  add_correction <pattern> <correction>   Add or update a learning
  match <input>                           Find matching pattern for input
  list                                    List all learnings
  clear                                   Clear all learnings
EOF
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

command="$1"
shift

case "${command}" in
  add_correction)
    [ $# -ge 2 ] || usage
    cmd_add_correction "$1" "$2"
    ;;
  match)
    [ $# -ge 1 ] || usage
    cmd_match "$1"
    ;;
  list)
    cmd_list
    ;;
  clear)
    cmd_clear
    ;;
  *)
    usage
    ;;
esac
