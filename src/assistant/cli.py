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
    from assistant.services import BriefingGenerator
    from assistant.telegram import SecondBrainBot

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
    """Process offline queue and sync to Notion (AT-115)."""
    from assistant.services.offline_queue import (
        get_offline_queue,
        process_offline_queue,
    )

    if not settings.has_notion:
        print("Error: NOTION_API_KEY not configured")
        sys.exit(1)

    queue = get_offline_queue()
    pending_count = queue.get_pending_count()

    if pending_count == 0:
        print("No pending items in offline queue")
        return

    print(f"Processing {pending_count} queued items...")

    result = await process_offline_queue()

    print("\nSync results:")
    print(f"  Successful: {result.successful}")
    print(f"  Deduplicated: {result.deduplicated}")
    print(f"  Failed: {result.failed}")

    if result.errors:
        print("\nErrors:")
        for error in result.errors:
            print(f"  - {error}")

    if result.all_successful:
        print("\nAll items synced successfully!")
    elif result.failed > 0:
        print(f"\n{result.failed} items remain in queue for retry")


async def send_nudges() -> None:
    """Send proactive nudges for upcoming tasks (T-130)."""
    from assistant.services.nudges import run_nudges

    if not settings.has_telegram:
        print("Error: TELEGRAM_BOT_TOKEN not configured")
        sys.exit(1)

    if not settings.user_telegram_chat_id:
        print("Error: USER_TELEGRAM_CHAT_ID not configured")
        sys.exit(1)

    if not settings.has_notion:
        print("Error: NOTION_API_KEY not configured")
        sys.exit(1)

    print("Checking for tasks to nudge...")

    report = await run_nudges()

    print("\nNudge results:")
    print(f"  Candidates found: {report.candidates_found}")
    print(f"  Nudges sent: {report.nudges_sent}")
    print(f"  Skipped (already nudged): {report.nudges_skipped}")
    print(f"  Failed: {report.nudges_failed}")

    if report.results:
        print("\nDetails:")
        for result in report.results:
            status = "Sent" if result.success else f"Failed: {result.error}"
            print(f"  - [{result.nudge_type.value}] {status}")

    if report.nudges_sent > 0:
        print("\nNudges sent successfully!")
    elif report.candidates_found == 0:
        print("\nNo tasks need nudging right now.")
    elif report.nudges_skipped == report.candidates_found:
        print("\nAll candidates already nudged today.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Second Brain Personal Assistant")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("run", help="Start the Telegram bot")
    subparsers.add_parser("briefing", help="Send morning briefing")
    subparsers.add_parser("check", help="Check configuration")
    subparsers.add_parser("sync", help="Process offline queue")
    subparsers.add_parser("nudge", help="Send proactive task reminders")

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
    elif args.command == "nudge":
        asyncio.run(send_nudges())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
