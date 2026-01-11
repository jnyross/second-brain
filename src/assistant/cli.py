import argparse
import asyncio
import logging
import sys

from assistant.config import settings


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


async def run_bot() -> None:
    from assistant.telegram import SecondBrainBot

    if not settings.has_telegram:
        print("Error: TELEGRAM_BOT_TOKEN not configured")
        print("Set it in .env file or as environment variable")
        sys.exit(1)

    bot = SecondBrainBot()
    await bot.start()


async def send_briefing() -> None:
    from assistant.telegram import SecondBrainBot
    from assistant.services import BriefingGenerator

    if not settings.has_telegram:
        print("Error: TELEGRAM_BOT_TOKEN not configured")
        sys.exit(1)

    if not settings.user_telegram_chat_id:
        print("Error: USER_TELEGRAM_CHAT_ID not configured")
        sys.exit(1)

    generator = BriefingGenerator()
    briefing = await generator.generate_morning_briefing()

    bot = SecondBrainBot()
    await bot.send_briefing(settings.user_telegram_chat_id, briefing)
    await bot.stop()

    print("Briefing sent successfully")


async def check_config() -> None:
    print("Second Brain Configuration Check\n")

    checks = [
        ("Telegram Bot Token", settings.has_telegram),
        ("Notion API Key", settings.has_notion),
        ("OpenAI API Key", settings.has_openai),
        ("Google OAuth", settings.has_google),
        ("User Telegram Chat ID", bool(settings.user_telegram_chat_id)),
        ("Notion Inbox DB", bool(settings.notion_inbox_db_id)),
        ("Notion Tasks DB", bool(settings.notion_tasks_db_id)),
        ("Notion People DB", bool(settings.notion_people_db_id)),
        ("Notion Log DB", bool(settings.notion_log_db_id)),
    ]

    all_required_ok = True
    for name, configured in checks:
        status = "OK" if configured else "MISSING"
        symbol = "+" if configured else "-"
        print(f"  [{symbol}] {name}: {status}")
        if name in ["Telegram Bot Token", "Notion API Key"] and not configured:
            all_required_ok = False

    print()
    if all_required_ok:
        print("Required configuration present. Ready to run.")
    else:
        print("Missing required configuration. See .env.example for setup.")


async def process_queue() -> None:
    from assistant.notion import NotionClient

    if not settings.has_notion:
        print("Error: NOTION_API_KEY not configured")
        sys.exit(1)

    notion = NotionClient()
    try:
        count = await notion.process_offline_queue()
        print(f"Processed {count} queued items")
    finally:
        await notion.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Second Brain Personal Assistant")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("run", help="Start the Telegram bot")
    subparsers.add_parser("briefing", help="Send morning briefing")
    subparsers.add_parser("check", help="Check configuration")
    subparsers.add_parser("sync", help="Process offline queue")

    args = parser.parse_args()

    setup_logging()

    if args.command == "run":
        asyncio.run(run_bot())
    elif args.command == "briefing":
        asyncio.run(send_briefing())
    elif args.command == "check":
        asyncio.run(check_config())
    elif args.command == "sync":
        asyncio.run(process_queue())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
