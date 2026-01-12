"""Offline queue service for Second Brain.

Implements PRD Section 4.8 (Failure Handling):
- Queue actions when Notion is unavailable
- Provide immediate user feedback
- Process queue on recovery with deduplication

AT-114: User receives immediate response when Notion is down
AT-115: Queued items sync to Notion in order on recovery
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from assistant.config import settings

logger = logging.getLogger(__name__)


class QueuedActionType(str, Enum):
    """Types of actions that can be queued."""

    CREATE_INBOX = "create_inbox"
    CREATE_TASK = "create_task"
    CREATE_PERSON = "create_person"
    CREATE_PLACE = "create_place"
    CREATE_PROJECT = "create_project"
    CREATE_LOG_ENTRY = "create_log_entry"
    UPDATE_TASK = "update_task"
    UPDATE_PERSON = "update_person"
    SOFT_DELETE = "soft_delete"


@dataclass
class QueuedAction:
    """Represents an action queued for offline processing."""

    action_type: QueuedActionType
    timestamp: datetime
    idempotency_key: str
    data: dict[str, Any]
    chat_id: str | None = None
    message_id: str | None = None
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "timestamp": self.timestamp.isoformat(),
            "idempotency_key": self.idempotency_key,
            "data": self.data,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QueuedAction":
        return cls(
            action_type=QueuedActionType(d["action_type"]),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            idempotency_key=d["idempotency_key"],
            data=d["data"],
            chat_id=d.get("chat_id"),
            message_id=d.get("message_id"),
            retry_count=d.get("retry_count", 0),
        )


@dataclass
class QueueProcessResult:
    """Result of processing the offline queue."""

    total_processed: int = 0
    successful: int = 0
    failed: int = 0
    deduplicated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def all_successful(self) -> bool:
        return self.failed == 0 and self.total_processed > 0


class OfflineQueue:
    """Manages offline queue for Notion API failures.

    Per PRD 4.8:
    - Retries 3x with exponential backoff (1s, 2s, 4s)
    - After retries fail, queues to local file
    - User gets immediate feedback: "Saved locally, will sync when Notion is back"
    - On recovery, processes queue in order with deduplication
    """

    DEFAULT_QUEUE_PATH = Path.home() / ".second-brain" / "queue" / "pending.jsonl"
    MAX_RETRIES = 3

    def __init__(self, queue_path: Path | None = None):
        self.queue_path = queue_path or self.DEFAULT_QUEUE_PATH
        self._processed_keys: set[str] = set()  # In-memory dedupe cache

    def _ensure_queue_dir(self) -> None:
        """Ensure queue directory exists."""
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)

    def enqueue(self, action: QueuedAction) -> None:
        """Add an action to the offline queue.

        Args:
            action: Action to queue
        """
        self._ensure_queue_dir()

        with open(self.queue_path, "a") as f:
            f.write(json.dumps(action.to_dict()) + "\n")

        logger.info(f"Queued {action.action_type.value} action: {action.idempotency_key}")

    def queue_inbox_item(
        self,
        raw_input: str,
        chat_id: str,
        message_id: str,
        confidence: int,
        interpretation: str | None = None,
    ) -> str:
        """Queue an inbox item for later sync.

        Args:
            raw_input: Original user input
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            confidence: AI confidence score
            interpretation: Optional AI interpretation

        Returns:
            Idempotency key for the queued action
        """
        idempotency_key = f"telegram:{chat_id}:{message_id}"

        action = QueuedAction(
            action_type=QueuedActionType.CREATE_INBOX,
            timestamp=datetime.utcnow(),
            idempotency_key=idempotency_key,
            chat_id=chat_id,
            message_id=message_id,
            data={
                "raw_input": raw_input,
                "source": "telegram_text",
                "telegram_chat_id": chat_id,
                "telegram_message_id": message_id,
                "confidence": confidence,
                "needs_clarification": confidence < settings.confidence_threshold,
                "interpretation": interpretation,
            },
        )

        self.enqueue(action)
        return idempotency_key

    def queue_task(
        self,
        title: str,
        chat_id: str,
        message_id: str,
        due_date: datetime | None = None,
        due_timezone: str | None = None,
        confidence: int = 80,
        priority: str = "medium",
    ) -> str:
        """Queue a task creation for later sync.

        Args:
            title: Task title
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            due_date: Optional due date
            due_timezone: Optional timezone
            confidence: AI confidence score
            priority: Task priority

        Returns:
            Idempotency key for the queued action
        """
        idempotency_key = f"telegram:{chat_id}:{message_id}"

        data: dict[str, Any] = {
            "title": title,
            "source": "telegram",
            "confidence": confidence,
            "priority": priority,
            "created_by": "ai",
        }

        if due_date:
            data["due_date"] = due_date.isoformat()
        if due_timezone:
            data["due_timezone"] = due_timezone

        action = QueuedAction(
            action_type=QueuedActionType.CREATE_TASK,
            timestamp=datetime.utcnow(),
            idempotency_key=idempotency_key,
            chat_id=chat_id,
            message_id=message_id,
            data=data,
        )

        self.enqueue(action)
        return idempotency_key

    def get_pending_count(self) -> int:
        """Get count of pending items in queue.

        Returns:
            Number of queued actions
        """
        if not self.queue_path.exists():
            return 0

        with open(self.queue_path) as f:
            return sum(1 for _ in f)

    def read_queue(self) -> list[QueuedAction]:
        """Read all actions from the queue.

        Returns:
            List of queued actions in order
        """
        if not self.queue_path.exists():
            return []

        actions = []
        with open(self.queue_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        actions.append(QueuedAction.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning(f"Skipping malformed queue entry: {e}")

        return actions

    def clear_queue(self) -> None:
        """Clear all items from the queue."""
        if self.queue_path.exists():
            self.queue_path.unlink()
        self._processed_keys.clear()

    def write_queue(self, actions: list[QueuedAction]) -> None:
        """Write actions back to queue (for partial failure handling).

        Args:
            actions: Actions to write
        """
        if not actions:
            self.clear_queue()
            return

        self._ensure_queue_dir()

        with open(self.queue_path, "w") as f:
            for action in actions:
                f.write(json.dumps(action.to_dict()) + "\n")

    async def process_queue(
        self,
        notion_client: Any | None = None,
    ) -> QueueProcessResult:
        """Process all queued actions.

        Per PRD AT-115:
        - All items synced to Notion in order
        - Deduplicated by idempotency_key
        - Queue cleared after successful processing

        Args:
            notion_client: Optional NotionClient instance

        Returns:
            Result with counts of processed/failed items
        """
        from assistant.notion import NotionClient

        actions = self.read_queue()
        if not actions:
            return QueueProcessResult()

        result = QueueProcessResult(total_processed=len(actions))

        # Use provided client or create new one
        client = notion_client or (NotionClient() if settings.has_notion else None)
        if not client:
            result.failed = len(actions)
            result.errors.append("Notion not configured")
            return result

        failed_actions: list[QueuedAction] = []

        try:
            for action in actions:
                # Check for duplicates
                if action.idempotency_key in self._processed_keys:
                    result.deduplicated += 1
                    logger.info(f"Deduplicated: {action.idempotency_key}")
                    continue

                try:
                    await self._process_action(client, action)
                    self._processed_keys.add(action.idempotency_key)
                    result.successful += 1
                    logger.info(f"Synced {action.action_type.value}: {action.idempotency_key}")

                except Exception as e:
                    action.retry_count += 1
                    if action.retry_count < self.MAX_RETRIES:
                        failed_actions.append(action)
                    result.failed += 1
                    result.errors.append(f"{action.idempotency_key}: {str(e)}")
                    logger.error(f"Failed to sync {action.idempotency_key}: {e}")

        finally:
            # Write back any failed actions for retry
            self.write_queue(failed_actions)

            # Close client if we created it
            if notion_client is None and client:
                await client.close()

        return result

    async def _process_action(
        self,
        client: Any,
        action: QueuedAction,
    ) -> str:
        """Process a single queued action.

        Args:
            client: NotionClient instance
            action: Action to process

        Returns:
            ID of created/updated resource
        """
        from assistant.notion.schemas import (
            InboxItem,
            InboxSource,
            Task,
            TaskPriority,
            TaskSource,
        )

        data = action.data

        if action.action_type == QueuedActionType.CREATE_INBOX:
            # Parse source enum
            source_str = data.get("source", "telegram_text")
            try:
                source = InboxSource(source_str)
            except ValueError:
                source = InboxSource.TELEGRAM_TEXT

            item = InboxItem(
                raw_input=data["raw_input"],
                source=source,
                telegram_chat_id=data.get("telegram_chat_id"),
                telegram_message_id=data.get("telegram_message_id"),
                confidence=data.get("confidence", 50),
                needs_clarification=data.get("needs_clarification", True),
                interpretation=data.get("interpretation"),
            )
            return await client.create_inbox_item(item)

        elif action.action_type == QueuedActionType.CREATE_TASK:
            # Parse priority enum
            priority_str = data.get("priority", "medium")
            try:
                priority = TaskPriority(priority_str)
            except ValueError:
                priority = TaskPriority.MEDIUM

            # Parse source enum
            task_source_str = data.get("source", "telegram")
            try:
                task_source = TaskSource(task_source_str)
            except ValueError:
                task_source = TaskSource.TELEGRAM

            # Parse due_date if present
            due_date = None
            if data.get("due_date"):
                due_date = datetime.fromisoformat(data["due_date"])

            task = Task(
                title=data["title"],
                due_date=due_date,
                due_timezone=data.get("due_timezone"),
                source=task_source,
                confidence=data.get("confidence", 80),
                priority=priority,
                created_by=data.get("created_by", "ai"),
            )
            return await client.create_task(task)

        else:
            raise NotImplementedError(f"Action type {action.action_type.value} not implemented")


# Module-level singleton and convenience functions
_offline_queue: OfflineQueue | None = None


def get_offline_queue(queue_path: Path | None = None) -> OfflineQueue:
    """Get the singleton offline queue instance.

    Args:
        queue_path: Optional custom queue path

    Returns:
        OfflineQueue instance
    """
    global _offline_queue
    if _offline_queue is None or queue_path is not None:
        _offline_queue = OfflineQueue(queue_path)
    return _offline_queue


def queue_for_offline_sync(
    action_type: QueuedActionType,
    idempotency_key: str,
    data: dict[str, Any],
    chat_id: str | None = None,
    message_id: str | None = None,
) -> None:
    """Convenience function to queue an action for offline sync.

    Args:
        action_type: Type of action
        idempotency_key: Key for deduplication
        data: Action data
        chat_id: Optional Telegram chat ID
        message_id: Optional Telegram message ID
    """
    queue = get_offline_queue()
    action = QueuedAction(
        action_type=action_type,
        timestamp=datetime.utcnow(),
        idempotency_key=idempotency_key,
        data=data,
        chat_id=chat_id,
        message_id=message_id,
    )
    queue.enqueue(action)


async def process_offline_queue(
    notion_client: Any | None = None,
) -> QueueProcessResult:
    """Process the offline queue.

    Args:
        notion_client: Optional NotionClient instance

    Returns:
        Result with counts of processed/failed items
    """
    queue = get_offline_queue()
    return await queue.process_queue(notion_client)


def get_offline_response() -> str:
    """Get the standard response for offline mode.

    Per PRD 4.8: User should receive this response when Notion is unavailable.

    Returns:
        User-facing message
    """
    return "Saved locally, will sync when Notion is back"
