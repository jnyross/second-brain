"""Tests for audit logging service.

Tests AT-111 (every action logged) and AT-113 (idempotency).
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.notion.schemas import ActionType
from assistant.services.audit import (
    UNDO_WINDOW_MINUTES,
    AuditLogger,
    DedupeResult,
    check_and_log_idempotency,
    get_audit_logger,
)


@pytest.fixture
def mock_notion():
    """Create a mock Notion client."""
    notion = MagicMock()
    notion.create_log_entry = AsyncMock(return_value="log-123")
    notion._check_dedupe = AsyncMock(return_value=None)
    notion._request = AsyncMock(return_value={"results": []})
    return notion


@pytest.fixture
def audit_logger(mock_notion):
    """Create an audit logger with mock Notion client."""
    return AuditLogger(notion_client=mock_notion)


class TestIdempotencyKeyGeneration:
    """Test idempotency key generation."""

    def test_telegram_key(self, audit_logger):
        """Test Telegram message idempotency key."""
        key = audit_logger.generate_idempotency_key("telegram", "12345", "67890")
        assert key == "telegram:12345:67890"

    def test_calendar_key(self, audit_logger):
        """Test calendar event idempotency key."""
        key = audit_logger.generate_idempotency_key("calendar", "task-abc", "2026-01-12")
        assert key == "calendar:task-abc:2026-01-12"

    def test_email_key(self, audit_logger):
        """Test email idempotency key."""
        key = audit_logger.generate_idempotency_key("email", "thread-xyz", "hash123")
        assert key == "email:thread-xyz:hash123"

    def test_briefing_key(self, audit_logger):
        """Test briefing idempotency key."""
        key = audit_logger.generate_idempotency_key("briefing", "2026-01-12", "chat-456")
        assert key == "briefing:2026-01-12:chat-456"


class TestIdempotencyCheck:
    """Test AT-113: Idempotency checking."""

    @pytest.mark.asyncio
    async def test_new_key_returns_new(self, audit_logger, mock_notion):
        """New idempotency key returns NEW result."""
        mock_notion._check_dedupe.return_value = None

        result, entry = await audit_logger.check_idempotency("telegram:123:456")

        assert result == DedupeResult.NEW
        assert entry is None
        mock_notion._check_dedupe.assert_called_once_with("log", "telegram:123:456")

    @pytest.mark.asyncio
    async def test_existing_key_returns_duplicate(self, audit_logger, mock_notion):
        """Existing idempotency key returns DUPLICATE result."""
        mock_notion._check_dedupe.return_value = "existing-log-id"

        result, entry = await audit_logger.check_idempotency("telegram:123:456")

        assert result == DedupeResult.DUPLICATE
        assert entry is not None
        assert entry.log_id == "existing-log-id"

    @pytest.mark.asyncio
    async def test_cached_key_returns_duplicate(self, audit_logger, mock_notion):
        """Cached key returns DUPLICATE without Notion call."""
        # First call populates cache
        mock_notion._check_dedupe.return_value = "existing-log-id"
        await audit_logger.check_idempotency("telegram:123:456")

        # Second call should use cache
        mock_notion._check_dedupe.reset_mock()
        result, entry = await audit_logger.check_idempotency("telegram:123:456")

        assert result == DedupeResult.DUPLICATE
        mock_notion._check_dedupe.assert_not_called()


class TestLogAction:
    """Test AT-111: Every action logged."""

    @pytest.mark.asyncio
    async def test_log_action_creates_entry(self, audit_logger, mock_notion):
        """Log action creates entry in Notion."""
        entry = await audit_logger.log_action(
            action_type=ActionType.CREATE,
            idempotency_key="telegram:123:456",
            input_text="Buy milk tomorrow",
            action_taken="Created task: Buy milk",
            confidence=95,
            entities_affected=["task-123"],
        )

        assert entry.log_id == "log-123"
        assert entry.action_type == ActionType.CREATE
        assert entry.input_text == "Buy milk tomorrow"
        mock_notion.create_log_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_action_includes_timestamp(self, audit_logger, mock_notion):
        """Log action includes timestamp."""
        before = datetime.utcnow()
        entry = await audit_logger.log_action(
            action_type=ActionType.CAPTURE,
            action_taken="Test action",
        )
        after = datetime.utcnow()

        assert before <= entry.timestamp <= after

    @pytest.mark.asyncio
    async def test_log_action_with_undo_window(self, audit_logger, mock_notion):
        """Log action with undo window sets expiry."""
        entry = await audit_logger.log_action(
            action_type=ActionType.CREATE,
            action_taken="Created task",
            include_undo_window=True,
        )

        assert entry.undo_available_until is not None
        expected_expiry = entry.timestamp + timedelta(minutes=UNDO_WINDOW_MINUTES)
        # Allow 1 second tolerance
        assert abs((entry.undo_available_until - expected_expiry).total_seconds()) < 1

    @pytest.mark.asyncio
    async def test_log_action_with_correction(self, audit_logger, mock_notion):
        """Log action with correction sets corrected_at."""
        entry = await audit_logger.log_action(
            action_type=ActionType.UPDATE,
            action_taken="Updated task",
            correction="Jess → Tess",
        )

        assert entry.correction == "Jess → Tess"
        assert entry.corrected_at is not None

    @pytest.mark.asyncio
    async def test_log_action_without_notion(self):
        """Log action works without Notion client (local mode)."""
        logger = AuditLogger(notion_client=None)

        # Patch has_notion to be False
        with patch("assistant.services.audit.settings") as mock_settings:
            mock_settings.has_notion = False

            entry = await logger.log_action(
                action_type=ActionType.CAPTURE,
                action_taken="Test action",
            )

        assert entry.action_type == ActionType.CAPTURE
        assert entry.log_id is None


class TestLogDeduplicated:
    """Test AT-113: Logging deduplicated actions."""

    @pytest.mark.asyncio
    async def test_log_deduplicated(self, audit_logger, mock_notion):
        """Log deduplicated creates entry with dedupe prefix."""
        await audit_logger.log_deduplicated(
            idempotency_key="telegram:123:456",
            original_log_id="original-log-id",
        )

        # Check the log entry was created
        mock_notion.create_log_entry.assert_called()
        call_args = mock_notion.create_log_entry.call_args[0][0]

        assert call_args.idempotency_key == "dedupe:telegram:123:456"
        assert "Deduplicated" in call_args.action_taken
        assert "original-log-id" in call_args.entities_affected


class TestConvenienceMethods:
    """Test convenience logging methods."""

    @pytest.mark.asyncio
    async def test_log_capture(self, audit_logger, mock_notion):
        """Log capture creates correct entry."""
        await audit_logger.log_capture(
            idempotency_key="telegram:123:456",
            input_text="Buy milk",
            confidence=45,
            inbox_id="inbox-123",
            needs_clarification=True,
        )

        call_args = mock_notion.create_log_entry.call_args[0][0]
        assert call_args.action_type == ActionType.CAPTURE
        assert "needs clarification" in call_args.action_taken
        assert "inbox-123" in call_args.entities_affected

    @pytest.mark.asyncio
    async def test_log_create_task(self, audit_logger, mock_notion):
        """Log create task creates correct entry."""
        await audit_logger.log_create(
            idempotency_key="telegram:123:456",
            input_text="Buy milk tomorrow",
            entity_type="task",
            entity_id="task-123",
            title="Buy milk",
            confidence=95,
        )

        call_args = mock_notion.create_log_entry.call_args[0][0]
        assert call_args.action_type == ActionType.CREATE
        assert "Created task: Buy milk" in call_args.action_taken

    @pytest.mark.asyncio
    async def test_log_create_calendar_event(self, audit_logger, mock_notion):
        """Log create calendar event uses CALENDAR_CREATE action type."""
        await audit_logger.log_create(
            idempotency_key="calendar:task-123:2026-01-12",
            input_text="Meeting at 2pm",
            entity_type="calendar_event",
            entity_id="task-123",
            title="Meeting",
            confidence=90,
            external_api="google",
            external_resource_id="event-456",
        )

        call_args = mock_notion.create_log_entry.call_args[0][0]
        assert call_args.action_type == ActionType.CALENDAR_CREATE
        assert call_args.external_api == "google"
        assert call_args.external_resource_id == "event-456"

    @pytest.mark.asyncio
    async def test_log_update(self, audit_logger, mock_notion):
        """Log update creates correct entry."""
        await audit_logger.log_update(
            entity_id="task-123",
            entity_type="task",
            field_name="title",
            old_value="Call Jess",
            new_value="Call Tess",
            reason="user correction",
        )

        call_args = mock_notion.create_log_entry.call_args[0][0]
        assert call_args.action_type == ActionType.UPDATE
        assert "Call Jess → Call Tess" in call_args.action_taken
        assert call_args.correction == "Call Jess → Call Tess"

    @pytest.mark.asyncio
    async def test_log_delete_soft(self, audit_logger, mock_notion):
        """Log soft delete creates correct entry with undo window."""
        await audit_logger.log_delete(
            entity_id="task-123",
            entity_type="task",
            title="Buy milk",
            soft=True,
        )

        call_args = mock_notion.create_log_entry.call_args[0][0]
        assert call_args.action_type == ActionType.DELETE
        assert "Soft deleted" in call_args.action_taken
        assert call_args.undo_available_until is not None

    @pytest.mark.asyncio
    async def test_log_delete_hard(self, audit_logger, mock_notion):
        """Log hard delete creates correct entry without undo window."""
        await audit_logger.log_delete(
            entity_id="task-123",
            entity_type="task",
            title="Buy milk",
            soft=False,
        )

        call_args = mock_notion.create_log_entry.call_args[0][0]
        assert "Hard deleted" in call_args.action_taken

    @pytest.mark.asyncio
    async def test_log_calendar_create(self, audit_logger, mock_notion):
        """Log calendar create generates correct idempotency key."""
        start_time = datetime(2026, 1, 15, 14, 0)

        await audit_logger.log_calendar_create(
            task_id="task-123",
            event_id="event-456",
            title="Team Meeting",
            start_time=start_time,
        )

        call_args = mock_notion.create_log_entry.call_args[0][0]
        assert call_args.idempotency_key == "calendar:task-123:2026-01-15"
        assert call_args.external_resource_id == "event-456"

    @pytest.mark.asyncio
    async def test_log_briefing(self, audit_logger, mock_notion):
        """Log briefing generates correct idempotency key."""
        await audit_logger.log_briefing(
            chat_id="123456",
            date="2026-01-12",
            sections_included=["calendar", "tasks", "inbox"],
        )

        call_args = mock_notion.create_log_entry.call_args[0][0]
        assert call_args.idempotency_key == "briefing:2026-01-12:123456"
        assert call_args.action_type == ActionType.SEND
        assert "calendar, tasks, inbox" in call_args.action_taken

    @pytest.mark.asyncio
    async def test_log_error(self, audit_logger, mock_notion):
        """Log error creates correct entry."""
        await audit_logger.log_error(
            error_code="NOTION_503",
            error_message="Service unavailable",
            action_attempted="Create task",
            idempotency_key="telegram:123:456",
            retry_count=3,
        )

        call_args = mock_notion.create_log_entry.call_args[0][0]
        assert call_args.action_type == ActionType.ERROR
        assert call_args.error_code == "NOTION_503"
        assert call_args.retry_count == 3


class TestModuleLevelFunctions:
    """Test module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_get_audit_logger_singleton(self):
        """get_audit_logger returns singleton."""
        # Reset singleton for test
        import assistant.services.audit as audit_module

        audit_module._audit_logger = None

        logger1 = get_audit_logger()
        logger2 = get_audit_logger()

        assert logger1 is logger2

        # Cleanup
        audit_module._audit_logger = None

    @pytest.mark.asyncio
    async def test_check_and_log_idempotency_new(self, mock_notion):
        """check_and_log_idempotency returns True for new key."""
        import assistant.services.audit as audit_module

        audit_module._audit_logger = AuditLogger(notion_client=mock_notion)
        mock_notion._check_dedupe.return_value = None

        should_proceed, entry = await check_and_log_idempotency("telegram:new:key")

        assert should_proceed is True
        assert entry is None

        # Cleanup
        audit_module._audit_logger = None

    @pytest.mark.asyncio
    async def test_check_and_log_idempotency_duplicate(self, mock_notion):
        """check_and_log_idempotency returns False and logs for duplicate."""
        import assistant.services.audit as audit_module

        audit_module._audit_logger = AuditLogger(notion_client=mock_notion)
        mock_notion._check_dedupe.return_value = "existing-log-id"

        should_proceed, entry = await check_and_log_idempotency("telegram:dup:key")

        assert should_proceed is False
        assert entry is not None

        # Verify dedupe was logged
        assert mock_notion.create_log_entry.call_count >= 1

        # Cleanup
        audit_module._audit_logger = None


class TestQueryLog:
    """Test log querying."""

    @pytest.mark.asyncio
    async def test_query_log_by_action_type(self, audit_logger, mock_notion):
        """Query log by action type."""
        mock_notion._request.return_value = {"results": [{"id": "log-1"}, {"id": "log-2"}]}

        results = await audit_logger.query_log(action_type=ActionType.CREATE)

        assert len(results) == 2
        call_args = mock_notion._request.call_args
        assert "action_type" in str(call_args)

    @pytest.mark.asyncio
    async def test_query_log_by_since(self, audit_logger, mock_notion):
        """Query log by timestamp."""
        since = datetime(2026, 1, 10)

        await audit_logger.query_log(since=since)

        call_args = mock_notion._request.call_args
        assert "2026-01-10" in str(call_args)

    @pytest.mark.asyncio
    async def test_query_log_by_entity(self, audit_logger, mock_notion):
        """Query log by entity ID."""
        await audit_logger.query_log(entity_id="task-123")

        call_args = mock_notion._request.call_args
        assert "task-123" in str(call_args)


class TestAT111EveryActionLogged:
    """Integration tests for AT-111: Every action logged."""

    @pytest.mark.asyncio
    async def test_all_action_types_loggable(self, audit_logger, mock_notion):
        """All action types can be logged."""
        for action_type in ActionType:
            entry = await audit_logger.log_action(
                action_type=action_type,
                action_taken=f"Test {action_type.value}",
            )
            assert entry.action_type == action_type


class TestAT113Idempotency:
    """Integration tests for AT-113: Idempotency."""

    @pytest.mark.asyncio
    async def test_duplicate_message_logged_as_deduplicated(self, mock_notion):
        """AT-113: Second attempt logged as 'deduplicated'."""
        import assistant.services.audit as audit_module

        audit_module._audit_logger = AuditLogger(notion_client=mock_notion)

        # Simulate existing entry
        mock_notion._check_dedupe.return_value = "original-log-id"

        should_proceed, entry = await check_and_log_idempotency("telegram:123:456")

        assert should_proceed is False

        # Verify dedupe log was created
        assert mock_notion.create_log_entry.called
        log_entry = mock_notion.create_log_entry.call_args[0][0]
        assert "dedupe:" in log_entry.idempotency_key
        assert "Deduplicated" in log_entry.action_taken

        # Cleanup
        audit_module._audit_logger = None
