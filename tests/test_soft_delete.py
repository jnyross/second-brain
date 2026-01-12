"""Tests for soft delete service (T-115).

Verifies AT-118:
- Given: Task "Buy groceries" exists
- When: User says "delete that"
- Then: Task.deleted_at set to current timestamp
- And: Task hidden from /today and briefings
- When: User says "undo" within 30 days
- Then: Task.deleted_at cleared, task visible again

Tests cover:
1. Soft delete sets deleted_at and hides from queries
2. Undo restores deleted_at to null
3. Deleted items tracked per-chat
4. Undo window (30 days) enforced
5. is_delete_command and is_undo_command pattern matching
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.services.soft_delete import (
    DeletedAction,
    DeleteResult,
    SoftDeleteService,
    UndoResult,
    is_delete_command,
    is_undo_command,
    soft_delete,
    undo_last_delete,
)


class TestDeletedAction:
    """Tests for DeletedAction dataclass."""

    def test_is_within_undo_window_fresh(self):
        """Fresh deletion should be within undo window."""
        action = DeletedAction(
            entity_type="task",
            entity_id="test-id",
            title="Test Task",
            deleted_at=datetime.utcnow(),
        )
        assert action.is_within_undo_window() is True

    def test_is_within_undo_window_old(self):
        """Old deletion should be outside undo window."""
        action = DeletedAction(
            entity_type="task",
            entity_id="test-id",
            title="Test Task",
            deleted_at=datetime.utcnow() - timedelta(days=31),
        )
        assert action.is_within_undo_window() is False

    def test_is_within_undo_window_at_boundary(self):
        """Deletion at exactly 30 days should be outside window."""
        action = DeletedAction(
            entity_type="task",
            entity_id="test-id",
            title="Test Task",
            deleted_at=datetime.utcnow() - timedelta(days=30, seconds=1),
        )
        assert action.is_within_undo_window() is False

    def test_is_within_undo_window_custom_days(self):
        """Custom undo window should be respected."""
        action = DeletedAction(
            entity_type="task",
            entity_id="test-id",
            title="Test Task",
            deleted_at=datetime.utcnow() - timedelta(days=5),
        )
        # 7 days window - action at 5 days should be within
        assert action.is_within_undo_window(days=7) is True
        # 3 days window - action at 5 days should be outside
        assert action.is_within_undo_window(days=3) is False


class TestSoftDeleteService:
    """Tests for SoftDeleteService."""

    @pytest.fixture
    def mock_notion(self):
        """Create a mock NotionClient."""
        mock = MagicMock()
        mock.soft_delete = AsyncMock()
        mock.undo_delete = AsyncMock()
        mock.log_action = AsyncMock(return_value="log-entry-id")
        return mock

    @pytest.fixture
    def service(self, mock_notion):
        """Create SoftDeleteService with mock NotionClient."""
        return SoftDeleteService(notion_client=mock_notion)

    @pytest.mark.asyncio
    async def test_soft_delete_success(self, service, mock_notion):
        """Soft delete should call Notion API and track for undo."""
        result = await service.soft_delete(
            entity_type="task",
            entity_id="task-123",
            title="Buy groceries",
            chat_id="chat-1",
            message_id="msg-1",
        )

        # Should succeed
        assert result.success is True
        assert result.entity_id == "task-123"
        assert result.entity_type == "task"
        assert result.title == "Buy groceries"
        assert result.can_undo is True
        assert "undo" in result.message.lower()

        # Should call Notion soft_delete
        mock_notion.soft_delete.assert_called_once_with("task-123")

        # Should log the action
        mock_notion.log_action.assert_called_once()

        # Should track for undo
        deleted = service._get_last_deleted("chat-1")
        assert deleted is not None
        assert deleted.entity_id == "task-123"
        assert deleted.title == "Buy groceries"

    @pytest.mark.asyncio
    async def test_soft_delete_failure(self, service, mock_notion):
        """Soft delete should handle Notion API errors gracefully."""
        mock_notion.soft_delete.side_effect = Exception("API error")

        result = await service.soft_delete(
            entity_type="task",
            entity_id="task-123",
            title="Buy groceries",
            chat_id="chat-1",
            message_id="msg-1",
        )

        assert result.success is False
        assert "couldn't delete" in result.message.lower()

    @pytest.mark.asyncio
    async def test_undo_last_delete_success(self, service, mock_notion):
        """Undo should restore the last deleted item."""
        # First delete an item
        await service.soft_delete(
            entity_type="task",
            entity_id="task-123",
            title="Buy groceries",
            chat_id="chat-1",
            message_id="msg-1",
        )

        # Reset mocks
        mock_notion.reset_mock()

        # Now undo
        result = await service.undo_last_delete("chat-1")

        assert result.success is True
        assert result.entity_id == "task-123"
        assert result.title == "Buy groceries"
        assert "restored" in result.message.lower()

        # Should call Notion undo_delete
        mock_notion.undo_delete.assert_called_once_with("task-123")

        # Should remove from tracking
        assert service._get_last_deleted("chat-1") is None

    @pytest.mark.asyncio
    async def test_undo_no_deletes(self, service):
        """Undo with no deleted items should fail gracefully."""
        result = await service.undo_last_delete("chat-1")

        assert result.success is False
        assert "nothing to undo" in result.message.lower()

    @pytest.mark.asyncio
    async def test_undo_outside_window(self, service, mock_notion):
        """Undo outside 30-day window should fail."""
        # Manually add an old deletion
        old_deletion = DeletedAction(
            entity_type="task",
            entity_id="task-old",
            title="Old task",
            deleted_at=datetime.utcnow() - timedelta(days=31),
            chat_id="chat-1",
        )
        service._deleted_items["chat-1"].append(old_deletion)

        result = await service.undo_last_delete("chat-1")

        assert result.success is False
        assert "30 days" in result.message

        # Should NOT call Notion
        mock_notion.undo_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_deletes_undo_order(self, service, mock_notion):
        """Undo should restore items in LIFO order."""
        # Delete three items
        await service.soft_delete(
            entity_type="task",
            entity_id="task-1",
            title="First task",
            chat_id="chat-1",
            message_id="msg-1",
        )
        await service.soft_delete(
            entity_type="task",
            entity_id="task-2",
            title="Second task",
            chat_id="chat-1",
            message_id="msg-2",
        )
        await service.soft_delete(
            entity_type="task",
            entity_id="task-3",
            title="Third task",
            chat_id="chat-1",
            message_id="msg-3",
        )

        # Undo should restore in reverse order
        result1 = await service.undo_last_delete("chat-1")
        assert result1.title == "Third task"

        result2 = await service.undo_last_delete("chat-1")
        assert result2.title == "Second task"

        result3 = await service.undo_last_delete("chat-1")
        assert result3.title == "First task"

        # No more to undo
        result4 = await service.undo_last_delete("chat-1")
        assert result4.success is False

    @pytest.mark.asyncio
    async def test_per_chat_isolation(self, service, mock_notion):
        """Deletes should be tracked separately per chat."""
        # Delete in chat-1
        await service.soft_delete(
            entity_type="task",
            entity_id="task-1",
            title="Chat 1 task",
            chat_id="chat-1",
            message_id="msg-1",
        )

        # Delete in chat-2
        await service.soft_delete(
            entity_type="task",
            entity_id="task-2",
            title="Chat 2 task",
            chat_id="chat-2",
            message_id="msg-2",
        )

        # Undo in chat-1 should restore chat-1's task
        result = await service.undo_last_delete("chat-1")
        assert result.title == "Chat 1 task"

        # Chat-2's task should still be pending
        result = await service.undo_last_delete("chat-2")
        assert result.title == "Chat 2 task"

    @pytest.mark.asyncio
    async def test_restore_by_id(self, service, mock_notion):
        """restore_by_id should restore a specific entity."""
        # Delete an item
        await service.soft_delete(
            entity_type="task",
            entity_id="task-123",
            title="Test task",
            chat_id="chat-1",
            message_id="msg-1",
        )

        mock_notion.reset_mock()

        # Restore by ID
        result = await service.restore_by_id("task-123", "chat-1")

        assert result.success is True
        assert result.entity_id == "task-123"
        mock_notion.undo_delete.assert_called_once_with("task-123")

    @pytest.mark.asyncio
    async def test_restore_by_id_unknown(self, service, mock_notion):
        """restore_by_id should work even for untracked entities."""
        result = await service.restore_by_id("unknown-id", "chat-1")

        assert result.success is True
        mock_notion.undo_delete.assert_called_once_with("unknown-id")

    def test_get_pending_deletes_count(self, service):
        """get_pending_deletes_count should count restorable items."""
        # Add some deletions
        service._deleted_items["chat-1"].append(
            DeletedAction(
                entity_type="task",
                entity_id="task-1",
                title="Task 1",
                deleted_at=datetime.utcnow(),
            )
        )
        service._deleted_items["chat-1"].append(
            DeletedAction(
                entity_type="task",
                entity_id="task-2",
                title="Task 2",
                deleted_at=datetime.utcnow() - timedelta(days=31),  # Expired
            )
        )

        assert service.get_pending_deletes_count("chat-1") == 1

    def test_max_deleted_items_limit(self, service):
        """Should limit tracked deletions per chat."""
        # Track more than MAX_DELETED_ITEMS
        for i in range(service.MAX_DELETED_ITEMS + 10):
            deleted = DeletedAction(
                entity_type="task",
                entity_id=f"task-{i}",
                title=f"Task {i}",
            )
            service._track_deletion("chat-1", deleted)

        # Should be limited to MAX_DELETED_ITEMS
        assert len(service._deleted_items["chat-1"]) <= service.MAX_DELETED_ITEMS


class TestPatternMatching:
    """Tests for command pattern matching."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("undo", True),
            ("Undo", True),
            ("UNDO", True),
            ("undo that", True),
            ("undo this", True),
            ("undo it", True),
            ("undo last", True),
            ("restore", True),
            ("restore it", True),
            ("bring that back", True),
            ("bring it back", True),
            ("undelete", True),
            ("recover", True),
            # Non-undo commands
            ("delete that", False),
            ("undo the laundry", False),  # Not a command pattern
            ("something undo", False),
            ("", False),
        ],
    )
    def test_is_undo_command(self, text, expected):
        """Test undo command detection."""
        assert is_undo_command(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("delete that", True),
            ("Delete that", True),
            ("DELETE THAT", True),
            ("delete this", True),
            ("delete it", True),
            ("remove that", True),
            ("remove this", True),
            ("remove it", True),
            ("forget that", True),
            ("forget this", True),
            ("forget it", True),
            ("forget about that", True),
            ("forget about this", True),
            ("forget about it", True),
            # Non-delete commands
            ("undo", False),
            ("delete the file", False),  # Not the pattern
            ("I should delete that", False),
            ("", False),
        ],
    )
    def test_is_delete_command(self, text, expected):
        """Test delete command detection."""
        assert is_delete_command(text) == expected


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_soft_delete_function(self):
        """Test soft_delete convenience function."""
        with patch.object(
            SoftDeleteService,
            "soft_delete",
            new_callable=AsyncMock,
        ) as mock_delete:
            mock_delete.return_value = DeleteResult(success=True)

            result = await soft_delete(
                entity_type="task",
                entity_id="task-1",
                title="Test",
                chat_id="chat-1",
                message_id="msg-1",
            )

            assert result.success is True

    @pytest.mark.asyncio
    async def test_undo_last_delete_function(self):
        """Test undo_last_delete convenience function."""
        with patch.object(
            SoftDeleteService,
            "undo_last_delete",
            new_callable=AsyncMock,
        ) as mock_undo:
            mock_undo.return_value = UndoResult(success=True)

            result = await undo_last_delete("chat-1")

            assert result.success is True


class TestAT118Integration:
    """Integration tests for AT-118 acceptance criteria.

    AT-118: Soft Delete Recovery
    - Given: Task "Buy groceries" exists
    - When: User says "delete that"
    - Then: Task.deleted_at set to current timestamp
    - And: Task hidden from /today and briefings
    - When: User says "undo" within 30 days
    - Then: Task.deleted_at cleared, task visible again
    """

    @pytest.fixture
    def mock_notion(self):
        """Create a mock NotionClient that tracks state."""
        mock = MagicMock()

        # Track the deleted state
        deleted_at: dict[str, datetime | None] = {}

        async def soft_delete(page_id: str):
            deleted_at[page_id] = datetime.utcnow()

        async def undo_delete(page_id: str):
            deleted_at[page_id] = None

        mock.soft_delete = AsyncMock(side_effect=soft_delete)
        mock.undo_delete = AsyncMock(side_effect=undo_delete)
        mock.log_action = AsyncMock(return_value="log-id")
        mock._deleted_at = deleted_at

        return mock

    @pytest.mark.asyncio
    async def test_at118_delete_and_undo_flow(self, mock_notion):
        """Full AT-118 scenario: delete → undo within 30 days → restored."""
        service = SoftDeleteService(notion_client=mock_notion)

        # Step 1: User says "delete that" for "Buy groceries"
        delete_result = await service.soft_delete(
            entity_type="task",
            entity_id="task-groceries",
            title="Buy groceries",
            chat_id="chat-1",
            message_id="msg-1",
        )

        # Then: Task.deleted_at set to current timestamp
        assert delete_result.success is True
        assert mock_notion._deleted_at["task-groceries"] is not None
        assert isinstance(mock_notion._deleted_at["task-groceries"], datetime)

        # And: Task hidden from /today and briefings
        # (This is verified by NotionClient.query_tasks excluding deleted items)

        # Step 2: User says "undo" within 30 days
        undo_result = await service.undo_last_delete("chat-1")

        # Then: Task.deleted_at cleared, task visible again
        assert undo_result.success is True
        assert undo_result.title == "Buy groceries"
        assert mock_notion._deleted_at["task-groceries"] is None

    @pytest.mark.asyncio
    async def test_at118_undo_after_30_days_fails(self, mock_notion):
        """AT-118: Undo after 30 days should fail."""
        service = SoftDeleteService(notion_client=mock_notion)

        # Manually add an old deletion (beyond 30 days)
        old_deletion = DeletedAction(
            entity_type="task",
            entity_id="task-old",
            title="Old groceries",
            deleted_at=datetime.utcnow() - timedelta(days=31),
            chat_id="chat-1",
        )
        service._deleted_items["chat-1"].append(old_deletion)

        # Attempt undo should fail
        result = await service.undo_last_delete("chat-1")

        assert result.success is False
        assert "30 days" in result.message
