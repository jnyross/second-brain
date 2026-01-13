"""Tests for offline queue service (T-114).

Implements tests for PRD Section 4.8 (Failure Handling):
- AT-114: Notion Offline Queue
- AT-115: Notion Recovery Sync
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.services.offline_queue import (
    OfflineQueue,
    QueuedAction,
    QueuedActionType,
    get_offline_queue,
    get_offline_response,
    queue_for_offline_sync,
)


class TestOfflineQueue:
    """Test OfflineQueue basic operations."""

    @pytest.fixture
    def temp_queue_path(self, tmp_path: Path) -> Path:
        """Create a temporary queue path."""
        return tmp_path / "queue" / "pending.jsonl"

    @pytest.fixture
    def queue(self, temp_queue_path: Path) -> OfflineQueue:
        """Create an OfflineQueue with temporary path."""
        return OfflineQueue(queue_path=temp_queue_path)

    def test_enqueue_creates_directory(self, queue: OfflineQueue, temp_queue_path: Path):
        """Test that enqueue creates the queue directory if needed."""
        action = QueuedAction(
            action_type=QueuedActionType.CREATE_TASK,
            timestamp=datetime.now(UTC),
            idempotency_key="test:123:456",
            data={"title": "Test task"},
        )

        queue.enqueue(action)

        assert temp_queue_path.parent.exists()
        assert temp_queue_path.exists()

    def test_enqueue_writes_action(self, queue: OfflineQueue, temp_queue_path: Path):
        """Test that enqueue writes action to file."""
        action = QueuedAction(
            action_type=QueuedActionType.CREATE_TASK,
            timestamp=datetime.now(UTC),
            idempotency_key="test:123:456",
            data={"title": "Test task"},
            chat_id="123",
            message_id="456",
        )

        queue.enqueue(action)

        with open(temp_queue_path) as f:
            line = f.readline()
            data = json.loads(line)

        assert data["action_type"] == "create_task"
        assert data["idempotency_key"] == "test:123:456"
        assert data["data"]["title"] == "Test task"
        assert data["chat_id"] == "123"
        assert data["message_id"] == "456"

    def test_read_queue_empty(self, queue: OfflineQueue):
        """Test reading empty queue returns empty list."""
        actions = queue.read_queue()
        assert actions == []

    def test_read_queue_with_items(self, queue: OfflineQueue, temp_queue_path: Path):
        """Test reading queue with items."""
        # Enqueue multiple items
        for i in range(3):
            action = QueuedAction(
                action_type=QueuedActionType.CREATE_TASK,
                timestamp=datetime.now(UTC),
                idempotency_key=f"test:123:{i}",
                data={"title": f"Task {i}"},
            )
            queue.enqueue(action)

        actions = queue.read_queue()

        assert len(actions) == 3
        assert actions[0].data["title"] == "Task 0"
        assert actions[1].data["title"] == "Task 1"
        assert actions[2].data["title"] == "Task 2"

    def test_get_pending_count(self, queue: OfflineQueue):
        """Test getting pending count."""
        assert queue.get_pending_count() == 0

        for i in range(5):
            action = QueuedAction(
                action_type=QueuedActionType.CREATE_TASK,
                timestamp=datetime.now(UTC),
                idempotency_key=f"test:{i}",
                data={"title": f"Task {i}"},
            )
            queue.enqueue(action)

        assert queue.get_pending_count() == 5

    def test_clear_queue(self, queue: OfflineQueue, temp_queue_path: Path):
        """Test clearing the queue."""
        action = QueuedAction(
            action_type=QueuedActionType.CREATE_TASK,
            timestamp=datetime.now(UTC),
            idempotency_key="test:123:456",
            data={"title": "Test"},
        )
        queue.enqueue(action)

        assert queue.get_pending_count() == 1

        queue.clear_queue()

        assert queue.get_pending_count() == 0
        assert not temp_queue_path.exists()


class TestQueueInboxItem:
    """Test queue_inbox_item helper."""

    @pytest.fixture
    def queue(self, tmp_path: Path) -> OfflineQueue:
        return OfflineQueue(queue_path=tmp_path / "queue" / "pending.jsonl")

    def test_queue_inbox_item_basic(self, queue: OfflineQueue):
        """Test queuing an inbox item."""
        key = queue.queue_inbox_item(
            raw_input="Buy milk tomorrow",
            chat_id="123",
            message_id="456",
            confidence=35,
            interpretation="Possibly a task",
        )

        assert key == "telegram:123:456"
        assert queue.get_pending_count() == 1

        actions = queue.read_queue()
        assert len(actions) == 1
        assert actions[0].action_type == QueuedActionType.CREATE_INBOX
        assert actions[0].data["raw_input"] == "Buy milk tomorrow"
        assert actions[0].data["confidence"] == 35
        assert actions[0].data["needs_clarification"] is True
        assert actions[0].data["interpretation"] == "Possibly a task"


class TestQueueTask:
    """Test queue_task helper."""

    @pytest.fixture
    def queue(self, tmp_path: Path) -> OfflineQueue:
        return OfflineQueue(queue_path=tmp_path / "queue" / "pending.jsonl")

    def test_queue_task_basic(self, queue: OfflineQueue):
        """Test queuing a task."""
        key = queue.queue_task(
            title="Buy milk",
            chat_id="123",
            message_id="456",
            confidence=95,
        )

        assert key == "telegram:123:456"
        assert queue.get_pending_count() == 1

        actions = queue.read_queue()
        assert len(actions) == 1
        assert actions[0].action_type == QueuedActionType.CREATE_TASK
        assert actions[0].data["title"] == "Buy milk"
        assert actions[0].data["confidence"] == 95

    def test_queue_task_with_due_date(self, queue: OfflineQueue):
        """Test queuing a task with due date."""
        due_date = datetime(2026, 1, 15, 14, 0)

        queue.queue_task(
            title="Meeting",
            chat_id="123",
            message_id="456",
            due_date=due_date,
            due_timezone="America/Los_Angeles",
        )

        actions = queue.read_queue()
        assert actions[0].data["due_date"] == "2026-01-15T14:00:00"
        assert actions[0].data["due_timezone"] == "America/Los_Angeles"


class TestQueueProcessing:
    """Test queue processing (AT-115)."""

    @pytest.fixture
    def queue(self, tmp_path: Path) -> OfflineQueue:
        return OfflineQueue(queue_path=tmp_path / "queue" / "pending.jsonl")

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock NotionClient."""
        client = MagicMock()
        client.create_inbox_item = AsyncMock(return_value="inbox-123")
        client.create_task = AsyncMock(return_value="task-456")
        client.close = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_process_empty_queue(self, queue: OfflineQueue):
        """Test processing empty queue."""
        result = await queue.process_queue()

        assert result.total_processed == 0
        assert result.successful == 0
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_process_queue_success(self, queue: OfflineQueue, mock_notion_client):
        """AT-115: All queued items synced to Notion in order."""
        # Queue 3 items
        for i in range(3):
            queue.queue_task(
                title=f"Task {i}",
                chat_id="123",
                message_id=str(i),
            )

        assert queue.get_pending_count() == 3

        # Process queue
        result = await queue.process_queue(notion_client=mock_notion_client)

        assert result.total_processed == 3
        assert result.successful == 3
        assert result.failed == 0
        assert result.all_successful

        # Queue should be cleared
        assert queue.get_pending_count() == 0

        # Verify Notion client was called 3 times
        assert mock_notion_client.create_task.call_count == 3

    @pytest.mark.asyncio
    async def test_process_queue_with_failures(self, queue: OfflineQueue, mock_notion_client):
        """Test partial failures keep items in queue for retry."""
        # Queue 3 items
        for i in range(3):
            queue.queue_task(
                title=f"Task {i}",
                chat_id="123",
                message_id=str(i),
            )

        # First call succeeds, second fails, third succeeds
        mock_notion_client.create_task.side_effect = [
            "task-0",
            Exception("API error"),
            "task-2",
        ]

        result = await queue.process_queue(notion_client=mock_notion_client)

        assert result.total_processed == 3
        assert result.successful == 2
        assert result.failed == 1
        assert len(result.errors) == 1
        assert "API error" in result.errors[0]

        # Failed item should remain in queue
        assert queue.get_pending_count() == 1

        # Retry count should be incremented
        remaining = queue.read_queue()
        assert remaining[0].retry_count == 1

    @pytest.mark.asyncio
    async def test_process_queue_deduplication(self, queue: OfflineQueue, mock_notion_client):
        """Test deduplication of items with same idempotency key."""
        # Queue same item twice
        queue.queue_task(title="Task 1", chat_id="123", message_id="456")
        queue.queue_task(title="Task 1 again", chat_id="123", message_id="456")

        assert queue.get_pending_count() == 2

        result = await queue.process_queue(notion_client=mock_notion_client)

        assert result.total_processed == 2
        assert result.successful == 1
        assert result.deduplicated == 1

        # Only one task created
        assert mock_notion_client.create_task.call_count == 1

    @pytest.mark.asyncio
    async def test_process_queue_order_preserved(self, queue: OfflineQueue, mock_notion_client):
        """AT-115: Items synced to Notion in original order."""
        titles = ["First", "Second", "Third"]

        for i, title in enumerate(titles):
            queue.queue_task(title=title, chat_id="123", message_id=str(i))

        await queue.process_queue(notion_client=mock_notion_client)

        # Verify order of calls
        calls = mock_notion_client.create_task.call_args_list
        assert len(calls) == 3

        for i, call in enumerate(calls):
            task_arg = call[0][0]  # First positional argument
            assert task_arg.title == titles[i]


class TestAT114OfflineCapture:
    """Tests for AT-114: Notion Offline Queue.

    Given: Notion API returns 503
    When: User sends "Call dentist"
    Then: Response sent within 5 seconds: "Saved locally, will sync when Notion is back"
    And: Item written to local queue file
    """

    @pytest.fixture
    def queue(self, tmp_path: Path) -> OfflineQueue:
        return OfflineQueue(queue_path=tmp_path / "queue" / "pending.jsonl")

    def test_get_offline_response_message(self):
        """Test that offline response message matches PRD requirement."""
        response = get_offline_response()
        assert "Saved locally" in response
        assert "sync" in response.lower()
        assert "Notion" in response

    def test_queue_item_when_notion_unavailable(self, queue: OfflineQueue):
        """Test that item is written to local queue when Notion fails."""
        # Simulate queuing when Notion is down
        key = queue.queue_task(
            title="Call dentist",
            chat_id="123",
            message_id="456",
            confidence=95,
        )

        # Verify item is in queue
        assert queue.get_pending_count() == 1

        actions = queue.read_queue()
        assert len(actions) == 1
        assert actions[0].data["title"] == "Call dentist"
        assert actions[0].idempotency_key == key

    def test_queue_persists_to_file(self, queue: OfflineQueue):
        """Test that queue persists to file system."""
        queue.queue_task(
            title="Call dentist",
            chat_id="123",
            message_id="456",
        )

        # Create new queue instance pointing to same file
        queue2 = OfflineQueue(queue_path=queue.queue_path)

        # Should see the same item
        assert queue2.get_pending_count() == 1
        actions = queue2.read_queue()
        assert actions[0].data["title"] == "Call dentist"


class TestAT115RecoverySync:
    """Tests for AT-115: Notion Recovery Sync.

    Given: Local queue has 3 pending items
    When: Notion becomes available
    Then: All 3 items synced to Notion in order
    And: Local queue cleared
    """

    @pytest.fixture
    def queue(self, tmp_path: Path) -> OfflineQueue:
        return OfflineQueue(queue_path=tmp_path / "queue" / "pending.jsonl")

    @pytest.fixture
    def mock_notion_client(self):
        client = MagicMock()
        client.create_inbox_item = AsyncMock(return_value="inbox-id")
        client.create_task = AsyncMock(return_value="task-id")
        client.close = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_three_items_synced_in_order(self, queue: OfflineQueue, mock_notion_client):
        """Test 3 items synced to Notion in order."""
        # Queue 3 items
        queue.queue_task(title="Task 1", chat_id="123", message_id="1")
        queue.queue_task(title="Task 2", chat_id="123", message_id="2")
        queue.queue_task(title="Task 3", chat_id="123", message_id="3")

        assert queue.get_pending_count() == 3

        # Process (simulating Notion recovery)
        result = await queue.process_queue(notion_client=mock_notion_client)

        # All 3 synced
        assert result.successful == 3
        assert mock_notion_client.create_task.call_count == 3

        # Order preserved
        calls = mock_notion_client.create_task.call_args_list
        assert calls[0][0][0].title == "Task 1"
        assert calls[1][0][0].title == "Task 2"
        assert calls[2][0][0].title == "Task 3"

    @pytest.mark.asyncio
    async def test_queue_cleared_after_success(self, queue: OfflineQueue, mock_notion_client):
        """Test queue is cleared after successful sync."""
        queue.queue_task(title="Task 1", chat_id="123", message_id="1")
        queue.queue_task(title="Task 2", chat_id="123", message_id="2")
        queue.queue_task(title="Task 3", chat_id="123", message_id="3")

        await queue.process_queue(notion_client=mock_notion_client)

        # Queue cleared
        assert queue.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_mixed_item_types(self, queue: OfflineQueue, mock_notion_client):
        """Test queue handles mixed action types."""
        # Queue inbox item
        queue.queue_inbox_item(
            raw_input="Something unclear",
            chat_id="123",
            message_id="1",
            confidence=40,
        )

        # Queue task
        queue.queue_task(title="Clear task", chat_id="123", message_id="2")

        # Queue another inbox item
        queue.queue_inbox_item(
            raw_input="Another unclear thing",
            chat_id="123",
            message_id="3",
            confidence=30,
        )

        result = await queue.process_queue(notion_client=mock_notion_client)

        assert result.successful == 3
        assert mock_notion_client.create_inbox_item.call_count == 2
        assert mock_notion_client.create_task.call_count == 1


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the module-level singleton between tests."""
        import assistant.services.offline_queue as module

        module._offline_queue = None
        yield
        module._offline_queue = None

    def test_get_offline_queue_singleton(self, tmp_path: Path):
        """Test that get_offline_queue returns singleton."""
        queue1 = get_offline_queue()
        queue2 = get_offline_queue()

        assert queue1 is queue2

    def test_get_offline_queue_custom_path(self, tmp_path: Path):
        """Test get_offline_queue with custom path."""
        custom_path = tmp_path / "custom" / "queue.jsonl"
        queue = get_offline_queue(queue_path=custom_path)

        assert queue.queue_path == custom_path

    def test_queue_for_offline_sync(self, tmp_path: Path):
        """Test queue_for_offline_sync convenience function."""
        custom_path = tmp_path / "queue" / "pending.jsonl"
        queue = get_offline_queue(queue_path=custom_path)

        queue_for_offline_sync(
            action_type=QueuedActionType.CREATE_TASK,
            idempotency_key="test:123:456",
            data={"title": "Test task"},
            chat_id="123",
            message_id="456",
        )

        assert queue.get_pending_count() == 1


class TestQueuedAction:
    """Test QueuedAction dataclass."""

    def test_to_dict(self):
        """Test serialization to dict."""
        timestamp = datetime(2026, 1, 12, 10, 0, 0)
        action = QueuedAction(
            action_type=QueuedActionType.CREATE_TASK,
            timestamp=timestamp,
            idempotency_key="test:123",
            data={"title": "Test"},
            chat_id="123",
            message_id="456",
            retry_count=2,
        )

        d = action.to_dict()

        assert d["action_type"] == "create_task"
        assert d["timestamp"] == "2026-01-12T10:00:00"
        assert d["idempotency_key"] == "test:123"
        assert d["data"] == {"title": "Test"}
        assert d["chat_id"] == "123"
        assert d["message_id"] == "456"
        assert d["retry_count"] == 2

    def test_from_dict(self):
        """Test deserialization from dict."""
        d = {
            "action_type": "create_inbox",
            "timestamp": "2026-01-12T10:00:00",
            "idempotency_key": "test:123",
            "data": {"raw_input": "Hello"},
            "chat_id": "123",
            "retry_count": 1,
        }

        action = QueuedAction.from_dict(d)

        assert action.action_type == QueuedActionType.CREATE_INBOX
        assert action.timestamp == datetime(2026, 1, 12, 10, 0, 0)
        assert action.idempotency_key == "test:123"
        assert action.data == {"raw_input": "Hello"}
        assert action.chat_id == "123"
        assert action.message_id is None
        assert action.retry_count == 1

    def test_round_trip(self):
        """Test serialization round trip."""
        original = QueuedAction(
            action_type=QueuedActionType.CREATE_TASK,
            timestamp=datetime.now(UTC),
            idempotency_key="test:123:456",
            data={"title": "Test", "priority": "high"},
            chat_id="123",
            message_id="456",
        )

        restored = QueuedAction.from_dict(original.to_dict())

        assert restored.action_type == original.action_type
        assert restored.idempotency_key == original.idempotency_key
        assert restored.data == original.data
        assert restored.chat_id == original.chat_id
        assert restored.message_id == original.message_id
