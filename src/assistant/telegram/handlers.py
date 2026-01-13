"""Telegram message handlers for Second Brain.

Handles text messages, voice messages, and commands.
All messages are processed through the MessageProcessor pipeline.
"""

import logging
from datetime import UTC, datetime
from io import BytesIO

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Voice

from assistant.config import settings
from assistant.services.corrections import (
    get_correction_handler,
    is_correction_message,
    track_created_task,
)
from assistant.services.processor import MessageProcessor
from assistant.services.whisper import (
    TranscriptionError,
    TranscriptionResult,
    WhisperTranscriber,
)

logger = logging.getLogger(__name__)

# Create router
router = Router()

# Message processor instance
processor = MessageProcessor()

# Whisper transcriber instance (created lazily)
_transcriber: WhisperTranscriber | None = None


def get_transcriber() -> WhisperTranscriber:
    """Get or create WhisperTranscriber instance."""
    global _transcriber
    if _transcriber is None:
        _transcriber = WhisperTranscriber()
    return _transcriber


def setup_handlers(dp: Dispatcher) -> None:
    """Set up message handlers on the dispatcher."""
    # Import debrief router for FSM-based /debrief command
    from assistant.telegram.debrief import router as debrief_router

    # Include debrief router first (needs to handle /debrief before other text handlers)
    dp.include_router(debrief_router)
    # Include main router
    dp.include_router(router)


# === Command Handlers ===


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    await message.answer(
        "Hello! I'm your Second Brain assistant.\n\n"
        "Send me text or voice messages to capture thoughts, tasks, and ideas.\n\n"
        "Commands:\n"
        "/today - See today's schedule\n"
        "/status - Check pending tasks\n"
        "/debrief - Review unclear items\n"
        "/help - Show this help message"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(
        "**Second Brain Assistant**\n\n"
        "Just send me text or voice messages like:\n"
        "- 'Buy milk tomorrow'\n"
        "- 'Call Sarah at 3pm'\n"
        "- 'Meeting with Mike at Starbucks'\n\n"
        "I'll automatically create tasks and remember details.\n\n"
        "**Commands:**\n"
        "/today - See today's schedule\n"
        "/status - Check pending tasks\n"
        "/debrief - Review unclear items\n"
        "/setup_google - Connect Google Calendar/Gmail"
    )


@router.message(Command("setup_google"))
async def cmd_setup_google(message: Message) -> None:
    """Handle /setup_google command - initiate Google OAuth flow."""
    from assistant.google.auth import google_auth

    # Check if already authenticated
    if google_auth.load_saved_credentials() and google_auth.is_authenticated():
        await message.answer(
            "✅ **Google already connected!**\n\n"
            "Calendar, Gmail, and Drive integration is active.\n\n"
            "To reconnect with a different account, delete the token "
            "and run /setup_google again."
        )
        return

    # Generate auth URL
    auth_url = google_auth.get_auth_url()

    if not auth_url:
        await message.answer(
            "❌ **Google OAuth not configured**\n\n"
            "The server needs a google_credentials.json file. "
            "Please contact the administrator."
        )
        return

    # Note: Don't use parse_mode here - the auth URL contains special chars
    await message.answer(
        "🔐 Connect Google Account\n\n"
        "1. Click this link to authorize:\n"
        f"{auth_url}\n\n"
        "2. After authorizing, you'll be redirected to a page "
        "(it might say 'This site can't be reached').\n\n"
        "3. Copy the ENTIRE URL from your browser's address bar "
        "and send it to me.\n\n"
        "The URL will contain a code I need to complete the connection."
    )


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    """Handle /today command - show today's schedule and due tasks."""
    try:
        today_message = await _generate_today_message()
        await message.answer(today_message, parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Today command failed: {e}")
        await message.answer("Sorry, couldn't fetch today's schedule. Please try again later.")


async def _generate_today_message() -> str:
    """Generate today's schedule message with calendar events and due tasks.

    Returns formatted message showing:
    - Today's calendar events
    - Tasks due today
    """
    from datetime import timedelta

    from assistant.notion.client import NotionClient

    sections = []

    # Get calendar events
    try:
        from assistant.google.calendar import list_todays_events

        events = await list_todays_events()

        if events:
            lines = ["📅 **TODAY'S SCHEDULE**"]
            for event in events[:10]:
                # Format time
                time_str = _format_event_time(event.start_time, event.end_time)
                line = f"• {time_str} - {event.title}"
                if event.location:
                    line += f" @ {event.location}"
                lines.append(line)
            sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(f"Could not fetch calendar events: {e}")
        # Calendar not configured is ok, continue with tasks

    # Get tasks due today
    client = NotionClient()
    try:
        today = datetime.now(UTC).date()
        today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC)
        today_end = datetime.combine(today, datetime.max.time()).replace(tzinfo=UTC)

        due_tasks = await client.query_tasks(
            due_before=today_end + timedelta(days=1),
            due_after=today_start - timedelta(days=1),
            exclude_statuses=["done", "cancelled"],
            limit=10,
        )

        if due_tasks:
            lines = ["✅ **DUE TODAY**"]
            for task in due_tasks[:10]:
                title = _extract_task_prop(task, "title")
                priority = _extract_task_prop(task, "priority")

                if title:
                    line = f"• {title}"
                    if priority in ("urgent", "high"):
                        line = f"🔴 {line[2:]}"  # Replace bullet with priority
                    lines.append(line)
            sections.append("\n".join(lines))

    finally:
        await client.close()

    # Build final message
    if sections:
        message = "\n\n".join(sections)

        # Add date header
        today_str = datetime.now(UTC).strftime("%A, %B %d")
        header = f"📆 **{today_str}**\n\n"

        return header + message
    else:
        today_str = datetime.now(UTC).strftime("%A, %B %d")
        return (
            f"📆 **{today_str}**\n\n"
            "✨ **Nothing scheduled!**\n\n"
            "No calendar events or tasks due today.\n"
            "Enjoy your free time!"
        )


def _format_event_time(start: datetime, end: datetime) -> str:
    """Format event time range for display."""
    # Check if all-day event (start and end at midnight)
    if start.hour == 0 and start.minute == 0:
        if end.hour == 0 and end.minute == 0:
            return "All day"

    # Format as HH:MM - HH:MM
    start_str = start.strftime("%H:%M")
    end_str = end.strftime("%H:%M")

    # If same time (event with no duration), just show start
    if start_str == end_str:
        return start_str

    return f"{start_str}-{end_str}"


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Handle /status command - show pending tasks and flagged items."""
    try:
        status_message = await _generate_status_message()
        await message.answer(status_message, parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Status command failed: {e}")
        await message.answer("Sorry, couldn't fetch your status. Please try again later.")


async def _generate_status_message() -> str:
    """Generate status message with pending tasks and flagged items.

    Returns formatted message showing:
    - Pending tasks (todo/doing status)
    - Flagged inbox items (needs_clarification=true)
    """
    from assistant.notion.client import NotionClient

    client = NotionClient()
    sections = []

    try:
        # Query pending tasks (todo and doing)
        todo_tasks = await client.query_tasks(status="todo", limit=10)
        doing_tasks = await client.query_tasks(status="doing", limit=5)

        # Query flagged inbox items
        flagged_items = await client.query_inbox(
            needs_clarification=True,
            processed=False,
            limit=5,
        )

        # Format DOING section (tasks in progress)
        if doing_tasks:
            lines = ["🔄 **IN PROGRESS**"]
            for task in doing_tasks[:5]:
                title = _extract_task_prop(task, "title")
                if title:
                    lines.append(f"• {title}")
            sections.append("\n".join(lines))

        # Format TODO section (pending tasks)
        if todo_tasks:
            lines = ["📋 **PENDING TASKS**"]
            for task in todo_tasks[:10]:
                title = _extract_task_prop(task, "title")
                due_str = _extract_task_prop(task, "due_date")
                priority = _extract_task_prop(task, "priority")

                if title:
                    line = f"• {title}"
                    if due_str:
                        # Format due date briefly
                        line += f" (due: {_format_due_brief(due_str)})"
                    if priority in ("urgent", "high"):
                        line = f"🔴 {line[2:]}"  # Replace bullet with priority
                    lines.append(line)
            sections.append("\n".join(lines))

        # Format FLAGGED section (needs clarification)
        if flagged_items:
            lines = ["⚠️ **NEEDS CLARIFICATION**"]
            for item in flagged_items[:5]:
                raw = _extract_inbox_prop(item, "raw_input")
                if raw:
                    # Truncate long items
                    display = raw[:40] + "..." if len(raw) > 40 else raw
                    lines.append(f'• "{display}"')
            sections.append("\n".join(lines))

        # Build final message
        if sections:
            message = "\n\n".join(sections)

            # Add summary
            total_tasks = len(todo_tasks) + len(doing_tasks)
            total_flagged = len(flagged_items)

            message += f"\n\n📊 _Total: {total_tasks} tasks, {total_flagged} flagged_"

            if total_flagged > 0:
                message += "\n_Use /debrief to review flagged items._"

            return message
        else:
            return (
                "✨ **All clear!**\n\n"
                "No pending tasks or flagged items.\n"
                "Send me a message to capture something new."
            )

    finally:
        await client.close()


def _extract_task_prop(task: dict, prop: str) -> str | None:
    """Extract a property value from a Notion task result."""
    props = task.get("properties", {})

    if prop == "title":
        title_data = props.get("title", {})
        title_list = title_data.get("title", [])
        if title_list:
            return title_list[0].get("text", {}).get("content", "")
    elif prop == "due_date":
        due_data = props.get("due_date", {})
        date_obj = due_data.get("date", {})
        if date_obj:
            return date_obj.get("start", "")
    elif prop == "priority":
        priority_data = props.get("priority", {})
        select_obj = priority_data.get("select", {})
        if select_obj:
            return select_obj.get("name", "")
    elif prop == "status":
        status_data = props.get("status", {})
        select_obj = status_data.get("select", {})
        if select_obj:
            return select_obj.get("name", "")

    return None


def _extract_inbox_prop(item: dict, prop: str) -> str | None:
    """Extract a property value from a Notion inbox result."""
    props = item.get("properties", {})

    if prop == "raw_input":
        data = props.get("raw_input", {})
        text_list = data.get("rich_text", [])
        if text_list:
            return text_list[0].get("text", {}).get("content", "")

    return None


def _format_due_brief(due_str: str) -> str:
    """Format a due date string briefly for status display."""
    try:
        # Parse ISO format date
        if "T" in due_str:
            due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
        else:
            due_dt = datetime.fromisoformat(due_str)

        # Make timezone-aware if not already
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        diff = due_dt.date() - now.date()

        if diff.days == 0:
            return "today"
        elif diff.days == 1:
            return "tomorrow"
        elif diff.days < 0:
            return f"{abs(diff.days)}d overdue"
        elif diff.days < 7:
            return due_dt.strftime("%A")  # Day name
        else:
            return due_dt.strftime("%b %d")  # "Jan 15"

    except (ValueError, AttributeError):
        return due_str[:10] if len(due_str) > 10 else due_str


# Note: /debrief command is handled by debrief.py module with FSM support


# === Message Handlers ===


@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot) -> None:
    """Handle voice messages.

    1. Download voice file from Telegram
    2. Transcribe using Whisper
    3. Process transcription like text message
    4. Store audio reference for debugging
    """
    voice: Voice | None = message.voice
    if voice is None:
        return
    chat_id = str(message.chat.id)
    message_id = str(message.message_id)

    logger.info(f"Received voice message: {voice.duration}s, {voice.file_size} bytes")

    # Check if OpenAI API is configured
    if not settings.has_openai:
        await message.answer(
            "Voice transcription is not configured. Please send text messages instead."
        )
        return

    try:
        # Download voice file from Telegram
        file = await bot.get_file(voice.file_id)
        if file.file_path is None:
            await message.answer("Sorry, I couldn't get the voice file. Please try again.")
            return
        file_data = await bot.download_file(file.file_path)

        # Read bytes from BytesIO or BinaryIO
        audio_bytes: bytes
        if isinstance(file_data, BytesIO):
            audio_bytes = file_data.read()
        elif hasattr(file_data, "read"):
            # Handle other BinaryIO types
            audio_bytes = file_data.read()  # type: ignore[union-attr]
        elif file_data is not None:
            audio_bytes = file_data
        else:
            await message.answer("Sorry, I couldn't download the voice file. Please try again.")
            return

        # Transcribe using Whisper
        transcriber = get_transcriber()
        result = await transcriber.transcribe(
            audio_data=audio_bytes,
            filename=f"voice_{message_id}.ogg",
        )

        logger.info(
            f"Transcribed voice: '{result.text[:50]}...' "
            f"(confidence: {result.confidence}%, language: {result.language})"
        )

        # Process transcription
        await _process_voice_transcription(
            message=message,
            transcription=result,
            chat_id=chat_id,
            message_id=message_id,
            audio_file_id=voice.file_id,
        )

    except TranscriptionError as e:
        logger.error(f"Transcription failed: {e}")
        await message.answer(
            "Sorry, I couldn't transcribe that voice message. Please try again or send as text."
        )
    except Exception as e:
        logger.exception(f"Voice handling failed: {e}")
        await message.answer(
            "Sorry, something went wrong processing your voice message. Please try again."
        )


async def _process_voice_transcription(
    message: Message,
    transcription: TranscriptionResult,
    chat_id: str,
    message_id: str,
    audio_file_id: str,
) -> None:
    """Process transcribed voice message.

    T-117: Low-confidence transcriptions are flagged for review with audio reference.
    Voice metadata (file_id, transcript_confidence, language) is passed to processor
    so it can be stored in inbox items for later review.
    """
    # If transcription confidence is low, warn user
    if transcription.needs_review:
        prefix = (
            f'I heard: "{transcription.text}"\n'
            f"(Transcription confidence: {transcription.confidence}%)\n\n"
        )
    else:
        prefix = ""

    # T-117: Process through pipeline with voice metadata
    # This ensures inbox items include transcript_confidence and voice_file_id
    result = await processor.process(
        text=transcription.text,
        chat_id=chat_id,
        message_id=f"{message_id}_voice",  # Distinguish from text messages
        voice_file_id=audio_file_id,
        transcript_confidence=transcription.confidence,
        language=transcription.language,
    )

    # Add transcription info to response
    response = prefix + result.response

    # Add audio reference note if low confidence
    if transcription.needs_review:
        response += "\n\n_Audio saved for review._"

    await message.answer(response)


@router.message(F.text)
async def handle_text(message: Message) -> None:
    """Handle text messages.

    Process through MessageProcessor pipeline which:
    - Parses intent, entities, dates
    - Routes based on confidence
    - Creates tasks or flags for review

    Also handles corrections like "Wrong, I said Tess not Jess".
    """
    text = message.text
    chat_id = str(message.chat.id)
    message_id = str(message.message_id)

    # Skip empty messages
    if not text or not text.strip():
        return

    logger.info(f"Received text message: '{text[:50]}...'")

    try:
        # Check if this is a Google OAuth callback URL/code
        if await _try_google_oauth_code(message, text):
            return

        # Check if this is a correction first
        if is_correction_message(text):
            handler = get_correction_handler()
            correction_result = await handler.process_correction(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
            )

            if correction_result.is_correction:
                await message.answer(correction_result.message)
                return

        # Normal message processing
        result = await processor.process(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
        )

        # Track the created task for potential future correction
        if result.task_id:
            # Extract the task title from the response
            # The response format is "Got it. <title>..."
            task_title = _extract_task_title(result.response)
            track_created_task(
                chat_id=chat_id,
                message_id=message_id,
                task_id=result.task_id,
                title=task_title,
            )

        await message.answer(result.response)

    except Exception as e:
        logger.exception(f"Text processing failed: {e}")
        await message.answer(
            "Sorry, something went wrong. Your message has been noted - "
            "I'll process it when I'm back online."
        )


async def _try_google_oauth_code(message: Message, text: str) -> bool:
    """Check if text contains a Google OAuth code and complete auth if so.

    Returns True if the text was an OAuth callback (handled), False otherwise.
    """
    # Only check if it looks like a callback URL or code
    if not ("code=" in text or "localhost" in text.lower() or len(text) > 30):
        return False

    from assistant.google.auth import extract_oauth_code, google_auth

    # Check if already authenticated
    if google_auth.is_authenticated():
        return False

    # Try to extract OAuth code
    code = extract_oauth_code(text)
    if not code:
        return False

    logger.info("Detected Google OAuth callback, attempting to complete auth")

    # Try to complete authentication
    if google_auth.complete_auth_with_code(code):
        await message.answer(
            "✅ **Google connected successfully!**\n\n"
            "Calendar, Gmail, and Drive integration is now active.\n\n"
            "You can now use:\n"
            "• /today - See calendar events\n"
            "• Tasks will sync to Google Calendar"
        )
        return True
    else:
        await message.answer(
            "❌ **Authentication failed**\n\n"
            "The code might have expired or been invalid.\n"
            "Please try /setup_google again to get a fresh link."
        )
        return True


def _extract_task_title(response: str) -> str:
    """Extract the task title from a processor response.

    Response format is typically: "Got it. <title>, <date> with <people> at <place>."
    We want to extract just the title portion.
    """
    # Remove "Got it. " prefix
    if response.startswith("Got it. "):
        response = response[8:]

    # Find the first comma or period to get the title
    for sep in [",", "."]:
        if sep in response:
            return response.split(sep)[0].strip()

    return response.strip()
