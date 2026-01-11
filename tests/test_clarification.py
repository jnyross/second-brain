"""Tests for the clarification service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from assistant.services.clarification import (
    ClarificationService,
    UnclearItem,
    ClarificationResult,
    get_unclear_items,
    get_unclear_count,
    format_debrief,
)


class TestUnclearItem:
    """Tests for UnclearItem dataclass."""

    def test_unclear_item_creation(self):
        """UnclearItem can be created with all fields."""
        item = UnclearItem(
            id="page-123",
            raw_input="some thing tomorrow",
            interpretation="Possibly a task: some thing",
            confidence=60,
            source="telegram_text",
            timestamp=datetime(2026, 1, 11, 10, 30),
            voice_transcript=False,
        )
        assert item.id == "page-123"
        assert item.raw_input == "some thing tomorrow"
        assert item.confidence == 60
        assert item.voice_transcript is False

    def test_unclear_item_voice_default(self):
        """voice_transcript defaults to False."""
        item = UnclearItem(
            id="page-123",
            raw_input="test",
            interpretation=None,
            confidence=50,
            source="telegram_text",
            timestamp=datetime.now(),
        )
        assert item.voice_transcript is False


class TestClarificationResult:
    """Tests for ClarificationResult dataclass."""

    def test_result_creation(self):
        """ClarificationResult can be created with all fields."""
        result = ClarificationResult(
            item_id="page-123",
            action="created_task",
            task_id="task-456",
            message="Created task: Buy milk",
        )
        assert result.item_id == "page-123"
        assert result.action == "created_task"
        assert result.task_id == "task-456"

    def test_result_defaults(self):
        """ClarificationResult has sensible defaults."""
        result = ClarificationResult(
            item_id="page-123",
            action="dismissed",
        )
        assert result.task_id is None
        assert result.message == ""


class TestClarificationService:
    """Tests for ClarificationService."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_notion = AsyncMock()
        self.service = ClarificationService(notion=self.mock_notion)

    # === Query Tests ===

    @pytest.mark.asyncio
    async def test_get_unclear_items_queries_notion(self):
        """get_unclear_items should query Notion for flagged items."""
        self.mock_notion.query_inbox.return_value = []

        await self.service.get_unclear_items()

        self.mock_notion.query_inbox.assert_called_once_with(
            needs_clarification=True,
            processed=False,
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_get_unclear_items_respects_limit(self):
        """get_unclear_items should pass custom limit."""
        self.mock_notion.query_inbox.return_value = []

        await self.service.get_unclear_items(limit=5)

        call_args = self.mock_notion.query_inbox.call_args
        assert call_args.kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_get_unclear_items_parses_results(self):
        """get_unclear_items should parse Notion results into UnclearItem."""
        self.mock_notion.query_inbox.return_value = [
            {
                "id": "page-123",
                "properties": {
                    "raw_input": {"rich_text": [{"text": {"content": "buy milk"}}]},
                    "interpretation": {"rich_text": [{"text": {"content": "Task: buy milk"}}]},
                    "confidence": {"number": 60},
                    "source": {"select": {"name": "telegram_text"}},
                    "timestamp": {"date": {"start": "2026-01-11T10:30:00"}},
                    "voice_file_id": {"rich_text": []},
                },
            }
        ]

        items = await self.service.get_unclear_items()

        assert len(items) == 1
        assert items[0].id == "page-123"
        assert items[0].raw_input == "buy milk"
        assert items[0].interpretation == "Task: buy milk"
        assert items[0].confidence == 60
        assert items[0].voice_transcript is False

    @pytest.mark.asyncio
    async def test_get_unclear_items_handles_voice(self):
        """get_unclear_items should detect voice transcripts."""
        self.mock_notion.query_inbox.return_value = [
            {
                "id": "page-123",
                "properties": {
                    "raw_input": {"rich_text": [{"text": {"content": "voice input"}}]},
                    "interpretation": {"rich_text": []},
                    "confidence": {"number": 50},
                    "source": {"select": {"name": "telegram_voice"}},
                    "timestamp": {"date": {"start": "2026-01-11T10:30:00"}},
                    "voice_file_id": {"rich_text": [{"text": {"content": "file_abc123"}}]},
                },
            }
        ]

        items = await self.service.get_unclear_items()

        assert items[0].voice_transcript is True

    @pytest.mark.asyncio
    async def test_get_unclear_items_handles_error(self):
        """get_unclear_items should return empty list on error."""
        self.mock_notion.query_inbox.side_effect = Exception("API error")

        items = await self.service.get_unclear_items()

        assert items == []

    @pytest.mark.asyncio
    async def test_get_unclear_count(self):
        """get_unclear_count should return count of items."""
        self.mock_notion.query_inbox.return_value = [
            {"id": "1", "properties": _make_minimal_props()},
            {"id": "2", "properties": _make_minimal_props()},
            {"id": "3", "properties": _make_minimal_props()},
        ]

        count = await self.service.get_unclear_count()

        assert count == 3

    # === Create Task Tests ===

    @pytest.mark.asyncio
    async def test_create_task_from_item(self):
        """create_task_from_item should create task and mark processed."""
        self.mock_notion.create_task.return_value = "task-456"
        self.mock_notion.mark_inbox_processed.return_value = None
        self.mock_notion.log_action.return_value = "log-789"

        result = await self.service.create_task_from_item(
            item_id="page-123",
            title="Buy milk tomorrow",
            chat_id="12345",
        )

        assert result.action == "created_task"
        assert result.task_id == "task-456"
        assert result.item_id == "page-123"

        # Should have created task
        self.mock_notion.create_task.assert_called_once()

        # Should have marked inbox item as processed
        self.mock_notion.mark_inbox_processed.assert_called_once_with(
            "page-123", "task-456"
        )

        # Should have logged the action
        self.mock_notion.log_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_task_handles_error(self):
        """create_task_from_item should handle errors gracefully."""
        self.mock_notion.create_task.side_effect = Exception("API error")

        result = await self.service.create_task_from_item(
            item_id="page-123",
            title="Test task",
        )

        assert result.action == "error"
        assert "API error" in result.message

    # === Dismiss Tests ===

    @pytest.mark.asyncio
    async def test_dismiss_item(self):
        """dismiss_item should mark item as processed."""
        self.mock_notion.mark_inbox_processed.return_value = None
        self.mock_notion.log_action.return_value = "log-789"

        result = await self.service.dismiss_item(
            item_id="page-123",
            reason="Not actionable",
        )

        assert result.action == "dismissed"
        assert result.item_id == "page-123"

        self.mock_notion.mark_inbox_processed.assert_called_once_with("page-123")
        self.mock_notion.log_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_dismiss_handles_error(self):
        """dismiss_item should handle errors gracefully."""
        self.mock_notion.mark_inbox_processed.side_effect = Exception("API error")

        result = await self.service.dismiss_item(item_id="page-123")

        assert result.action == "error"

    # === Format Tests ===

    def test_format_for_debrief_empty(self):
        """format_for_debrief should handle empty list."""
        result = self.service.format_for_debrief([])

        assert "No items need clarification" in result
        assert "all caught up" in result

    def test_format_for_debrief_single_item(self):
        """format_for_debrief should format single item."""
        items = [
            UnclearItem(
                id="page-123",
                raw_input="buy milk tomorrow",
                interpretation="Possibly a task: buy milk",
                confidence=60,
                source="telegram_text",
                timestamp=datetime(2026, 1, 11, 10, 30),
            )
        ]

        result = self.service.format_for_debrief(items)

        assert "1 item(s) need clarification" in result
        assert "buy milk tomorrow" in result
        assert "60%" in result
        assert "Possibly a task" in result

    def test_format_for_debrief_multiple_items(self):
        """format_for_debrief should format multiple items."""
        items = [
            UnclearItem(
                id="page-1",
                raw_input="first item",
                interpretation=None,
                confidence=50,
                source="telegram_text",
                timestamp=datetime(2026, 1, 11, 10, 30),
            ),
            UnclearItem(
                id="page-2",
                raw_input="second item",
                interpretation="Maybe: second",
                confidence=65,
                source="telegram_voice",
                timestamp=datetime(2026, 1, 11, 11, 0),
                voice_transcript=True,
            ),
        ]

        result = self.service.format_for_debrief(items)

        assert "2 item(s) need clarification" in result
        assert "1. \"first item\"" in result
        assert "2. \"second item\"" in result
        assert "(voice)" in result  # Voice indicator
        assert "50%" in result
        assert "65%" in result

    def test_format_for_debrief_includes_instructions(self):
        """format_for_debrief should include user instructions."""
        items = [
            UnclearItem(
                id="page-1",
                raw_input="test",
                interpretation=None,
                confidence=50,
                source="telegram_text",
                timestamp=datetime.now(),
            )
        ]

        result = self.service.format_for_debrief(items)

        assert "Reply with a number" in result
        assert "skip" in result.lower()


class TestNoNotionConfigured:
    """Tests when Notion is not configured."""

    @pytest.mark.asyncio
    async def test_get_unclear_items_no_notion(self):
        """Should return empty list when Notion not configured."""
        with patch("assistant.services.clarification.settings") as mock_settings:
            mock_settings.has_notion = False
            service = ClarificationService()
            items = await service.get_unclear_items()
            assert items == []

    @pytest.mark.asyncio
    async def test_create_task_no_notion(self):
        """Should return error result when Notion not configured."""
        with patch("assistant.services.clarification.settings") as mock_settings:
            mock_settings.has_notion = False
            service = ClarificationService()
            result = await service.create_task_from_item("page-123", "Test")
            assert result.action == "error"
            assert "not configured" in result.message

    @pytest.mark.asyncio
    async def test_dismiss_no_notion(self):
        """Should return error result when Notion not configured."""
        with patch("assistant.services.clarification.settings") as mock_settings:
            mock_settings.has_notion = False
            service = ClarificationService()
            result = await service.dismiss_item("page-123")
            assert result.action == "error"


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    @pytest.mark.asyncio
    async def test_get_unclear_items_function(self):
        """Convenience function should work."""
        with patch.object(ClarificationService, "get_unclear_items") as mock:
            mock.return_value = []
            result = await get_unclear_items()
            assert result == []

    @pytest.mark.asyncio
    async def test_get_unclear_count_function(self):
        """Convenience function should return count."""
        with patch.object(ClarificationService, "get_unclear_count") as mock:
            mock.return_value = 5
            result = await get_unclear_count()
            assert result == 5

    @pytest.mark.asyncio
    async def test_format_debrief_function(self):
        """Convenience function should return formatted debrief."""
        with patch.object(ClarificationService, "get_unclear_items") as mock_get, \
             patch.object(ClarificationService, "format_for_debrief") as mock_format:
            mock_get.return_value = []
            mock_format.return_value = "No items"
            result = await format_debrief()
            assert result == "No items"


def _make_minimal_props():
    """Create minimal Notion properties for testing."""
    return {
        "raw_input": {"rich_text": [{"text": {"content": "test"}}]},
        "interpretation": {"rich_text": []},
        "confidence": {"number": 50},
        "source": {"select": {"name": "telegram_text"}},
        "timestamp": {"date": {"start": "2026-01-11T10:00:00"}},
        "voice_file_id": {"rich_text": []},
    }
