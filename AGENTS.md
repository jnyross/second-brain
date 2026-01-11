# PROJECT KNOWLEDGE BASE

**Generated:** 2026-01-11
**Commit:** no-commit
**Branch:** main

## OVERVIEW
Documentation-first repository for a HITL personal assistant. Current code is limited to bootstrap scripts and Ralph loop artifacts; core app code is not yet implemented.

## STRUCTURE
```
./
├── PRD.md                 # Requirements + acceptance tests
├── Prompt.md              # Ralph loop contract (rarely changes)
├── scripts/
│   ├── bootstrap.sh       # Initializes ~/.ai-assistant
│   └── bootstrap_test.sh  # Idempotency + artifact checks
├── docs/plans/            # Design notes and implementation plans
└── .ralph/                # Loop state (PROGRESS.md, TASKS.json)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Requirements | `PRD.md` | Acceptance tests + verify/run commands.
| Loop rules | `Prompt.md` | Non‑negotiables and iteration algorithm.
| Bootstrap logic | `scripts/bootstrap.sh` | Uses `AI_ASSISTANT_HOME` and `jq`.
| Bootstrap test | `scripts/bootstrap_test.sh` | Uses `.tmp/ai-assistant` fixture.
| Task state | `.ralph/TASKS.json` | Stable task IDs and pass evidence.
| Progress log | `.ralph/PROGRESS.md` | Append-only run history.

## COMMANDS
```bash
# One-time setup
scripts/bootstrap.sh

# Bootstrap validation
scripts/bootstrap_test.sh
```

## CONVENTIONS
- Shell scripts use `bash` with `set -euo pipefail`.
- `AI_ASSISTANT_HOME` controls target directory; tests use `.tmp/ai-assistant`.
- `jq` is required for JSON validation in scripts.
- Treat `Prompt.md` as read-only unless explicitly changing contract rules.
- Ralph loop files (`.ralph/PROGRESS.md`, `.ralph/TASKS.json`) are append-only in practice.

## ANTI-PATTERNS (THIS PROJECT)
- Don’t claim completion without running required checks.
- Don’t weaken acceptance criteria or tests to force a pass.
- Don’t introduce secrets into the repo or logs.
- Don’t rewrite `Prompt.md` history; bump version + append changelog if required.

## NOTES
- No CI/build configuration is present yet.
- Core application code directories (e.g., `src/`) have not been introduced.
