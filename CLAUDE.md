# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Second Brain is a personal AI assistant that captures thoughts via Telegram (text/voice), organizes them automatically into a Notion knowledge graph, and provides daily briefings. The system learns user patterns and acts autonomously on low-risk tasks.

## Commands

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the Telegram bot
python -m assistant run

# Send morning briefing manually
python -m assistant briefing

# Check configuration
python -m assistant check

# Process offline queue (sync pending items to Notion)
python -m assistant sync

# Run tests
pytest

# Run single test
pytest tests/test_parser.py::TestParser::test_parse_simple_task -v

# Lint and format
ruff check src tests
ruff format src tests

# Type check
mypy src

# Verify script (checks knowledge base, git, docker, claude CLI)
scripts/verify.sh

# Ralph autonomous loop (with tmux monitoring)
ralph --monitor

# Ralph loop with limits (30 min timeout, 50 calls/hour)
ralph --timeout 30 --calls 50

# View Ralph loop status
ralph --status

# Reset circuit breaker if stuck
ralph --reset-circuit
```

## Architecture

### Core Flow
```
Telegram Message → Parser → Confidence Check → Notion Storage
                              ↓
                    High (≥80%)  →  Create Task + Log
                    Low (<80%)   →  Add to Inbox (needs_clarification=true)
```

### Package Structure (src/assistant/)
- `config.py` - Pydantic settings from `.env` (all API keys, Notion DB IDs)
- `cli.py` - Entry point with subcommands: run, briefing, check, sync
- `telegram/bot.py` - aiogram-based Telegram bot using long-polling
- `telegram/handlers.py` - Message handlers (currently minimal)
- `services/parser.py` - NLP extraction of intent, dates, people, places
- `services/processor.py` - Orchestrates parsing → Notion storage → response
- `services/briefing.py` - Morning briefing generation
- `notion/client.py` - Async Notion API client with retry, offline queue, deduplication
- `notion/schemas.py` - Pydantic models for all Notion databases
- `google/auth.py` - OAuth flow for Calendar/Gmail/Drive
- `google/maps.py` - Places geocoding and travel time calculations
- `google/drive.py` - Document/sheet creation

### Key Design Patterns

**Confidence-based routing**: `Parser.parse()` returns a `ParsedIntent` with a confidence score (0-100). Messages with confidence < 80 are flagged for human review rather than acted upon.

**Idempotency**: Every action uses an idempotency key (`telegram:{chat_id}:{message_id}`) to prevent duplicate processing on retries.

**Offline queue**: When Notion is unavailable, requests queue to `~/.second-brain/queue/pending.jsonl` and replay on recovery.

**Soft deletes**: Records use `deleted_at` timestamp instead of hard deletion for recoverability.

## Notion Database Schema

The system uses 9 interconnected Notion databases:
- **Inbox** - Raw captures awaiting processing
- **Tasks** - Actions with status, priority, due dates, linked people/projects
- **People** - Contacts with relationship type, preferences, aliases
- **Projects** - Grouped work with status and related tasks
- **Places** - Locations with geocoded coordinates
- **Preferences** - Learned user preferences
- **Patterns** - Trigger→meaning mappings learned from corrections
- **Emails** - Cached Gmail threads with extracted tasks
- **Log** - Audit trail of all actions

Database IDs are configured via `NOTION_*_DB_ID` environment variables.

## Configuration

All configuration via environment variables (`.env` file):

**Required:**
- `TELEGRAM_BOT_TOKEN` - From @BotFather
- `NOTION_API_KEY` - From notion.so/my-integrations
- `NOTION_*_DB_ID` - Database IDs for each entity type

**Optional:**
- `OPENAI_API_KEY` - For Whisper transcription
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` - OAuth for Calendar/Gmail/Drive
- `GOOGLE_MAPS_API_KEY` - For place enrichment
- `USER_TIMEZONE` - Default "UTC"
- `CONFIDENCE_THRESHOLD` - Default 80

## Ralph Loop Integration

This project uses the Ralph Loop contract (`Prompt.md`) for autonomous development:

**Loop State Files:**
- `.ralph/PROGRESS.md` - Append-only session log
- `.ralph/TASKS.json` - Structured backlog with stable IDs
- `.ralph/NEEDS_INPUT.md` - Created when blocked (if exists)

**Ralph-claude-code Convention Files:**
- `@fix_plan.md` - Prioritized task checklist (from TASKS.json)
- `@AGENT.md` - Build/run/test instructions

**Autonomous Execution:**
- `ralph --monitor` - Run loop with tmux dashboard
- `ralph --timeout 30 --calls 50` - With safety limits
- Status reporting via `---RALPH_STATUS---` block (see Prompt.md §12)

**Completion Criteria:**
- Tasks marked complete only when acceptance tests pass
- PRD acceptance tests (AT-101 through AT-127) define verifiable criteria

## Testing Conventions

- Tests in `tests/` use pytest with `pytest-asyncio`
- Test file pattern: `test_*.py`
- Parser tests freeze timezone to `America/Los_Angeles` for determinism
- Notion client tests should mock httpx responses
