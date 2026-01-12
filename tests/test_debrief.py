"""Tests for the /debrief command and interactive clarification flow.

Tests AT-107: On-Demand Debrief
- User sends /debrief command
- Interactive review session starts when there are items with needs_clarification=true
- Each unclear item presented for clarification
- All needs_clarification items addressed or skipped
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.services.clarification import ClarificationResult, UnclearItem
from assistant.telegram.debrief import (
    DebriefStates,
    _dict_to_entities,
    _dict_to_item,
    _end_debrief_session,
    _entities_to_dict,
    _format_due_date,
    _format_entity_summary,
    _format_item_for_review,
    _is_cancel_command,
    _item_to_dict,
    _should_ask_for_due_date,
    cmd_debrief,
    handle_debrief_response,
    handle_due_date_response,
    setup_debrief_handlers,
)


class TestDebriefCommand:
    """Tests for /debrief command initialization."""

    @pytest.mark.asyncio
    async def test_debrief_no_items(self):
        """When no unclear items, should show 'all clear' message."""
        message = AsyncMock()
        message.chat.id = 12345
        state = AsyncMock()

        with patch("assistant.telegram.debrief.ClarificationService") as MockService:
            mock_service = AsyncMock()
            mock_service.get_unclear_items.return_value = []
            MockService.return_value = mock_service

            await cmd_debrief(message, state)

            # Should show all clear message
            message.answer.assert_called_once()
            call_args = message.answer.call_args[0][0]
            assert "All clear" in call_args
            assert "No items need clarification" in call_args

    @pytest.mark.asyncio
    async def test_debrief_starts_session(self):
        """When items exist, should start interactive session."""
        message = AsyncMock()
        message.chat.id = 12345
        state = AsyncMock()

        items = [
            UnclearItem(
                id="page-1",
                raw_input="that thing tomorrow",
                interpretation="Task: that thing",
                confidence=55,
                source="telegram_text",
                timestamp=datetime(2026, 1, 11, 10, 30),
            )
        ]

        with patch("assistant.telegram.debrief.ClarificationService") as MockService:
            mock_service = AsyncMock()
            mock_service.get_unclear_items.return_value = items
            MockService.return_value = mock_service

            await cmd_debrief(message, state)

            # Should store items in state
            state.update_data.assert_called_once()
            call_kwargs = state.update_data.call_args[1]
            assert len(call_kwargs["items"]) == 1
            assert call_kwargs["current_index"] == 0

            # Should set state to reviewing
            state.set_state.assert_called_once_with(DebriefStates.reviewing)

            # Should show intro and first item
            message.answer.assert_called_once()
            call_args = message.answer.call_args[0][0]
            assert "Debrief Session" in call_args
            assert "item(s)" in call_args  # Count shown with markdown bold
            assert "that thing tomorrow" in call_args

    @pytest.mark.asyncio
    async def test_debrief_multiple_items(self):
        """Should show correct count for multiple items."""
        message = AsyncMock()
        message.chat.id = 12345
        state = AsyncMock()

        items = [
            UnclearItem(
                id=f"page-{i}",
                raw_input=f"item {i}",
                interpretation=None,
                confidence=50,
                source="telegram_text",
                timestamp=datetime.now(),
            )
            for i in range(5)
        ]

        with patch("assistant.telegram.debrief.ClarificationService") as MockService:
            mock_service = AsyncMock()
            mock_service.get_unclear_items.return_value = items
            MockService.return_value = mock_service

            await cmd_debrief(message, state)

            call_args = message.answer.call_args[0][0]
            assert "**5**" in call_args  # Count shown with markdown bold
            assert "item(s)" in call_args


class TestDebriefResponse:
    """Tests for handling user responses during debrief."""

    def setup_method(self):
        """Set up common test fixtures."""
        self.message = AsyncMock()
        self.message.chat.id = 12345
        self.state = AsyncMock()

        self.items_data = [
            {
                "id": "page-1",
                "raw_input": "that thing",
                "interpretation": "Task: that thing",
                "confidence": 55,
                "source": "telegram_text",
                "timestamp": "2026-01-11T10:30:00",
                "voice_transcript": False,
            },
            {
                "id": "page-2",
                "raw_input": "another thing",
                "interpretation": None,
                "confidence": 45,
                "source": "telegram_voice",
                "timestamp": "2026-01-11T11:00:00",
                "voice_transcript": True,
            },
        ]

    @pytest.mark.asyncio
    async def test_done_command_ends_session(self):
        """User typing 'done' should end session early."""
        self.message.text = "done"
        self.state.get_data.return_value = {
            "items": self.items_data,
            "current_index": 0,
            "chat_id": "12345",
            "stats": {"clarified": 1, "skipped": 0, "dismissed": 0},
        }

        with patch("assistant.telegram.debrief._get_remaining_count") as mock_count:
            mock_count.return_value = 1

            await handle_debrief_response(self.message, self.state)

            # Should clear state
            self.state.clear.assert_called_once()

            # Should show summary
            call_args = self.message.answer.call_args[0][0]
            assert "Debrief Complete" in call_args
            assert "1 task(s) created" in call_args

    @pytest.mark.asyncio
    async def test_skip_command_dismisses_item(self):
        """User typing 'skip' should dismiss current item."""
        self.message.text = "skip"
        self.state.get_data.return_value = {
            "items": self.items_data,
            "current_index": 0,
            "chat_id": "12345",
            "stats": {"clarified": 0, "skipped": 0, "dismissed": 0},
        }

        with patch("assistant.telegram.debrief.ClarificationService") as MockService:
            mock_service = AsyncMock()
            mock_service.dismiss_item.return_value = ClarificationResult(
                item_id="page-1",
                action="dismissed",
            )
            MockService.return_value = mock_service

            await handle_debrief_response(self.message, self.state)

            # Should dismiss the item
            mock_service.dismiss_item.assert_called_once_with(
                "page-1", reason="Skipped in debrief"
            )

            # Should show skip message
            calls = self.message.answer.call_args_list
            assert any("Skipped" in str(call) for call in calls)

            # Should advance to next item
            state_calls = self.state.update_data.call_args_list
            assert any(
                call[1].get("current_index") == 1 for call in state_calls
            ) or any(
                len(call[0]) > 0 and call[0][0] == 1 for call in state_calls
            )

    @pytest.mark.asyncio
    async def test_clarification_creates_task(self):
        """User typing clarification should create task.

        T-083: Updated to handle actionable tasks that trigger due date question.
        For actionable items like 'Buy milk', the flow asks for due date first.
        """
        # Use a general description without action words to skip due date prompt
        self.message.text = "Groceries from the store"
        self.state.get_data.return_value = {
            "items": self.items_data,
            "current_index": 0,
            "chat_id": "12345",
            "stats": {"clarified": 0, "skipped": 0, "dismissed": 0},
        }

        with patch("assistant.telegram.debrief.ClarificationService") as MockService:
            mock_service = AsyncMock()
            mock_service.create_task_from_item.return_value = ClarificationResult(
                item_id="page-1",
                action="created_task",
                task_id="task-123",
                message="Created task: Groceries from the store",
            )
            MockService.return_value = mock_service

            await handle_debrief_response(self.message, self.state)

            # Should create task with user's clarification
            # T-083: Now includes entity linking parameters
            mock_service.create_task_from_item.assert_called_once()
            call_kwargs = mock_service.create_task_from_item.call_args[1]
            assert call_kwargs["item_id"] == "page-1"
            assert call_kwargs["title"] == "Groceries from the store"
            assert call_kwargs["chat_id"] == "12345"

            # Should show success message
            calls = self.message.answer.call_args_list
            assert any("Created task" in str(call) for call in calls)
            assert any("Groceries from the store" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_last_item_ends_session(self):
        """Processing last item should end session."""
        self.message.text = "Final task"
        self.state.get_data.return_value = {
            "items": [self.items_data[0]],  # Only one item
            "current_index": 0,
            "chat_id": "12345",
            "stats": {"clarified": 0, "skipped": 0, "dismissed": 0},
        }

        with patch("assistant.telegram.debrief.ClarificationService") as MockService, \
             patch("assistant.telegram.debrief._get_remaining_count") as mock_count:
            mock_service = AsyncMock()
            mock_service.create_task_from_item.return_value = ClarificationResult(
                item_id="page-1",
                action="created_task",
                task_id="task-123",
            )
            MockService.return_value = mock_service
            mock_count.return_value = 0

            await handle_debrief_response(self.message, self.state)

            # Should clear state (ending session)
            self.state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_response_prompts_user(self):
        """Empty response should ask user to provide input."""
        self.message.text = "   "  # whitespace only
        self.state.get_data.return_value = {
            "items": self.items_data,
            "current_index": 0,
            "chat_id": "12345",
            "stats": {"clarified": 0, "skipped": 0, "dismissed": 0},
        }

        await handle_debrief_response(self.message, self.state)

        # Should prompt user
        call_args = self.message.answer.call_args[0][0]
        assert "Please type" in call_args or "skip" in call_args.lower()

    @pytest.mark.asyncio
    async def test_handles_task_creation_error(self):
        """Should handle errors gracefully when task creation fails."""
        self.message.text = "Some task"
        self.state.get_data.return_value = {
            "items": self.items_data,
            "current_index": 0,
            "chat_id": "12345",
            "stats": {"clarified": 0, "skipped": 0, "dismissed": 0},
        }

        with patch("assistant.telegram.debrief.ClarificationService") as MockService:
            mock_service = AsyncMock()
            mock_service.create_task_from_item.return_value = ClarificationResult(
                item_id="page-1",
                action="error",
                message="API error",
            )
            MockService.return_value = mock_service

            await handle_debrief_response(self.message, self.state)

            # Should show error message but continue
            calls = self.message.answer.call_args_list
            assert any("Couldn't create task" in str(call) for call in calls)


class TestFormatItemForReview:
    """Tests for _format_item_for_review helper."""

    def test_formats_basic_item(self):
        """Should format basic unclear item."""
        item = UnclearItem(
            id="page-1",
            raw_input="buy milk tomorrow",
            interpretation=None,
            confidence=60,
            source="telegram_text",
            timestamp=datetime(2026, 1, 11, 10, 30),
        )

        result = _format_item_for_review(item, 1, 5)

        assert "Item 1 of 5" in result
        assert "buy milk tomorrow" in result
        assert "60%" in result
        assert "What did you mean?" in result

    def test_shows_voice_indicator(self):
        """Should show voice indicator for transcribed items."""
        item = UnclearItem(
            id="page-1",
            raw_input="voice input",
            interpretation=None,
            confidence=50,
            source="telegram_voice",
            timestamp=datetime.now(),
            voice_transcript=True,
        )

        result = _format_item_for_review(item, 1, 1)

        assert "voice" in result.lower()

    def test_shows_interpretation_if_available(self):
        """Should show AI interpretation when available."""
        item = UnclearItem(
            id="page-1",
            raw_input="that thing",
            interpretation="Possibly: buy milk",
            confidence=55,
            source="telegram_text",
            timestamp=datetime.now(),
        )

        result = _format_item_for_review(item, 1, 1)

        assert "I thought" in result
        assert "Possibly: buy milk" in result

    def test_includes_instructions(self):
        """Should include user instructions."""
        item = UnclearItem(
            id="page-1",
            raw_input="test",
            interpretation=None,
            confidence=50,
            source="telegram_text",
            timestamp=datetime.now(),
        )

        result = _format_item_for_review(item, 1, 1)

        assert "skip" in result.lower()
        assert "done" in result.lower()


class TestItemSerialization:
    """Tests for item serialization to/from FSM storage."""

    def test_item_to_dict(self):
        """Should convert UnclearItem to dict."""
        item = UnclearItem(
            id="page-1",
            raw_input="test input",
            interpretation="test interpretation",
            confidence=65,
            source="telegram_text",
            timestamp=datetime(2026, 1, 11, 10, 30),
            voice_transcript=True,
        )

        result = _item_to_dict(item)

        assert result["id"] == "page-1"
        assert result["raw_input"] == "test input"
        assert result["interpretation"] == "test interpretation"
        assert result["confidence"] == 65
        assert result["voice_transcript"] is True
        assert "2026-01-11" in result["timestamp"]

    def test_dict_to_item(self):
        """Should convert dict back to UnclearItem."""
        data = {
            "id": "page-1",
            "raw_input": "test input",
            "interpretation": "test interpretation",
            "confidence": 65,
            "source": "telegram_text",
            "timestamp": "2026-01-11T10:30:00",
            "voice_transcript": True,
        }

        result = _dict_to_item(data)

        assert result.id == "page-1"
        assert result.raw_input == "test input"
        assert result.interpretation == "test interpretation"
        assert result.confidence == 65
        assert result.voice_transcript is True
        assert result.timestamp == datetime(2026, 1, 11, 10, 30)

    def test_roundtrip_serialization(self):
        """Should maintain data through serialization roundtrip."""
        original = UnclearItem(
            id="page-123",
            raw_input="original input",
            interpretation=None,
            confidence=42,
            source="telegram_voice",
            timestamp=datetime(2026, 1, 15, 14, 30, 45),
            voice_transcript=False,
        )

        serialized = _item_to_dict(original)
        restored = _dict_to_item(serialized)

        assert restored.id == original.id
        assert restored.raw_input == original.raw_input
        assert restored.interpretation == original.interpretation
        assert restored.confidence == original.confidence
        assert restored.source == original.source
        assert restored.voice_transcript == original.voice_transcript


class TestEndDebriefSession:
    """Tests for _end_debrief_session helper."""

    @pytest.mark.asyncio
    async def test_shows_summary_with_clarified(self):
        """Should show clarified count in summary."""
        message = AsyncMock()
        state = AsyncMock()
        stats = {"clarified": 3, "skipped": 1, "dismissed": 0}

        with patch("assistant.telegram.debrief._get_remaining_count") as mock_count:
            mock_count.return_value = 0

            await _end_debrief_session(message, state, stats)

            state.clear.assert_called_once()
            call_args = message.answer.call_args[0][0]
            assert "3 task(s) created" in call_args
            assert "1 item(s) skipped" in call_args

    @pytest.mark.asyncio
    async def test_shows_remaining_count(self):
        """Should show remaining items if any."""
        message = AsyncMock()
        state = AsyncMock()
        stats = {"clarified": 1, "skipped": 0, "dismissed": 0}

        with patch("assistant.telegram.debrief._get_remaining_count") as mock_count:
            mock_count.return_value = 5

            await _end_debrief_session(message, state, stats)

            call_args = message.answer.call_args[0][0]
            assert "5 item(s) still need review" in call_args

    @pytest.mark.asyncio
    async def test_shows_celebration_when_done(self):
        """Should show celebration when all items reviewed."""
        message = AsyncMock()
        state = AsyncMock()
        stats = {"clarified": 2, "skipped": 1, "dismissed": 0}

        with patch("assistant.telegram.debrief._get_remaining_count") as mock_count:
            mock_count.return_value = 0

            await _end_debrief_session(message, state, stats)

            call_args = message.answer.call_args[0][0]
            assert "All items have been reviewed" in call_args


class TestSetupHandlers:
    """Tests for handler setup."""

    def test_setup_includes_router(self):
        """setup_debrief_handlers should include router on dispatcher."""
        mock_dp = MagicMock()

        setup_debrief_handlers(mock_dp)

        mock_dp.include_router.assert_called_once()


class TestAT107:
    """Acceptance test for AT-107: On-Demand Debrief.

    Given: User sends /debrief command
    When: There are items with needs_clarification=true
    Then: Interactive review session starts
    And: Each unclear item presented for clarification
    Pass condition: All needs_clarification items addressed or skipped
    """

    @pytest.mark.asyncio
    async def test_at107_full_debrief_flow(self):
        """Complete debrief flow: start -> clarify -> skip -> done."""
        # Setup
        message = AsyncMock()
        message.chat.id = 12345
        state = AsyncMock()

        items = [
            UnclearItem(
                id="page-1",
                raw_input="first unclear item",
                interpretation="Maybe task 1",
                confidence=50,
                source="telegram_text",
                timestamp=datetime.now(),
            ),
            UnclearItem(
                id="page-2",
                raw_input="second unclear item",
                interpretation=None,
                confidence=40,
                source="telegram_voice",
                timestamp=datetime.now(),
                voice_transcript=True,
            ),
        ]

        # Step 1: Start debrief
        with patch("assistant.telegram.debrief.ClarificationService") as MockService:
            mock_service = AsyncMock()
            mock_service.get_unclear_items.return_value = items
            MockService.return_value = mock_service

            await cmd_debrief(message, state)

            # Should start session with 2 items
            call_args = message.answer.call_args[0][0]
            assert "**2**" in call_args  # Count shown with markdown bold
            assert "item(s)" in call_args
            assert "first unclear item" in call_args

        # Step 2: Clarify first item
        # T-083: Use a non-actionable phrase to skip due date question
        message.reset_mock()
        message.text = "Groceries for dinner"  # No action word = skip due date question
        state.get_data.return_value = {
            "items": [_item_to_dict(item) for item in items],
            "current_index": 0,
            "chat_id": "12345",
            "stats": {"clarified": 0, "skipped": 0, "dismissed": 0},
        }

        with patch("assistant.telegram.debrief.ClarificationService") as MockService:
            mock_service = AsyncMock()
            mock_service.create_task_from_item.return_value = ClarificationResult(
                item_id="page-1",
                action="created_task",
                task_id="task-1",
            )
            MockService.return_value = mock_service

            await handle_debrief_response(message, state)

            # Should create task
            mock_service.create_task_from_item.assert_called_once()

            # Should advance to item 2
            calls = [str(call) for call in message.answer.call_args_list]
            assert any("Created task" in call for call in calls)
            assert any("second unclear item" in call for call in calls)

        # Step 3: Skip second item
        message.reset_mock()
        message.text = "skip"
        state.get_data.return_value = {
            "items": [_item_to_dict(item) for item in items],
            "current_index": 1,
            "chat_id": "12345",
            "stats": {"clarified": 1, "skipped": 0, "dismissed": 0},
        }

        with patch("assistant.telegram.debrief.ClarificationService") as MockService, \
             patch("assistant.telegram.debrief._get_remaining_count") as mock_count:
            mock_service = AsyncMock()
            mock_service.dismiss_item.return_value = ClarificationResult(
                item_id="page-2",
                action="dismissed",
            )
            MockService.return_value = mock_service
            mock_count.return_value = 0

            await handle_debrief_response(message, state)

            # Should dismiss item
            mock_service.dismiss_item.assert_called_once()

            # Should end session (was last item)
            state.clear.assert_called()

            # Should show summary
            calls = [str(call) for call in message.answer.call_args_list]
            assert any("Debrief Complete" in call for call in calls)
            assert any("1 task(s) created" in call for call in calls)
            assert any("1 item(s) skipped" in call or "Skipped" in call for call in calls)


class TestT083CancelPatterns:
    """Tests for T-083: Cancel pattern detection."""

    def test_is_cancel_command_basic(self):
        """Should recognize 'cancel' as cancel command."""
        assert _is_cancel_command("cancel") is True
        assert _is_cancel_command("Cancel") is True
        assert _is_cancel_command("CANCEL") is True

    def test_is_cancel_command_cancel_that(self):
        """Should recognize 'cancel that' as cancel command."""
        assert _is_cancel_command("cancel that") is True
        assert _is_cancel_command("Cancel That") is True

    def test_is_cancel_command_already_done(self):
        """Should recognize 'already done' variations."""
        assert _is_cancel_command("already done") is True
        assert _is_cancel_command("already did") is True
        assert _is_cancel_command("done already") is True
        assert _is_cancel_command("already did that") is True

    def test_is_cancel_command_nevermind(self):
        """Should recognize 'nevermind' variations."""
        assert _is_cancel_command("nevermind") is True
        assert _is_cancel_command("never mind") is True

    def test_is_cancel_command_forget(self):
        """Should recognize 'forget it' variations."""
        assert _is_cancel_command("forget it") is True
        assert _is_cancel_command("forget") is True

    def test_is_cancel_command_not_needed(self):
        """Should recognize 'not needed' and 'ignore'."""
        assert _is_cancel_command("not needed") is True
        assert _is_cancel_command("ignore") is True
        assert _is_cancel_command("ignore this") is True

    def test_is_cancel_command_normal_text(self):
        """Should NOT recognize normal clarification text as cancel."""
        assert _is_cancel_command("Send Mike the report") is False
        assert _is_cancel_command("Buy groceries") is False
        assert _is_cancel_command("done") is False  # 'done' ends session, not cancel
        assert _is_cancel_command("skip") is False

    @pytest.mark.asyncio
    async def test_cancel_dismisses_item(self):
        """Saying 'cancel that' should dismiss the current item."""
        message = AsyncMock()
        message.text = "cancel that"
        message.chat.id = 12345
        state = AsyncMock()
        state.get_data.return_value = {
            "items": [
                {
                    "id": "page-1",
                    "raw_input": "something unclear",
                    "interpretation": None,
                    "confidence": 50,
                    "source": "telegram_text",
                    "timestamp": "2026-01-11T10:30:00",
                    "voice_transcript": False,
                }
            ],
            "current_index": 0,
            "chat_id": "12345",
            "stats": {"clarified": 0, "skipped": 0, "dismissed": 0},
        }

        with patch("assistant.telegram.debrief.ClarificationService") as MockService, \
             patch("assistant.telegram.debrief._get_remaining_count") as mock_count:
            mock_service = AsyncMock()
            mock_service.dismiss_item.return_value = ClarificationResult(
                item_id="page-1",
                action="dismissed",
            )
            MockService.return_value = mock_service
            mock_count.return_value = 0

            await handle_debrief_response(message, state)

            # Should dismiss with appropriate reason
            mock_service.dismiss_item.assert_called_once()
            call_args = mock_service.dismiss_item.call_args
            assert "Cancelled by user" in call_args[1]["reason"]

            # Should show "Removed from inbox" message
            call_args = message.answer.call_args_list[0][0][0]
            assert "Removed" in call_args


class TestT083DueDateFollowUp:
    """Tests for T-083: Due date follow-up questions."""

    def test_should_ask_for_due_date_action_words(self):
        """Should ask for due date when action words are present."""
        assert _should_ask_for_due_date("Send Mike the report") is True
        assert _should_ask_for_due_date("Email the client") is True
        assert _should_ask_for_due_date("Call Sarah") is True
        assert _should_ask_for_due_date("Buy groceries") is True
        assert _should_ask_for_due_date("Schedule meeting") is True
        assert _should_ask_for_due_date("Finish the proposal") is True

    def test_should_not_ask_for_due_date_notes(self):
        """Should NOT ask for due date for notes/vague items."""
        assert _should_ask_for_due_date("Remember to check something") is False
        assert _should_ask_for_due_date("Idea for the project") is False
        assert _should_ask_for_due_date("Maybe do this later") is False
        assert _should_ask_for_due_date("Consider new approach") is False
        assert _should_ask_for_due_date("Someday learn Python") is False

    def test_should_not_ask_for_due_date_general(self):
        """Should NOT ask for general descriptions without action words."""
        assert _should_ask_for_due_date("Project planning") is False
        assert _should_ask_for_due_date("Groceries for dinner") is False
        assert _should_ask_for_due_date("Meeting notes") is False

    @pytest.mark.asyncio
    async def test_action_item_triggers_due_date_question(self):
        """Actionable clarification should trigger due date question."""
        message = AsyncMock()
        message.text = "Send the report to Mike"
        message.chat.id = 12345
        state = AsyncMock()
        state.get_data.return_value = {
            "items": [
                {
                    "id": "page-1",
                    "raw_input": "that thing",
                    "interpretation": None,
                    "confidence": 50,
                    "source": "telegram_text",
                    "timestamp": "2026-01-11T10:30:00",
                    "voice_transcript": False,
                }
            ],
            "current_index": 0,
            "chat_id": "12345",
            "stats": {"clarified": 0, "skipped": 0, "dismissed": 0},
        }

        await handle_debrief_response(message, state)

        # Should ask for due date
        call_args = message.answer.call_args[0][0]
        assert "When is it due" in call_args
        assert "tomorrow" in call_args.lower() or "friday" in call_args.lower()

        # Should transition to awaiting_due_date state
        state.set_state.assert_called_with(DebriefStates.awaiting_due_date)

        # Should store pending task
        state.update_data.assert_called()
        update_call = state.update_data.call_args_list[-1]
        assert "pending_task_title" in update_call[1]
        assert update_call[1]["pending_task_title"] == "Send the report to Mike"


class TestT083EntityHandling:
    """Tests for T-083: Entity parsing and linking."""

    def test_format_entity_summary_with_people(self):
        """Should format people entities correctly."""
        from assistant.services.entities import ExtractedEntities, ExtractedPerson

        entities = ExtractedEntities(
            people=[ExtractedPerson(name="Mike", confidence=90)],
        )
        result = _format_entity_summary(entities)
        assert "with Mike" in result
        assert "👤" in result

    def test_format_entity_summary_with_places(self):
        """Should format place entities correctly."""
        from assistant.services.entities import ExtractedEntities, ExtractedPlace

        entities = ExtractedEntities(
            places=[ExtractedPlace(name="Starbucks", confidence=85)],
        )
        result = _format_entity_summary(entities)
        assert "at Starbucks" in result
        assert "📍" in result

    def test_format_entity_summary_with_both(self):
        """Should format multiple entity types correctly."""
        from assistant.services.entities import ExtractedEntities, ExtractedPerson, ExtractedPlace

        entities = ExtractedEntities(
            people=[ExtractedPerson(name="Mike", confidence=90)],
            places=[ExtractedPlace(name="Starbucks", confidence=85)],
        )
        result = _format_entity_summary(entities)
        assert "with Mike" in result
        assert "at Starbucks" in result

    def test_format_entity_summary_empty(self):
        """Should return empty string for no entities."""
        from assistant.services.entities import ExtractedEntities

        entities = ExtractedEntities()
        result = _format_entity_summary(entities)
        assert result == ""

    def test_entities_roundtrip_serialization(self):
        """Should maintain entity data through serialization roundtrip."""
        from assistant.services.entities import (
            ExtractedEntities,
            ExtractedPerson,
            ExtractedPlace,
            ExtractedDate,
        )

        original = ExtractedEntities(
            people=[ExtractedPerson(name="Sarah", confidence=85, context="with Sarah")],
            places=[ExtractedPlace(name="Office", confidence=90, context="at Office")],
            dates=[ExtractedDate(
                datetime_value=datetime(2026, 1, 15, 14, 0),
                confidence=95,
                original_text="tomorrow",
            )],
            raw_text="Meet with Sarah at Office tomorrow",
        )

        serialized = _entities_to_dict(original)
        restored = _dict_to_entities(serialized)

        assert len(restored.people) == 1
        assert restored.people[0].name == "Sarah"
        assert restored.people[0].confidence == 85

        assert len(restored.places) == 1
        assert restored.places[0].name == "Office"

        assert len(restored.dates) == 1
        assert restored.dates[0].confidence == 95

        assert restored.raw_text == "Meet with Sarah at Office tomorrow"


class TestT083DueDateFormatting:
    """Tests for T-083: Due date formatting."""

    def test_format_due_date_today(self):
        """Should format today's date."""
        today = datetime.now()
        result = _format_due_date(today)
        assert result == "Today"

    def test_format_due_date_tomorrow(self):
        """Should format tomorrow's date."""
        from datetime import timedelta
        tomorrow = datetime.now() + timedelta(days=1)
        result = _format_due_date(tomorrow)
        assert result == "Tomorrow"

    def test_format_due_date_weekday(self):
        """Should format near-future date as weekday name."""
        from datetime import timedelta
        # 3 days from now
        future = datetime.now() + timedelta(days=3)
        result = _format_due_date(future)
        # Should be a weekday name
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        assert result in weekdays

    def test_format_due_date_distant(self):
        """Should format distant date with month and day."""
        from datetime import timedelta
        distant = datetime.now() + timedelta(days=30)
        result = _format_due_date(distant)
        # Should contain month name
        assert any(m in result for m in [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ])
