#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_ROOT="${REPO_ROOT}/.tmp/ai-assistant"
FAKE_BIN="${TARGET_ROOT}/.fake-bin"

trap 'rm -rf "${TARGET_ROOT}"' EXIT

rm -rf "${TARGET_ROOT}"
mkdir -p "${TARGET_ROOT}" "${FAKE_BIN}"

cat > "${FAKE_BIN}/claude" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

cat > "${FAKE_BIN}/docker" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

chmod +x "${FAKE_BIN}/claude" "${FAKE_BIN}/docker"

export PATH="${FAKE_BIN}:${PATH}"
export AI_ASSISTANT_HOME="${TARGET_ROOT}"

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

"${REPO_ROOT}/scripts/bootstrap.sh"

"${REPO_ROOT}/scripts/verify.sh"

echo "Verify test passed"
