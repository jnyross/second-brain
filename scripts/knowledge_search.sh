#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_HOME="${AI_ASSISTANT_HOME:-${HOME}/.ai-assistant}"
KNOWLEDGE_DIR="${ASSISTANT_HOME}/knowledge"
INDEX_FILE="${KNOWLEDGE_DIR}/.index.json"

ensure_index() {
  if [ ! -f "${INDEX_FILE}" ]; then
    echo '{"files": [], "indexed_at": null}' > "${INDEX_FILE}"
  fi
}

get_timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

cmd_index() {
  mkdir -p "${KNOWLEDGE_DIR}"
  
  local files_json="[]"
  local timestamp
  timestamp=$(get_timestamp)
  
  while IFS= read -r -d '' file; do
    local relative_path="${file#${ASSISTANT_HOME}/}"
    local content
    content=$(cat "${file}" 2>/dev/null || echo "")
    
    local words
    words=$(echo "${content}" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '\n' | sort -u | tr '\n' ' ')
    
    local entry
    entry=$(jq -n --arg path "${relative_path}" --arg words "${words}" \
      '{path: $path, keywords: $words}')
    
    files_json=$(echo "${files_json}" | jq --argjson entry "${entry}" '. += [$entry]')
  done < <(find "${KNOWLEDGE_DIR}" -type f \( -name "*.md" -o -name "*.txt" -o -name "*.json" \) ! -name ".index.json" -print0 2>/dev/null)
  
  jq -n --argjson files "${files_json}" --arg ts "${timestamp}" \
    '{files: $files, indexed_at: $ts}' > "${INDEX_FILE}"
  
  local count
  count=$(echo "${files_json}" | jq 'length')
  echo "Indexed ${count} files"
}

cmd_search() {
  local query="$1"
  ensure_index
  
  local query_lower
  query_lower=$(echo "${query}" | tr '[:upper:]' '[:lower:]')
  
  local query_words
  query_words=$(echo "${query_lower}" | tr -cs '[:alnum:]' '\n' | grep -v '^$' || true)
  
  local results=""
  
  while IFS= read -r file_entry; do
    [ -z "${file_entry}" ] && continue
    
    local path
    path=$(echo "${file_entry}" | jq -r '.path')
    local keywords
    keywords=$(echo "${file_entry}" | jq -r '.keywords')
    
    local match_count=0
    for word in ${query_words}; do
      if echo "${keywords}" | grep -qw "${word}"; then
        match_count=$((match_count + 1))
      fi
    done
    
    if [ "${match_count}" -gt 0 ]; then
      local full_path="${ASSISTANT_HOME}/${path}"
      if [ -f "${full_path}" ]; then
        local matching_line
        matching_line=$(grep -i -m 1 "${query_lower%% *}" "${full_path}" 2>/dev/null | head -1 || echo "")
        
        if [ -z "${matching_line}" ]; then
          matching_line=$(head -3 "${full_path}" | tail -1)
        fi
        
        matching_line=$(echo "${matching_line}" | sed 's/^[#* ]*//' | head -c 100)
        
        if [ -n "${results}" ]; then
          results="${results}\n"
        fi
        results="${results}According to ${path}: ${matching_line}"
      fi
    fi
  done < <(jq -c '.files[]' "${INDEX_FILE}" 2>/dev/null)
  
  if [ -n "${results}" ]; then
    echo -e "${results}"
  else
    echo "No results found for: ${query}"
  fi
}

cmd_list() {
  ensure_index
  jq -r '.files[].path' "${INDEX_FILE}"
}

cmd_get() {
  local path="$1"
  local full_path="${ASSISTANT_HOME}/${path}"
  
  if [ -f "${full_path}" ]; then
    cat "${full_path}"
  else
    echo "File not found: ${path}" >&2
    exit 1
  fi
}

usage() {
  cat << 'EOF'
Usage: knowledge_search.sh <command> [args]

Commands:
  index              Index all knowledge base files
  search <query>     Search knowledge base
  list               List indexed files
  get <path>         Get file content
EOF
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

command="$1"
shift

case "${command}" in
  index) cmd_index ;;
  search) [ $# -ge 1 ] || usage; cmd_search "$1" ;;
  list) cmd_list ;;
  get) [ $# -ge 1 ] || usage; cmd_get "$1" ;;
  *) usage ;;
esac
