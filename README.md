# Second Brain

Personal AI Assistant that captures thoughts via Telegram (text/voice), organizes them automatically into a Notion knowledge graph, and provides daily briefings.

## Features

- **Telegram Integration**: Capture thoughts via text or voice messages
- **Notion Knowledge Graph**: Automatically organize and link information
- **Daily Briefings**: Morning summaries of tasks, calendar, and priorities
- **Smart Parsing**: Extract dates, people, places, and intent from natural language
- **Confidence-Based Routing**: High-confidence actions execute automatically; low-confidence items go to inbox for review

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Run the bot
python -m assistant run
```

## Configuration

Required environment variables:
- `TELEGRAM_BOT_TOKEN` - From @BotFather
- `NOTION_API_KEY` - From notion.so/my-integrations
- `NOTION_*_DB_ID` - Database IDs for each entity type

Optional:
- `OPENAI_API_KEY` - For Whisper voice transcription
- `GOOGLE_*` - OAuth credentials for Calendar/Gmail/Drive integration

## Development

```bash
# Run tests
pytest

# Lint and format
ruff check src tests
ruff format src tests

# Type check
mypy src
```

## License

MIT
