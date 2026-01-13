"""Tests for the correction handler service."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from assistant.services.corrections import (
    CorrectionHandler,
    RecentAction,
    get_correction_handler,
    is_correction_message,
    track_created_task,
)


class TestRecentAction:
    """Tests for RecentAction dataclass."""

    def test_creation(self):
        """Test creating a RecentAction."""
        action = RecentAction(
            action_type="task_created",
            entity_id="page-123",
            title="Call Jess",
            chat_id="chat-1",
            message_id="msg-1",
        )

        assert action.action_type == "task_created"
        assert action.entity_id == "page-123"
        assert action.title == "Call Jess"
        assert action.chat_id == "chat-1"
        assert action.message_id == "msg-1"
        assert isinstance(action.timestamp, datetime)

    def test_is_expired_false_for_recent(self):
        """Recent actions should not be expired."""
        action = RecentAction(
            action_type="task_created",
            entity_id="page-123",
            title="Call Jess",
        )
        assert not action.is_expired(max_age_minutes=30)

    def test_is_expired_true_for_old(self):
        """Old actions should be expired."""
        action = RecentAction(
            action_type="task_created",
            entity_id="page-123",
            title="Call Jess",
            timestamp=datetime.now(UTC) - timedelta(minutes=35),
        )
        assert action.is_expired(max_age_minutes=30)


class TestCorrectionPatternDetection:
    """Tests for correction pattern detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "Wrong",
            "wrong!",
            "Wrong, I said Tess",
            "That's wrong",
            "thats wrong",
            "That's not right",
            "That's not correct",
            "No, I said Tess",
            "no that's wrong",
            "Incorrect",
            "Actually, it's Tess",
            "actually Tess not Jess",
            "Not that",
            "I said Tess not Jess",
            "I meant Tess",
            "Should be Tess not Jess",
            "It's Tess not Jess",
            "undo",
            "Undo that",
            "Cancel that",
            "delete that",
        ],
    )
    def test_is_correction_true(self, text):
        """Test that correction patterns are detected."""
        handler = CorrectionHandler()
        assert handler.is_correction(text), f"Should detect '{text}' as correction"

    @pytest.mark.parametrize(
        "text",
        [
            "Buy milk tomorrow",
            "Call Sarah at 3pm",
            "Meeting with Mike",
            "Reminder to exercise",
            "Schedule a haircut",
            "I need to finish the report",
            "What's on my calendar?",
            "Show me today's tasks",
        ],
    )
    def test_is_correction_false(self, text):
        """Test that normal messages are not detected as corrections."""
        handler = CorrectionHandler()
        assert not handler.is_correction(text), f"Should not detect '{text}' as correction"


class TestCorrectionExtraction:
    """Tests for extracting correction values."""

    @pytest.mark.parametrize(
        "text,expected_correct,expected_wrong",
        [
            ("I said Tess not Jess", "Tess", "Jess"),
            ("I said 'Tess' not 'Jess'", "Tess", "Jess"),
            ('I said "Tess" not "Jess"', "Tess", "Jess"),
            ("i meant Tess not Jess", "Tess", "Jess"),
            ("should be Tess not Jess", "Tess", "Jess"),
            ("should have been Tess not Jess", "Tess", "Jess"),
            ("it's Tess not Jess", "Tess", "Jess"),
            ("that was Tess not Jess", "Tess", "Jess"),
            ("that's Tess not Jess", "Tess", "Jess"),
            ("change Jess to Tess", "Tess", "Jess"),
            ("Wrong, I said Tess", "Tess", None),
            ("Wrong, it's Tess", "Tess", None),
            ("Wrong, that was Tess", "Tess", None),
        ],
    )
    def test_extract_correction(self, text, expected_correct, expected_wrong):
        """Test extracting correct and wrong values from correction text."""
        handler = CorrectionHandler()
        correct, wrong = handler.extract_correction(text)
        assert correct == expected_correct, (
            f"Expected correct='{expected_correct}', got '{correct}'"
        )
        if expected_wrong is not None:
            assert wrong == expected_wrong, f"Expected wrong='{expected_wrong}', got '{wrong}'"

    def test_extract_correction_no_match(self):
        """Test extraction when no pattern matches."""
        handler = CorrectionHandler()
        correct, wrong = handler.extract_correction("Wrong")
        assert correct is None
        assert wrong is None


class TestCorrectionHandlerTrackAction:
    """Tests for tracking actions."""

    def test_track_action(self):
        """Test tracking a new action."""
        handler = CorrectionHandler()
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-123",
            title="Call Jess",
        )

        action = handler.get_last_action("chat-1")
        assert action is not None
        assert action.title == "Call Jess"
        assert action.entity_id == "page-123"

    def test_track_multiple_actions(self):
        """Test tracking multiple actions returns the latest."""
        handler = CorrectionHandler()
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-1",
            title="First task",
        )
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-2",
            action_type="task_created",
            entity_id="page-2",
            title="Second task",
        )

        action = handler.get_last_action("chat-1")
        assert action is not None
        assert action.title == "Second task"

    def test_track_actions_per_chat(self):
        """Test that actions are tracked per chat."""
        handler = CorrectionHandler()
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-1",
            title="Chat 1 task",
        )
        handler.track_action(
            chat_id="chat-2",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-2",
            title="Chat 2 task",
        )

        action1 = handler.get_last_action("chat-1")
        action2 = handler.get_last_action("chat-2")

        assert action1.title == "Chat 1 task"
        assert action2.title == "Chat 2 task"

    def test_get_last_action_no_actions(self):
        """Test getting last action when none exist."""
        handler = CorrectionHandler()
        action = handler.get_last_action("chat-1")
        assert action is None


class TestCorrectionHandlerProcessCorrection:
    """Tests for processing corrections."""

    @pytest.fixture
    def mock_notion(self):
        """Create a mock NotionClient."""
        notion = AsyncMock()
        notion.soft_delete = AsyncMock()
        notion.log_action = AsyncMock()
        notion.create_log_entry = AsyncMock()
        notion._request = AsyncMock()
        return notion

    @pytest.fixture
    def handler(self, mock_notion):
        """Create a handler with mock NotionClient."""
        return CorrectionHandler(notion_client=mock_notion)

    @pytest.mark.asyncio
    async def test_not_a_correction(self, handler):
        """Test processing a non-correction message."""
        result = await handler.process_correction(
            text="Buy milk tomorrow",
            chat_id="chat-1",
            message_id="msg-1",
        )
        assert not result.is_correction

    @pytest.mark.asyncio
    async def test_correction_no_recent_action(self, handler):
        """Test correction when there's no recent action to correct."""
        result = await handler.process_correction(
            text="Wrong, I said Tess",
            chat_id="chat-1",
            message_id="msg-1",
        )
        assert result.is_correction
        assert not result.success
        assert "don't have a recent action" in result.message

    @pytest.mark.asyncio
    async def test_correction_with_extraction(self, handler, mock_notion):
        """Test successful correction with value extraction."""
        # Track an action first
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-123",
            title="Call Jess",
        )

        # Apply correction
        result = await handler.process_correction(
            text="Wrong, I said Tess not Jess",
            chat_id="chat-1",
            message_id="msg-2",
        )

        assert result.is_correction
        assert result.success
        assert result.original_value == "Call Jess"
        assert result.corrected_value == "Tess"
        assert "Fixed" in result.message

        # Verify Notion was called to update
        mock_notion._request.assert_called()

    @pytest.mark.asyncio
    async def test_undo_request(self, handler, mock_notion):
        """Test undo/delete request."""
        # Track an action first
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-123",
            title="Call Jess",
        )

        # Undo the action
        result = await handler.process_correction(
            text="Undo that",
            chat_id="chat-1",
            message_id="msg-2",
        )

        assert result.is_correction
        assert result.success
        assert result.correction_type == "undo"
        assert "Removed" in result.message

        # Verify soft delete was called
        mock_notion.soft_delete.assert_called_once_with("page-123")

    @pytest.mark.asyncio
    async def test_cancel_that_request(self, handler, mock_notion):
        """Test 'cancel that' request."""
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-123",
            title="Call Jess",
        )

        result = await handler.process_correction(
            text="Cancel that",
            chat_id="chat-1",
            message_id="msg-2",
        )

        assert result.is_correction
        assert result.success
        assert result.correction_type == "undo"

    @pytest.mark.asyncio
    async def test_delete_that_request(self, handler, mock_notion):
        """Test 'delete that' request."""
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-123",
            title="Buy groceries",
        )

        result = await handler.process_correction(
            text="delete that",
            chat_id="chat-1",
            message_id="msg-2",
        )

        assert result.is_correction
        assert result.success
        assert result.correction_type == "undo"

    @pytest.mark.asyncio
    async def test_correction_without_value_asks_clarification(self, handler):
        """Test correction without extractable value asks for clarification."""
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-123",
            title="Call Jess",
        )

        result = await handler.process_correction(
            text="Wrong",
            chat_id="chat-1",
            message_id="msg-2",
        )

        assert result.is_correction
        assert not result.success
        assert "what should it be instead" in result.message

    @pytest.mark.asyncio
    async def test_correction_updates_tracked_action(self, handler, mock_notion):
        """Test that correction updates the tracked action's title."""
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="task_created",
            entity_id="page-123",
            title="Call Jess",
        )

        await handler.process_correction(
            text="I said Tess not Jess",
            chat_id="chat-1",
            message_id="msg-2",
        )

        # The tracked action should now have the updated title
        action = handler.get_last_action("chat-1")
        assert action.title == "Tess"


class TestCorrectionHandlerEntityTypes:
    """Tests for correcting different entity types."""

    @pytest.fixture
    def mock_notion(self):
        """Create a mock NotionClient."""
        notion = AsyncMock()
        notion._request = AsyncMock()
        notion.log_action = AsyncMock()
        notion.create_log_entry = AsyncMock()
        return notion

    @pytest.fixture
    def handler(self, mock_notion):
        """Create a handler with mock NotionClient."""
        return CorrectionHandler(notion_client=mock_notion)

    @pytest.mark.asyncio
    async def test_correct_person_name(self, handler, mock_notion):
        """Test correcting a person's name."""
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="person_created",
            entity_id="person-123",
            title="Jess",
        )

        result = await handler.process_correction(
            text="I said Tess not Jess",
            chat_id="chat-1",
            message_id="msg-2",
        )

        assert result.success
        # Verify the correct update method was called
        mock_notion._request.assert_called()
        call_args = mock_notion._request.call_args
        assert "name" in str(call_args)

    @pytest.mark.asyncio
    async def test_correct_place_name(self, handler, mock_notion):
        """Test correcting a place's name."""
        handler.track_action(
            chat_id="chat-1",
            message_id="msg-1",
            action_type="place_created",
            entity_id="place-123",
            title="Starbucks",
        )

        result = await handler.process_correction(
            text="I said Blue Bottle not Starbucks",
            chat_id="chat-1",
            message_id="msg-2",
        )

        assert result.success
        assert result.corrected_value == "Blue Bottle"


class TestAT108AcceptanceTest:
    """Test AT-108: Correction Handling acceptance criteria.

    Given: AI created task "Call Jess"
    When: User replies "Wrong, I said Tess"
    Then: Task updated to "Call Tess"
    And: Correction logged in Log database
    Pass condition: Task.title = "Call Tess" AND Log entry with correction field populated
    """

    @pytest.fixture
    def mock_notion(self):
        """Create a mock NotionClient for the test."""
        notion = AsyncMock()
        notion._request = AsyncMock(return_value={"id": "updated-page"})
        notion.log_action = AsyncMock(return_value="log-entry-1")
        notion.create_log_entry = AsyncMock(return_value="log-entry-2")
        return notion

    @pytest.fixture
    def handler(self, mock_notion):
        """Create handler with mock."""
        return CorrectionHandler(notion_client=mock_notion)

    @pytest.mark.asyncio
    async def test_at108_correction_handling(self, handler, mock_notion):
        """Test the full AT-108 acceptance criteria."""
        # Step 1: AI created task "Call Jess" (track it)
        handler.track_action(
            chat_id="user-chat",
            message_id="original-msg",
            action_type="task_created",
            entity_id="task-page-id",
            title="Call Jess",
        )

        # Step 2: User replies "Wrong, I said Tess"
        result = await handler.process_correction(
            text="Wrong, I said Tess",
            chat_id="user-chat",
            message_id="correction-msg",
        )

        # Verify: Task updated (title changed)
        assert result.is_correction, "Should detect as correction"
        assert result.success, "Correction should succeed"
        assert result.corrected_value == "Tess", "Corrected value should be 'Tess'"
        assert result.original_value == "Call Jess", "Original should be 'Call Jess'"

        # Verify: Notion API was called to update the task title
        patch_calls = [
            call for call in mock_notion._request.call_args_list if call[0][0] == "PATCH"
        ]
        assert len(patch_calls) >= 1, "Should have made at least one PATCH request"

        # Verify: Correction was logged
        mock_notion.create_log_entry.assert_called()
        log_call = mock_notion.create_log_entry.call_args
        log_entry = log_call[0][0]
        assert log_entry.correction is not None, "Log entry should have correction field"
        assert "Jess" in log_entry.correction and "Tess" in log_entry.correction

        # Verify response message
        assert "Fixed" in result.message or "Changed" in result.message


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_is_correction_message(self):
        """Test the module-level is_correction_message function."""
        assert is_correction_message("Wrong, I said Tess")
        assert not is_correction_message("Buy milk")

    def test_get_correction_handler_singleton(self):
        """Test that get_correction_handler returns a handler."""
        handler = get_correction_handler()
        assert handler is not None
        assert isinstance(handler, CorrectionHandler)

    def test_track_created_task(self):
        """Test the module-level track_created_task function."""
        # Reset the global handler first
        import assistant.services.corrections as corrections_module

        corrections_module._handler = None

        track_created_task(
            chat_id="test-chat",
            message_id="test-msg",
            task_id="task-123",
            title="Test Task",
        )

        handler = get_correction_handler()
        action = handler.get_last_action("test-chat")
        assert action is not None
        assert action.title == "Test Task"

        # Cleanup
        corrections_module._handler = None


class TestHandlersIntegration:
    """Tests for handlers.py integration."""

    def test_extract_task_title_from_response(self):
        """Test extracting task title from processor response."""
        from assistant.telegram.handlers import _extract_task_title

        # Standard response
        assert _extract_task_title("Got it. Call Jess.") == "Call Jess"

        # Response with date
        assert _extract_task_title("Got it. Call Jess, Friday at 3:00 PM.") == "Call Jess"

        # Response with people
        assert _extract_task_title("Got it. Meeting, Friday at 2:00 PM with Sarah.") == "Meeting"

        # Response with place
        assert _extract_task_title("Got it. Dinner at Starbucks.") == "Dinner at Starbucks"

    def test_is_correction_message_import(self):
        """Test that is_correction_message is importable from handlers."""
        from assistant.telegram.handlers import is_correction_message

        assert callable(is_correction_message)
