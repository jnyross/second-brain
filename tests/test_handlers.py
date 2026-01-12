"""Tests for Telegram message handlers."""

from datetime import UTC
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Note: cmd_debrief moved to assistant.telegram.debrief module
from assistant.services.whisper import TranscriptionError, TranscriptionResult
from assistant.telegram.handlers import (
    _extract_inbox_prop,
    _extract_task_prop,
    _format_due_brief,
    _format_event_time,
    _generate_status_message,
    _generate_today_message,
    _process_voice_transcription,
    cmd_help,
    cmd_start,
    cmd_status,
    cmd_today,
    get_transcriber,
    handle_text,
    handle_voice,
    setup_handlers,
)


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
    async def test_cmd_today_with_events_and_tasks(self):
        """Today command should show events and tasks."""
        message = AsyncMock()

        with patch(
            "assistant.telegram.handlers._generate_today_message"
        ) as mock_gen:
            mock_gen.return_value = (
                "📆 **Monday, January 12**\n\n"
                "📅 **TODAY'S SCHEDULE**\n• 09:00 - Meeting"
            )
            await cmd_today(message)

        message.answer.assert_called_once()
        call_kwargs = message.answer.call_args[1]
        assert call_kwargs.get("parse_mode") == "Markdown"

    @pytest.mark.asyncio
    async def test_cmd_today_handles_error(self):
        """Today command should handle errors gracefully."""
        message = AsyncMock()

        with patch(
            "assistant.telegram.handlers._generate_today_message"
        ) as mock_gen:
            mock_gen.side_effect = Exception("API error")
            await cmd_today(message)

        message.answer.assert_called_once()
        call_args = message.answer.call_args[0][0]
        assert "couldn't fetch" in call_args.lower()

    @pytest.mark.asyncio
    async def test_cmd_status_with_tasks_and_flagged(self):
        """Status command should show tasks and flagged items."""
        message = AsyncMock()

        with patch(
            "assistant.telegram.handlers._generate_status_message"
        ) as mock_gen:
            mock_gen.return_value = (
                "🔄 **IN PROGRESS**\n• Test task\n\n"
                "📊 _Total: 1 tasks, 0 flagged_"
            )
            await cmd_status(message)

        message.answer.assert_called_once()
        call_kwargs = message.answer.call_args[1]
        assert call_kwargs.get("parse_mode") == "Markdown"

    @pytest.mark.asyncio
    async def test_cmd_status_handles_error(self):
        """Status command should handle errors gracefully."""
        message = AsyncMock()

        with patch(
            "assistant.telegram.handlers._generate_status_message"
        ) as mock_gen:
            mock_gen.side_effect = Exception("API error")
            await cmd_status(message)

        message.answer.assert_called_once()
        call_args = message.answer.call_args[0][0]
        assert "couldn't fetch" in call_args.lower()

    # Note: test_cmd_debrief moved to tests/test_debrief.py
    # The /debrief command now uses FSM for interactive flow


class TestStatusHelpers:
    """Tests for /status command helper functions."""

    def test_extract_task_prop_title(self):
        """Should extract title from task properties."""
        task = {
            "properties": {
                "title": {
                    "title": [{"text": {"content": "Buy groceries"}}]
                }
            }
        }
        assert _extract_task_prop(task, "title") == "Buy groceries"

    def test_extract_task_prop_due_date(self):
        """Should extract due date from task properties."""
        task = {
            "properties": {
                "due_date": {
                    "date": {"start": "2026-01-15"}
                }
            }
        }
        assert _extract_task_prop(task, "due_date") == "2026-01-15"

    def test_extract_task_prop_priority(self):
        """Should extract priority from task properties."""
        task = {
            "properties": {
                "priority": {
                    "select": {"name": "high"}
                }
            }
        }
        assert _extract_task_prop(task, "priority") == "high"

    def test_extract_task_prop_status(self):
        """Should extract status from task properties."""
        task = {
            "properties": {
                "status": {
                    "select": {"name": "doing"}
                }
            }
        }
        assert _extract_task_prop(task, "status") == "doing"

    def test_extract_task_prop_missing(self):
        """Should return None for missing properties."""
        task = {"properties": {}}
        assert _extract_task_prop(task, "title") is None
        assert _extract_task_prop(task, "due_date") is None

    def test_extract_inbox_prop_raw_input(self):
        """Should extract raw_input from inbox properties."""
        item = {
            "properties": {
                "raw_input": {
                    "rich_text": [{"text": {"content": "Something unclear"}}]
                }
            }
        }
        assert _extract_inbox_prop(item, "raw_input") == "Something unclear"

    def test_extract_inbox_prop_missing(self):
        """Should return None for missing properties."""
        item = {"properties": {}}
        assert _extract_inbox_prop(item, "raw_input") is None

    def test_format_due_brief_today(self):
        """Should format today's date as 'today'."""
        from datetime import datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert _format_due_brief(today) == "today"

    def test_format_due_brief_tomorrow(self):
        """Should format tomorrow's date."""
        from datetime import datetime, timedelta

        tomorrow = (datetime.now(UTC) + timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        assert _format_due_brief(tomorrow) == "tomorrow"

    def test_format_due_brief_overdue(self):
        """Should format overdue dates."""
        from datetime import datetime, timedelta

        yesterday = (datetime.now(UTC) - timedelta(days=2)).strftime(
            "%Y-%m-%d"
        )
        assert "overdue" in _format_due_brief(yesterday)

    def test_format_due_brief_week(self):
        """Should format dates within a week as day name."""
        from datetime import datetime, timedelta

        in_3_days = datetime.now(UTC) + timedelta(days=3)
        due_str = in_3_days.strftime("%Y-%m-%d")
        result = _format_due_brief(due_str)
        # Should be a day name like "Monday", "Tuesday", etc.
        assert result in [
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"
        ]

    def test_format_due_brief_future(self):
        """Should format far future dates as 'Mon DD'."""
        from datetime import datetime, timedelta

        in_2_weeks = datetime.now(UTC) + timedelta(days=14)
        due_str = in_2_weeks.strftime("%Y-%m-%d")
        result = _format_due_brief(due_str)
        # Should be like "Jan 26"
        assert len(result) <= 7

    def test_format_due_brief_invalid(self):
        """Should handle invalid date strings."""
        assert _format_due_brief("not-a-date") == "not-a-date"


class TestGenerateStatusMessage:
    """Tests for _generate_status_message function."""

    @pytest.mark.asyncio
    async def test_generate_status_all_clear(self):
        """Should show 'All clear' when no items."""
        with patch("assistant.notion.client.NotionClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.query_tasks.return_value = []
            mock_client.query_inbox.return_value = []

            result = await _generate_status_message()

            assert "All clear" in result
            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_status_with_doing_tasks(self):
        """Should show in-progress tasks."""
        with patch("assistant.notion.client.NotionClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.query_tasks.side_effect = [
                [],  # todo tasks
                [{"properties": {"title": {"title": [
                    {"text": {"content": "Working on it"}}
                ]}}}],  # doing tasks
            ]
            mock_client.query_inbox.return_value = []

            result = await _generate_status_message()

            assert "IN PROGRESS" in result
            assert "Working on it" in result

    @pytest.mark.asyncio
    async def test_generate_status_with_todo_tasks(self):
        """Should show pending tasks."""
        with patch("assistant.notion.client.NotionClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.query_tasks.side_effect = [
                [{"properties": {"title": {"title": [
                    {"text": {"content": "Buy milk"}}
                ]}}}],  # todo tasks
                [],  # doing tasks
            ]
            mock_client.query_inbox.return_value = []

            result = await _generate_status_message()

            assert "PENDING TASKS" in result
            assert "Buy milk" in result

    @pytest.mark.asyncio
    async def test_generate_status_with_high_priority(self):
        """Should highlight high priority tasks."""
        with patch("assistant.notion.client.NotionClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.query_tasks.side_effect = [
                [{
                    "properties": {
                        "title": {"title": [
                            {"text": {"content": "Urgent task"}}
                        ]},
                        "priority": {"select": {"name": "high"}}
                    }
                }],  # todo tasks
                [],  # doing tasks
            ]
            mock_client.query_inbox.return_value = []

            result = await _generate_status_message()

            assert "🔴" in result
            assert "Urgent task" in result

    @pytest.mark.asyncio
    async def test_generate_status_with_flagged_items(self):
        """Should show flagged inbox items."""
        with patch("assistant.notion.client.NotionClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.query_tasks.return_value = []
            mock_client.query_inbox.return_value = [
                {"properties": {"raw_input": {"rich_text": [
                    {"text": {"content": "Something unclear"}}
                ]}}}
            ]

            result = await _generate_status_message()

            assert "NEEDS CLARIFICATION" in result
            assert "Something unclear" in result
            assert "/debrief" in result

    @pytest.mark.asyncio
    async def test_generate_status_shows_summary(self):
        """Should show summary with totals."""
        with patch("assistant.notion.client.NotionClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.query_tasks.side_effect = [
                [{"properties": {"title": {"title": [
                    {"text": {"content": "Task 1"}}
                ]}}}],  # todo
                [{"properties": {"title": {"title": [
                    {"text": {"content": "Task 2"}}
                ]}}}],  # doing
            ]
            mock_client.query_inbox.return_value = []

            result = await _generate_status_message()

            assert "Total:" in result
            assert "2 tasks" in result


class TestTodayHelpers:
    """Tests for /today command helper functions."""

    def test_format_event_time_normal(self):
        """Should format normal event time range."""
        from datetime import datetime

        start = datetime(2026, 1, 12, 9, 0)
        end = datetime(2026, 1, 12, 10, 30)
        assert _format_event_time(start, end) == "09:00-10:30"

    def test_format_event_time_all_day(self):
        """Should format all-day event."""
        from datetime import datetime

        start = datetime(2026, 1, 12, 0, 0)
        end = datetime(2026, 1, 13, 0, 0)
        assert _format_event_time(start, end) == "All day"

    def test_format_event_time_same_time(self):
        """Should format event with same start/end as single time."""
        from datetime import datetime

        start = datetime(2026, 1, 12, 14, 0)
        end = datetime(2026, 1, 12, 14, 0)
        assert _format_event_time(start, end) == "14:00"

    def test_format_event_time_midnight_start_not_all_day(self):
        """Should format midnight event that isn't all-day."""
        from datetime import datetime

        start = datetime(2026, 1, 12, 0, 0)
        end = datetime(2026, 1, 12, 1, 0)
        assert _format_event_time(start, end) == "00:00-01:00"


class TestGenerateTodayMessage:
    """Tests for _generate_today_message function."""

    @pytest.mark.asyncio
    async def test_generate_today_nothing_scheduled(self):
        """Should show 'Nothing scheduled' when no items."""
        with (
            patch("assistant.notion.client.NotionClient") as mock_notion_cls,
            patch(
                "assistant.google.calendar.list_todays_events",
                side_effect=Exception("No calendar"),
            ),
        ):
            mock_client = AsyncMock()
            mock_notion_cls.return_value = mock_client
            mock_client.query_tasks.return_value = []

            result = await _generate_today_message()

            assert "Nothing scheduled" in result
            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_today_with_calendar_events(self):
        """Should show calendar events."""
        from datetime import datetime

        from assistant.google.calendar import CalendarEvent

        mock_event = CalendarEvent(
            event_id="evt1",
            title="Team Meeting",
            start_time=datetime(2026, 1, 12, 9, 0),
            end_time=datetime(2026, 1, 12, 10, 0),
            timezone="UTC",
            attendees=[],
            location="Room A",
        )

        with (
            patch("assistant.notion.client.NotionClient") as mock_notion_cls,
            patch(
                "assistant.google.calendar.list_todays_events",
                return_value=[mock_event],
            ),
        ):
            mock_client = AsyncMock()
            mock_notion_cls.return_value = mock_client
            mock_client.query_tasks.return_value = []

            result = await _generate_today_message()

            assert "TODAY'S SCHEDULE" in result
            assert "Team Meeting" in result
            assert "Room A" in result

    @pytest.mark.asyncio
    async def test_generate_today_with_due_tasks(self):
        """Should show due tasks."""
        with (
            patch("assistant.notion.client.NotionClient") as mock_notion_cls,
            patch(
                "assistant.google.calendar.list_todays_events",
                side_effect=Exception("No calendar"),
            ),
        ):
            mock_client = AsyncMock()
            mock_notion_cls.return_value = mock_client
            mock_client.query_tasks.return_value = [
                {"properties": {"title": {"title": [
                    {"text": {"content": "Submit report"}}
                ]}}}
            ]

            result = await _generate_today_message()

            assert "DUE TODAY" in result
            assert "Submit report" in result

    @pytest.mark.asyncio
    async def test_generate_today_with_high_priority_task(self):
        """Should highlight high priority tasks."""
        with (
            patch("assistant.notion.client.NotionClient") as mock_notion_cls,
            patch(
                "assistant.google.calendar.list_todays_events",
                side_effect=Exception("No calendar"),
            ),
        ):
            mock_client = AsyncMock()
            mock_notion_cls.return_value = mock_client
            mock_client.query_tasks.return_value = [
                {
                    "properties": {
                        "title": {"title": [
                            {"text": {"content": "Critical task"}}
                        ]},
                        "priority": {"select": {"name": "high"}}
                    }
                }
            ]

            result = await _generate_today_message()

            assert "🔴" in result
            assert "Critical task" in result

    @pytest.mark.asyncio
    async def test_generate_today_shows_date_header(self):
        """Should show date header."""
        with (
            patch("assistant.notion.client.NotionClient") as mock_notion_cls,
            patch(
                "assistant.google.calendar.list_todays_events",
                return_value=[],
            ),
        ):
            mock_client = AsyncMock()
            mock_notion_cls.return_value = mock_client
            mock_client.query_tasks.return_value = []

            result = await _generate_today_message()

            # Should have date like "Monday, January 12"
            assert "📆" in result


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

        with (
            patch("assistant.telegram.handlers.settings") as mock_settings,
            patch("assistant.telegram.handlers.get_transcriber") as mock_get_transcriber,
            patch("assistant.telegram.handlers.processor") as mock_processor,
        ):
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
        with (
            patch("assistant.telegram.handlers.settings") as mock_settings,
            patch("assistant.telegram.handlers.get_transcriber") as mock_get_transcriber,
        ):
            mock_settings.has_openai = True
            mock_transcriber = AsyncMock()
            mock_transcriber.transcribe = AsyncMock(side_effect=TranscriptionError("API error"))
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


class TestT117WhisperConfidenceHandling:
    """Tests for T-117: Whisper confidence handling (AT-120)."""

    @pytest.mark.asyncio
    async def test_voice_metadata_passed_to_processor(self):
        """Voice transcription should pass metadata to processor."""
        message = AsyncMock()
        transcription = TranscriptionResult(
            text="Test message",
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
                audio_file_id="voice_file_abc",
            )

            # Verify voice metadata was passed
            call_kwargs = mock_processor.process.call_args.kwargs
            assert call_kwargs["voice_file_id"] == "voice_file_abc"
            assert call_kwargs["transcript_confidence"] == 95
            assert call_kwargs["language"] == "en"

    @pytest.mark.asyncio
    async def test_low_confidence_passes_metadata(self):
        """Low confidence transcription should still pass all metadata."""
        message = AsyncMock()
        transcription = TranscriptionResult(
            text="Unclear message",
            confidence=55,
            language="es",
            duration_seconds=3.0,
            is_low_confidence=True,
        )

        with patch("assistant.telegram.handlers.processor") as mock_processor:
            mock_result = MagicMock()
            mock_result.response = "Added to inbox."
            mock_processor.process = AsyncMock(return_value=mock_result)

            await _process_voice_transcription(
                message=message,
                transcription=transcription,
                chat_id="chat1",
                message_id="msg1",
                audio_file_id="voice_xyz",
            )

            call_kwargs = mock_processor.process.call_args.kwargs
            assert call_kwargs["voice_file_id"] == "voice_xyz"
            assert call_kwargs["transcript_confidence"] == 55
            assert call_kwargs["language"] == "es"


class TestAT120WhisperLowConfidence:
    """Acceptance tests for AT-120: Whisper Low Confidence Handling.

    Given: User sends voice memo with background noise
    When: Whisper returns transcript with low confidence
    Then: Inbox item created with needs_clarification=true
    And: transcript_confidence field populated
    And: Voice file reference stored
    """

    @pytest.mark.asyncio
    async def test_at120_low_confidence_creates_flagged_inbox_item(self):
        """Low confidence whisper should create flagged inbox item."""
        from assistant.notion.schemas import InboxSource
        from assistant.services.processor import MessageProcessor

        with patch("assistant.services.processor.NotionClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.create_inbox_item = AsyncMock(return_value="inbox_123")
            mock_client.log_action = AsyncMock()

            processor = MessageProcessor()
            processor.notion = mock_client

            # Simulate low-confidence Whisper transcription
            _result = await processor.process(
                text="something unclear",
                chat_id="123",
                message_id="456_voice",
                voice_file_id="voice_abc123",
                transcript_confidence=50,  # Low confidence
                language="en",
            )

            # Verify inbox item was created
            mock_client.create_inbox_item.assert_called_once()
            item = mock_client.create_inbox_item.call_args[0][0]

            # AT-120 assertions
            assert item.needs_clarification is True
            assert item.transcript_confidence == 50
            assert item.voice_file_id == "voice_abc123"
            assert item.source == InboxSource.TELEGRAM_VOICE
            assert item.language == "en"

    @pytest.mark.asyncio
    async def test_at120_high_confidence_processes_normally(self):
        """High confidence whisper should process normally (not flagged)."""
        from assistant.services.pattern_applicator import PatternApplicationResult
        from assistant.services.processor import MessageProcessor

        with (
            patch("assistant.services.processor.NotionClient") as mock_client_cls,
            patch("assistant.services.processor.settings") as mock_settings,
            patch("assistant.services.processor.PatternApplicator") as mock_pattern_cls,
        ):
            mock_settings.confidence_threshold = 80
            mock_settings.has_notion = True

            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.query_people = AsyncMock(return_value=[])
            mock_client.create_person = AsyncMock(return_value="person_1")
            mock_client.create_task = AsyncMock(return_value="task_123")
            mock_client.log_action = AsyncMock()

            # Mock pattern applicator to return no corrections
            mock_pattern = AsyncMock()
            mock_pattern_cls.return_value = mock_pattern
            mock_pattern.apply_patterns = AsyncMock(
                return_value=PatternApplicationResult(
                    original_text="Buy groceries tomorrow",
                    original_people=[],
                    original_places=[],
                    original_title="Buy groceries",
                )
            )

            processor = MessageProcessor()
            processor.notion = mock_client

            # Simulate high-confidence Whisper transcription
            # Note: "Buy groceries tomorrow" has 95% parser confidence
            result = await processor.process(
                text="Buy groceries tomorrow",
                chat_id="123",
                message_id="456_voice",
                voice_file_id="voice_def456",
                transcript_confidence=95,  # High confidence
                language="en",
            )

            # Task created, not inbox item
            mock_client.create_task.assert_called_once()
            mock_client.create_inbox_item.assert_not_called()
            assert result.task_id == "task_123"

    @pytest.mark.asyncio
    async def test_at120_borderline_confidence_flags(self):
        """Borderline whisper confidence (< 80) should flag for review."""
        from assistant.services.processor import MessageProcessor

        with patch("assistant.services.processor.NotionClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.create_inbox_item = AsyncMock(return_value="inbox_456")
            mock_client.log_action = AsyncMock()

            processor = MessageProcessor()
            processor.notion = mock_client

            # Borderline confidence (79% whisper, but parser might be higher)
            _result = await processor.process(
                text="Something",
                chat_id="123",
                message_id="789_voice",
                voice_file_id="voice_ghi789",
                transcript_confidence=79,  # Just below 80%
                language="en",
            )

            # Should be flagged due to low transcript confidence
            mock_client.create_inbox_item.assert_called_once()
            item = mock_client.create_inbox_item.call_args[0][0]
            assert item.needs_clarification is True
            assert item.transcript_confidence == 79
