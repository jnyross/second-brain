import pytest
from datetime import datetime
from assistant.notion.schemas import (
    InboxItem,
    Task,
    Person,
    LogEntry,
    TaskStatus,
    TaskPriority,
    InboxSource,
    ActionType,
)


class TestInboxItem:
    def test_create_with_defaults(self):
        item = InboxItem(raw_input="Test input", source=InboxSource.TELEGRAM_TEXT)
        assert item.id is not None
        assert item.processed is False
        assert item.needs_clarification is False
        assert item.retry_count == 0

    def test_create_with_telegram_ids(self):
        item = InboxItem(
            raw_input="Test",
            source=InboxSource.TELEGRAM_TEXT,
            telegram_chat_id="123",
            telegram_message_id="456",
        )
        assert item.telegram_chat_id == "123"
        assert item.telegram_message_id == "456"


class TestTask:
    def test_create_with_defaults(self):
        task = Task(title="Test task")
        assert task.id is not None
        assert task.status == TaskStatus.TODO
        assert task.priority == TaskPriority.MEDIUM
        assert task.deleted_at is None

    def test_create_with_due_date(self):
        due = datetime(2026, 1, 15, 14, 0)
        task = Task(title="Test", due_date=due, due_timezone="America/Los_Angeles")
        assert task.due_date == due
        assert task.due_timezone == "America/Los_Angeles"


class TestPerson:
    def test_create_with_defaults(self):
        person = Person(name="John Doe")
        assert person.id is not None
        assert person.aliases == []
        assert person.archived is False

    def test_create_with_aliases(self):
        person = Person(name="John Doe", aliases=["Johnny", "JD"])
        assert len(person.aliases) == 2


class TestLogEntry:
    def test_create_with_action(self):
        entry = LogEntry(action_type=ActionType.CREATE)
        assert entry.id is not None
        assert entry.request_id is not None
        assert entry.undone is False

    def test_create_with_idempotency_key(self):
        entry = LogEntry(
            action_type=ActionType.CAPTURE,
            idempotency_key="telegram:123:456",
        )
        assert entry.idempotency_key == "telegram:123:456"
