"""Tests for Telegram message handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from io import BytesIO

from assistant.telegram.handlers import (
    router,
    setup_handlers,
    get_transcriber,
    cmd_start,
    cmd_help,
    cmd_today,
    cmd_status,
    handle_voice,
    handle_text,
    _process_voice_transcription,
)
# Note: cmd_debrief moved to assistant.telegram.debrief module
from assistant.services.whisper import TranscriptionResult, TranscriptionError


class TestSetupHandlers:
    """Tests for handler setup."""

    def test_setup_handlers_includes_routers(self):
        """setup_handlers should include both main and debrief routers."""
        mock_dp = MagicMock()
        setup_handlers(mock_dp)
        # Should include both debrief router and main router
        assert mock_dp.include_router.call_count == 2


class TestGetTranscriber:
    """Tests for transcriber lazy initialization."""

    def test_get_transcriber_creates_instance(self):
        """get_transcriber should create WhisperTranscriber."""
        # Reset global
        import assistant.telegram.handlers as handlers
        handlers._transcriber = None

        with patch("assistant.telegram.handlers.WhisperTranscriber") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance

            result = get_transcriber()

            mock_cls.assert_called_once()
            assert result == mock_instance

    def test_get_transcriber_reuses_instance(self):
        """get_transcriber should reuse existing instance."""
        import assistant.telegram.handlers as handlers

        mock_instance = MagicMock()
        handlers._transcriber = mock_instance

        result = get_transcriber()

        assert result == mock_instance


class TestCommandHandlers:
    """Tests for command handlers."""

    @pytest.mark.asyncio
    async def test_cmd_start(self):
        """Start command should send welcome message."""
        message = AsyncMock()
        await cmd_start(message)

        message.answer.assert_called_once()
        call_args = message.answer.call_args[0][0]
        assert "Hello" in call_args
        assert "Second Brain" in call_args
        assert "/help" in call_args

    @pytest.mark.asyncio
    async def test_cmd_help(self):
        """Help command should send help message."""
        message = AsyncMock()
        await cmd_help(message)

        message.answer.assert_called_once()
        call_args = message.answer.call_args[0][0]
        assert "Second Brain" in call_args
        assert "/today" in call_args
        assert "/status" in call_args

    @pytest.mark.asyncio
    async def test_cmd_today(self):
        """Today command should respond."""
        message = AsyncMock()
        await cmd_today(message)

        message.answer.assert_called_once()
        call_args = message.answer.call_args[0][0]
        assert "schedule" in call_args.lower() or "today" in call_args.lower()

    @pytest.mark.asyncio
    async def test_cmd_status(self):
        """Status command should respond."""
        message = AsyncMock()
        await cmd_status(message)

        message.answer.assert_called_once()
        call_args = message.answer.call_args[0][0]
        assert "status" in call_args.lower() or "task" in call_args.lower()

    # Note: test_cmd_debrief moved to tests/test_debrief.py
    # The /debrief command now uses FSM for interactive flow


class TestTextHandler:
    """Tests for text message handler."""

    @pytest.mark.asyncio
    async def test_handle_text_processes_message(self):
        """Text handler should process through MessageProcessor."""
        message = AsyncMock()
        message.text = "Buy milk tomorrow"
        message.chat.id = 12345
        message.message_id = 99

        with patch("assistant.telegram.handlers.processor") as mock_processor:
            mock_result = MagicMock()
            mock_result.response = "Got it. Buy milk tomorrow."
            mock_processor.process = AsyncMock(return_value=mock_result)

            await handle_text(message)

            mock_processor.process.assert_called_once_with(
                text="Buy milk tomorrow",
                chat_id="12345",
                message_id="99",
            )
            message.answer.assert_called_once_with("Got it. Buy milk tomorrow.")

    @pytest.mark.asyncio
    async def test_handle_text_skips_empty(self):
        """Text handler should skip empty messages."""
        message = AsyncMock()
        message.text = ""

        with patch("assistant.telegram.handlers.processor") as mock_processor:
            await handle_text(message)
            mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_text_skips_whitespace(self):
        """Text handler should skip whitespace-only messages."""
        message = AsyncMock()
        message.text = "   "

        with patch("assistant.telegram.handlers.processor") as mock_processor:
            await handle_text(message)
            mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_text_error_recovery(self):
        """Text handler should recover from errors gracefully."""
        message = AsyncMock()
        message.text = "Test message"
        message.chat.id = 12345
        message.message_id = 99

        with patch("assistant.telegram.handlers.processor") as mock_processor:
            mock_processor.process = AsyncMock(side_effect=Exception("DB error"))

            await handle_text(message)

            message.answer.assert_called_once()
            call_args = message.answer.call_args[0][0]
            assert "wrong" in call_args.lower()


class TestVoiceHandler:
    """Tests for voice message handler."""

    def setup_method(self):
        """Set up test fixtures."""
        self.message = AsyncMock()
        self.message.voice.file_id = "voice_file_123"
        self.message.voice.duration = 5
        self.message.voice.file_size = 10000
        self.message.chat.id = 12345
        self.message.message_id = 99

        self.bot = AsyncMock()
        self.bot.get_file = AsyncMock(return_value=MagicMock(file_path="voices/test.ogg"))
        self.bot.download_file = AsyncMock(return_value=BytesIO(b"\x00" * 100))

    @pytest.mark.asyncio
    async def test_handle_voice_no_openai(self):
        """Voice handler should reject if OpenAI not configured."""
        with patch("assistant.telegram.handlers.settings") as mock_settings:
            mock_settings.has_openai = False

            await handle_voice(self.message, self.bot)

            self.message.answer.assert_called_once()
            call_args = self.message.answer.call_args[0][0]
            assert "not configured" in call_args.lower()

    @pytest.mark.asyncio
    async def test_handle_voice_transcribes_and_processes(self):
        """Voice handler should transcribe and process through pipeline."""
        transcription = TranscriptionResult(
            text="Buy milk tomorrow",
            confidence=95,
            language="en",
            duration_seconds=2.0,
            is_low_confidence=False,
        )

        with patch("assistant.telegram.handlers.settings") as mock_settings, \
             patch("assistant.telegram.handlers.get_transcriber") as mock_get_transcriber, \
             patch("assistant.telegram.handlers.processor") as mock_processor:

            mock_settings.has_openai = True
            mock_transcriber = AsyncMock()
            mock_transcriber.transcribe = AsyncMock(return_value=transcription)
            mock_get_transcriber.return_value = mock_transcriber

            mock_result = MagicMock()
            mock_result.response = "Got it. Buy milk tomorrow."
            mock_processor.process = AsyncMock(return_value=mock_result)

            await handle_voice(self.message, self.bot)

            # Should have downloaded file
            self.bot.get_file.assert_called_once_with("voice_file_123")
            self.bot.download_file.assert_called_once()

            # Should have transcribed
            mock_transcriber.transcribe.assert_called_once()

            # Should have processed
            mock_processor.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_voice_transcription_error(self):
        """Voice handler should handle transcription errors gracefully."""
        with patch("assistant.telegram.handlers.settings") as mock_settings, \
             patch("assistant.telegram.handlers.get_transcriber") as mock_get_transcriber:

            mock_settings.has_openai = True
            mock_transcriber = AsyncMock()
            mock_transcriber.transcribe = AsyncMock(
                side_effect=TranscriptionError("API error")
            )
            mock_get_transcriber.return_value = mock_transcriber

            await handle_voice(self.message, self.bot)

            self.message.answer.assert_called_once()
            call_args = self.message.answer.call_args[0][0]
            assert "couldn't transcribe" in call_args.lower()

    @pytest.mark.asyncio
    async def test_handle_voice_download_error(self):
        """Voice handler should handle download errors gracefully."""
        self.bot.download_file = AsyncMock(side_effect=Exception("Network error"))

        with patch("assistant.telegram.handlers.settings") as mock_settings:
            mock_settings.has_openai = True

            await handle_voice(self.message, self.bot)

            self.message.answer.assert_called_once()
            call_args = self.message.answer.call_args[0][0]
            assert "wrong" in call_args.lower()


class TestProcessVoiceTranscription:
    """Tests for voice transcription processing."""

    @pytest.mark.asyncio
    async def test_high_confidence_no_prefix(self):
        """High confidence transcription should not add prefix."""
        message = AsyncMock()
        transcription = TranscriptionResult(
            text="Buy milk",
            confidence=95,
            language="en",
            duration_seconds=1.0,
            is_low_confidence=False,
        )

        with patch("assistant.telegram.handlers.processor") as mock_processor:
            mock_result = MagicMock()
            mock_result.response = "Got it."
            mock_processor.process = AsyncMock(return_value=mock_result)

            await _process_voice_transcription(
                message=message,
                transcription=transcription,
                chat_id="123",
                message_id="456",
                audio_file_id="file_id",
            )

            call_args = message.answer.call_args[0][0]
            assert "I heard" not in call_args
            assert "Got it." in call_args

    @pytest.mark.asyncio
    async def test_low_confidence_adds_prefix(self):
        """Low confidence transcription should add 'I heard' prefix."""
        message = AsyncMock()
        transcription = TranscriptionResult(
            text="mumble mumble",
            confidence=60,
            language="en",
            duration_seconds=2.0,
            is_low_confidence=True,
        )

        with patch("assistant.telegram.handlers.processor") as mock_processor:
            mock_result = MagicMock()
            mock_result.response = "Got it."
            mock_processor.process = AsyncMock(return_value=mock_result)

            await _process_voice_transcription(
                message=message,
                transcription=transcription,
                chat_id="123",
                message_id="456",
                audio_file_id="file_id",
            )

            call_args = message.answer.call_args[0][0]
            assert "I heard" in call_args
            assert "mumble mumble" in call_args
            assert "60%" in call_args
            assert "Audio saved" in call_args

    @pytest.mark.asyncio
    async def test_message_id_includes_voice_suffix(self):
        """Voice messages should have _voice suffix in message_id."""
        message = AsyncMock()
        transcription = TranscriptionResult(
            text="Test",
            confidence=90,
            language="en",
            duration_seconds=1.0,
            is_low_confidence=False,
        )

        with patch("assistant.telegram.handlers.processor") as mock_processor:
            mock_result = MagicMock()
            mock_result.response = "Got it."
            mock_processor.process = AsyncMock(return_value=mock_result)

            await _process_voice_transcription(
                message=message,
                transcription=transcription,
                chat_id="123",
                message_id="456",
                audio_file_id="file_id",
            )

            call_args = mock_processor.process.call_args
            assert call_args.kwargs["message_id"] == "456_voice"
