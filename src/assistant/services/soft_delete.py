"""Soft delete service for Second Brain.

Implements soft delete and undo functionality per PRD Section 5.6:
- Soft delete sets `deleted_at` timestamp
- Records hidden from normal queries
- Recoverable via undo within 30 days
- Cleaned up after 30 days

Per PRD Section 6.2 - Undo & Rollback Semantics:
- User commands: "delete that", "remove [item]", "undo"
- Undo triggers: "wrong" or "undo" replies
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from assistant.notion import NotionClient
from assistant.notion.schemas import ActionType

logger = logging.getLogger(__name__)


# Undo window for soft-deleted items (30 days per PRD 5.6)
UNDO_WINDOW_DAYS = 30


@dataclass
class DeletedAction:
    """Tracks a deleted item for potential undo."""

    entity_type: str  # "task", "person", "place", "project"
    entity_id: str  # Notion page ID
    title: str  # The title/name that was deleted
    deleted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    chat_id: str = ""
    message_id: str = ""

    def is_within_undo_window(self, days: int = UNDO_WINDOW_DAYS) -> bool:
        """Check if this deletion can still be undone."""
        return datetime.now(UTC) - self.deleted_at < timedelta(days=days)


@dataclass
class DeleteResult:
    """Result of a soft delete operation."""

    success: bool
    entity_id: str | None = None
    entity_type: str | None = None
    title: str | None = None
    message: str = ""
    can_undo: bool = True


@dataclass
class UndoResult:
    """Result of an undo operation."""

    success: bool
    entity_id: str | None = None
    entity_type: str | None = None
    title: str | None = None
    message: str = ""


class SoftDeleteService:
    """Manages soft delete and undo operations.

    Maintains a per-chat history of deleted items for undo.
    Integrates with NotionClient for persistence.
    """

    # Maximum number of deleted items to track per chat
    MAX_DELETED_ITEMS = 50

    def __init__(self, notion_client: NotionClient | None = None):
        """Initialize the soft delete service.

        Args:
            notion_client: Optional NotionClient instance. If not provided,
                          one will be created when needed.
        """
        self._notion = notion_client

        # Per-chat deleted item history: chat_id -> list of DeletedAction
        self._deleted_items: dict[str, list[DeletedAction]] = defaultdict(list)

    @property
    def notion(self) -> NotionClient:
        """Get or create NotionClient instance."""
        if self._notion is None:
            self._notion = NotionClient()
        return self._notion

    async def soft_delete(
        self,
        entity_type: str,
        entity_id: str,
        title: str,
        chat_id: str,
        message_id: str,
    ) -> DeleteResult:
        """Soft delete an entity and track for undo.

        Args:
            entity_type: Type of entity ("task", "person", "place", "project")
            entity_id: Notion page ID
            title: The title/name of the entity
            chat_id: Telegram chat ID
            message_id: Telegram message ID

        Returns:
            DeleteResult with operation details
        """
        try:
            # Perform soft delete in Notion
            await self.notion.soft_delete(entity_id)

            # Track for undo
            deleted = DeletedAction(
                entity_type=entity_type,
                entity_id=entity_id,
                title=title,
                chat_id=chat_id,
                message_id=message_id,
            )
            self._track_deletion(chat_id, deleted)

            # Log the action
            await self.notion.log_action(
                action_type=ActionType.DELETE,
                idempotency_key=f"delete:{chat_id}:{message_id}",
                input_text=f"Delete {entity_type}: {title}",
                action_taken=f"Soft deleted: {title}",
                entities_affected=[entity_id],
            )

            logger.info(f"Soft deleted {entity_type} '{title}' (id={entity_id}) for chat {chat_id}")

            return DeleteResult(
                success=True,
                entity_id=entity_id,
                entity_type=entity_type,
                title=title,
                message=f'Done. Removed "{title}". Say "undo" to restore.',
                can_undo=True,
            )

        except Exception as e:
            logger.exception(f"Failed to soft delete {entity_type}: {e}")
            return DeleteResult(
                success=False,
                message="Sorry, I couldn't delete that. Please try again or edit in Notion.",
            )

    async def undo_last_delete(self, chat_id: str) -> UndoResult:
        """Undo the last deletion for a chat.

        Args:
            chat_id: Telegram chat ID

        Returns:
            UndoResult with operation details
        """
        # Get the last deleted item (including expired ones for proper error messages)
        deleted = self._get_last_deleted(chat_id, include_expired=True)

        if not deleted:
            return UndoResult(
                success=False,
                message="Nothing to undo. No recent deletions found.",
            )

        if not deleted.is_within_undo_window():
            return UndoResult(
                success=False,
                message=(
                    f'Can\'t undo - "{deleted.title}" was deleted more than '
                    f"{UNDO_WINDOW_DAYS} days ago."
                ),
            )

        try:
            # Restore in Notion
            await self.notion.undo_delete(deleted.entity_id)

            # Remove from deleted tracking
            self._remove_from_deleted(chat_id, deleted.entity_id)

            # Log the undo action
            await self.notion.log_action(
                action_type=ActionType.UPDATE,
                input_text=f"Undo delete: {deleted.title}",
                action_taken=f"Restored: {deleted.title}",
                entities_affected=[deleted.entity_id],
            )

            logger.info(
                f"Restored {deleted.entity_type} '{deleted.title}' "
                f"(id={deleted.entity_id}) for chat {chat_id}"
            )

            return UndoResult(
                success=True,
                entity_id=deleted.entity_id,
                entity_type=deleted.entity_type,
                title=deleted.title,
                message=f'Restored "{deleted.title}".',
            )

        except Exception as e:
            logger.exception(f"Failed to undo delete: {e}")
            return UndoResult(
                success=False,
                message="Sorry, I couldn't restore that. Please check Notion directly.",
            )

    async def restore_by_id(self, entity_id: str, chat_id: str) -> UndoResult:
        """Restore a specific entity by ID.

        Args:
            entity_id: Notion page ID to restore
            chat_id: Telegram chat ID

        Returns:
            UndoResult with operation details
        """
        # Find the deleted item in our tracking
        deleted = self._find_deleted_by_id(chat_id, entity_id)

        if deleted and not deleted.is_within_undo_window():
            return UndoResult(
                success=False,
                message=f"Can't restore - item was deleted more than {UNDO_WINDOW_DAYS} days ago.",
            )

        try:
            # Restore in Notion (works even if we don't have tracking)
            await self.notion.undo_delete(entity_id)

            # Remove from tracking if present
            if deleted:
                self._remove_from_deleted(chat_id, entity_id)
                title = deleted.title
                entity_type = deleted.entity_type
            else:
                title = "item"
                entity_type = "unknown"

            # Log the action
            await self.notion.log_action(
                action_type=ActionType.UPDATE,
                input_text=f"Restore: {title}",
                action_taken=f"Restored: {title}",
                entities_affected=[entity_id],
            )

            return UndoResult(
                success=True,
                entity_id=entity_id,
                entity_type=entity_type,
                title=title,
                message=f'Restored "{title}".',
            )

        except Exception as e:
            logger.exception(f"Failed to restore {entity_id}: {e}")
            return UndoResult(
                success=False,
                message="Sorry, I couldn't restore that item.",
            )

    def _track_deletion(self, chat_id: str, deleted: DeletedAction) -> None:
        """Track a deletion for potential undo."""
        items = self._deleted_items[chat_id]
        items.append(deleted)

        # Prune items outside undo window and limit size
        self._deleted_items[chat_id] = [d for d in items if d.is_within_undo_window()][
            -self.MAX_DELETED_ITEMS :
        ]

    def _get_last_deleted(
        self,
        chat_id: str,
        include_expired: bool = False,
    ) -> DeletedAction | None:
        """Get the most recent deleted item for a chat.

        Args:
            chat_id: Telegram chat ID
            include_expired: If True, return expired items too

        Returns:
            Most recent deleted item, or None
        """
        items = self._deleted_items.get(chat_id, [])

        if include_expired:
            return items[-1] if items else None

        # Filter to items within undo window
        valid = [d for d in items if d.is_within_undo_window()]

        return valid[-1] if valid else None

    def _find_deleted_by_id(
        self,
        chat_id: str,
        entity_id: str,
    ) -> DeletedAction | None:
        """Find a deleted item by ID."""
        items = self._deleted_items.get(chat_id, [])

        for deleted in items:
            if deleted.entity_id == entity_id:
                return deleted

        return None

    def _remove_from_deleted(self, chat_id: str, entity_id: str) -> None:
        """Remove an item from deleted tracking (after restore)."""
        if chat_id in self._deleted_items:
            self._deleted_items[chat_id] = [
                d for d in self._deleted_items[chat_id] if d.entity_id != entity_id
            ]

    def get_pending_deletes_count(self, chat_id: str) -> int:
        """Get count of items that can still be undone."""
        items = self._deleted_items.get(chat_id, [])
        return len([d for d in items if d.is_within_undo_window()])

    def get_pending_deletes(self, chat_id: str) -> list[DeletedAction]:
        """Get all items that can still be undone."""
        items = self._deleted_items.get(chat_id, [])
        return [d for d in items if d.is_within_undo_window()]

    async def close(self) -> None:
        """Close the Notion client connection."""
        if self._notion:
            await self._notion.close()


# Module-level singleton and convenience functions

_service: SoftDeleteService | None = None


def get_soft_delete_service() -> SoftDeleteService:
    """Get or create the global SoftDeleteService instance."""
    global _service
    if _service is None:
        _service = SoftDeleteService()
    return _service


async def soft_delete(
    entity_type: str,
    entity_id: str,
    title: str,
    chat_id: str,
    message_id: str,
) -> DeleteResult:
    """Soft delete an entity.

    Convenience function using global service.
    """
    return await get_soft_delete_service().soft_delete(
        entity_type=entity_type,
        entity_id=entity_id,
        title=title,
        chat_id=chat_id,
        message_id=message_id,
    )


async def undo_last_delete(chat_id: str) -> UndoResult:
    """Undo the last deletion for a chat.

    Convenience function using global service.
    """
    return await get_soft_delete_service().undo_last_delete(chat_id)


async def restore_by_id(entity_id: str, chat_id: str) -> UndoResult:
    """Restore a specific entity by ID.

    Convenience function using global service.
    """
    return await get_soft_delete_service().restore_by_id(entity_id, chat_id)


def is_undo_command(text: str) -> bool:
    """Check if text is an undo command.

    Returns True for: "undo", "restore", "bring back", "undelete"
    """
    import re

    text_lower = text.lower().strip()
    undo_patterns = [
        r"^undo$",
        r"^undo\s+(?:that|this|it|last)?\s*$",
        r"^restore\b",
        r"^bring\s+(?:that|it)\s+back\b",
        r"^undelete\b",
        r"^recover\b",
    ]

    for pattern in undo_patterns:
        if re.match(pattern, text_lower):
            return True
    return False


def is_delete_command(text: str) -> bool:
    """Check if text is a delete command.

    Returns True for: "delete that", "remove this", "forget it"
    """
    import re

    text_lower = text.lower().strip()
    delete_patterns = [
        r"^delete\s+(?:that|this|it)\b",
        r"^remove\s+(?:that|this|it)\b",
        r"^forget\s+(?:that|this|it|about\s+(?:that|this|it))\b",
    ]

    for pattern in delete_patterns:
        if re.match(pattern, text_lower):
            return True
    return False
