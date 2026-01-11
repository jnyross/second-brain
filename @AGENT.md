# @AGENT.md — Build & Run Instructions

**Project:** Second Brain - Personal AI Assistant
**Language:** Python 3.12
**Last updated:** 2026-01-11

---

## Setup & Operations

### Installation
```bash
# Create virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

### Running the Application
```bash
# Start Telegram bot (main entry point)
python -m assistant run

# Send morning briefing manually
python -m assistant briefing

# Check configuration
python -m assistant check

# Process offline queue
python -m assistant sync
```

### Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/assistant --cov-report=term-missing

# Run single test
pytest tests/test_parser.py::TestParser::test_parse_simple_task -v

# Run async tests only
pytest -m asyncio
```

### Code Quality
```bash
# Lint
ruff check src tests

# Format
ruff format src tests

# Type check
mypy src

# Full verification (all gates)
scripts/verify.sh
```

---

## Key Learnings

*Document build optimizations and setup gotchas as discovered:*

- Parser tests freeze timezone to `America/Los_Angeles` for determinism
- Notion client tests should mock httpx responses
- Use `pytest-asyncio` for async test support
- `.env` file is gitignored; use `.env.example` as template

---

## Feature Development Quality Standards

### Testing Requirements

**Coverage:** 85% code coverage ratio required for all new code.

**Test Types:**
- Unit tests: Test individual functions/methods in isolation
- Integration tests: Test component interactions (e.g., Parser → Processor)
- End-to-end tests: Test full message flow (Telegram → Notion)

**Validation:**
```bash
pytest --cov=src/assistant --cov-report=term-missing
# Coverage must be >= 85% for modified files
```

### Git Workflow

**Commit Format:** Use conventional commits
```
feat(parser): add entity extraction for places
fix(notion): handle rate limit errors gracefully
test(processor): add integration tests for voice messages
docs(readme): update installation instructions
```

**Branch Strategy:**
- `main` - stable, deployable
- Feature branches: `feat/entity-extraction`, `fix/rate-limiting`

**CI/CD Validation:**
- All tests must pass before merge
- Coverage must not decrease
- Linting/formatting must pass

### Documentation

Keep these synchronized with implementation:
- Code docstrings for public APIs
- `CLAUDE.md` for architecture overview
- `@AGENT.md` for build/test commands
- `PRD.md` for requirements (read-only during implementation)

### Completion Checklist

Before marking any task complete:

- [ ] All tests pass (`pytest`)
- [ ] Coverage >= 85% for new code
- [ ] Linting passes (`ruff check src tests`)
- [ ] Formatting applied (`ruff format src tests`)
- [ ] Type checking passes (`mypy src`)
- [ ] `scripts/verify.sh` exits 0
- [ ] Code committed with conventional commit message
- [ ] `.ralph/TASKS.json` updated with evidence
- [ ] `.ralph/PROGRESS.md` appended with iteration entry

---

## Architecture Reference

### Core Flow
```
Telegram Message → Parser → Confidence Check → Notion Storage
                              ↓
                    High (≥80%)  →  Create Task + Log
                    Low (<80%)   →  Add to Inbox (needs_clarification=true)
```

### Package Structure
```
src/assistant/
├── config.py          # Pydantic settings from .env
├── cli.py             # Entry point (run, briefing, check, sync)
├── telegram/
│   ├── bot.py         # aiogram bot with long-polling
│   └── handlers.py    # Message handlers
├── services/
│   ├── parser.py      # NLP extraction
│   ├── processor.py   # Orchestration
│   └── briefing.py    # Morning briefings
├── notion/
│   ├── client.py      # Async API client
│   └── schemas.py     # Pydantic models
└── google/
    ├── auth.py        # OAuth flow
    ├── maps.py        # Places API
    └── drive.py       # Drive API
```

### Key Patterns

- **Confidence-based routing**: Score 0-100, threshold at 80%
- **Idempotency**: Key format `telegram:{chat_id}:{message_id}`
- **Offline queue**: `~/.second-brain/queue/pending.jsonl`
- **Soft deletes**: `deleted_at` timestamp

---

## Rationale

These standards ensure:
- **Quality**: Bugs caught early via testing and type checking
- **Traceability**: Conventional commits enable changelog generation
- **Maintainability**: Consistent formatting and documentation
- **Reliability**: CI gates prevent regressions
- **Automation**: Ralph loops can verify completion objectively

AI agents should automatically apply these standards to all feature development tasks.
