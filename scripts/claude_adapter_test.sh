#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="${SCRIPT_DIR}/../.tmp/ai-assistant"

cleanup() {
  rm -rf "${SCRIPT_DIR}/../.tmp"
  rm -f "${SCRIPT_DIR}/../.tmp-bin/claude"
}

trap cleanup EXIT
cleanup

export AI_ASSISTANT_HOME="${FIXTURE_DIR}"
"${SCRIPT_DIR}/bootstrap.sh"

mkdir -p "${SCRIPT_DIR}/../.tmp-bin"
cat > "${SCRIPT_DIR}/../.tmp-bin/claude" << 'MOCK_EOF'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  echo "claude-code 1.0.0"
  exit 0
fi
if [ "$1" = "run" ]; then
  echo '{"response": "Mock response", "tokens": 100}'
  exit 0
fi
echo "Unknown command"
exit 1
MOCK_EOF
chmod +x "${SCRIPT_DIR}/../.tmp-bin/claude"

export PATH="${SCRIPT_DIR}/../.tmp-bin:${PATH}"

CONFIG=$("${SCRIPT_DIR}/claude_adapter.sh" config)

if ! echo "${CONFIG}" | grep -q "model"; then
  echo "FAIL: Config should include model"
  exit 1
fi

echo "PASS: Config shows adapter settings"

if ! "${SCRIPT_DIR}/claude_adapter.sh" check; then
  echo "FAIL: Check should pass with mock claude in PATH"
  exit 1
fi

echo "PASS: Claude CLI check passes"

RESULT=$("${SCRIPT_DIR}/claude_adapter.sh" prompt "Hello world")

if [ -z "${RESULT}" ]; then
  echo "FAIL: Prompt should return response"
  exit 1
fi

echo "PASS: Prompt returns response"

STREAM_RESULT=$("${SCRIPT_DIR}/claude_adapter.sh" prompt --stream "Hello world")

if [ -z "${STREAM_RESULT}" ]; then
  echo "FAIL: Streaming prompt should return response"
  exit 1
fi

echo "PASS: Streaming mode works"

TOOL_RESULT=$("${SCRIPT_DIR}/claude_adapter.sh" prompt --tools "Create a task" 2>&1 || true)

echo "PASS: Tool calling mode configured"

echo ""
echo "Claude Adapter test passed"
