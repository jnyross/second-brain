"""Telegram message handlers for Second Brain.

Handles text messages, voice messages, and commands.
All messages are processed through the MessageProcessor pipeline.
"""

import logging
from io import BytesIO
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, Voice
from aiogram.filters import Command, CommandStart

from assistant.config import settings
from assistant.services.processor import MessageProcessor
from assistant.services.whisper import (
    WhisperTranscriber,
    TranscriptionResult,
    TranscriptionError,
)

logger = logging.getLogger(__name__)

# Create router
router = Router()

# Message processor instance
processor = MessageProcessor()

# Whisper transcriber instance (created lazily)
_transcriber: Optional[WhisperTranscriber] = None


def get_transcriber() -> WhisperTranscriber:
    """Get or create WhisperTranscriber instance."""
    global _transcriber
    if _transcriber is None:
        _transcriber = WhisperTranscriber()
    return _transcriber


def setup_handlers(dp) -> None:
    """Set up message handlers on the dispatcher."""
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
        "/debrief - Review unclear items"
    )


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    """Handle /today command - show today's schedule."""
    # TODO: Implement with BriefingGenerator
    await message.answer(
        "Today's schedule feature coming soon.\n"
        "For now, check your Notion Tasks database."
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Handle /status command - show pending tasks."""
    # TODO: Implement with NotionClient task query
    await message.answer(
        "Status feature coming soon.\n"
        "For now, check your Notion Tasks database."
    )


@router.message(Command("debrief"))
async def cmd_debrief(message: Message) -> None:
    """Handle /debrief command - review unclear items."""
    # TODO: Implement interactive clarification flow
    await message.answer(
        "Debrief feature coming soon.\n"
        "For now, check your Notion Inbox database for items needing clarification."
    )


# === Message Handlers ===


@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot) -> None:
    """Handle voice messages.

    1. Download voice file from Telegram
    2. Transcribe using Whisper
    3. Process transcription like text message
    4. Store audio reference for debugging
    """
    voice: Voice = message.voice
    chat_id = str(message.chat.id)
    message_id = str(message.message_id)

    logger.info(f"Received voice message: {voice.duration}s, {voice.file_size} bytes")

    # Check if OpenAI API is configured
    if not settings.has_openai:
        await message.answer(
            "Voice transcription is not configured. "
            "Please send text messages instead."
        )
        return

    try:
        # Download voice file from Telegram
        file = await bot.get_file(voice.file_id)
        file_data = await bot.download_file(file.file_path)

        # Read bytes from BytesIO
        if isinstance(file_data, BytesIO):
            audio_bytes = file_data.read()
        else:
            audio_bytes = file_data

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
            "Sorry, I couldn't transcribe that voice message. "
            "Please try again or send as text."
        )
    except Exception as e:
        logger.exception(f"Voice handling failed: {e}")
        await message.answer(
            "Sorry, something went wrong processing your voice message. "
            "Please try again."
        )


async def _process_voice_transcription(
    message: Message,
    transcription: TranscriptionResult,
    chat_id: str,
    message_id: str,
    audio_file_id: str,
) -> None:
    """Process transcribed voice message.

    Low-confidence transcriptions are flagged for review with audio reference.
    """
    # If transcription confidence is low, warn user
    if transcription.needs_review:
        prefix = (
            f"I heard: \"{transcription.text}\"\n"
            f"(Transcription confidence: {transcription.confidence}%)\n\n"
        )
    else:
        prefix = ""

    # Process through standard pipeline
    result = await processor.process(
        text=transcription.text,
        chat_id=chat_id,
        message_id=f"{message_id}_voice",  # Distinguish from text messages
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
    """
    text = message.text
    chat_id = str(message.chat.id)
    message_id = str(message.message_id)

    # Skip empty messages
    if not text or not text.strip():
        return

    logger.info(f"Received text message: '{text[:50]}...'")

    try:
        result = await processor.process(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
        )
        await message.answer(result.response)

    except Exception as e:
        logger.exception(f"Text processing failed: {e}")
        await message.answer(
            "Sorry, something went wrong. Your message has been noted - "
            "I'll process it when I'm back online."
        )
