"""Comprehensive audit logging service for Second Brain.

Implements AT-111 (every action logged) and AT-113 (idempotency).

Per PRD 4.9, every action has an idempotency key stored in Log:
- Process Telegram message: telegram:{chat_id}:{message_id}
- Create calendar event: calendar:{task_notion_id}:{date}
- Send email: email:{thread_id}:{response_hash}
- Morning briefing: briefing:{date}:{chat_id}

Deduplication process:
1. Before action, check Log for existing idempotency_key
2. If found and not error, skip action
3. If found with error, may retry based on error type
4. If not found, proceed and log with key
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from assistant.config import settings
from assistant.notion.schemas import ActionType, LogEntry

logger = logging.getLogger(__name__)


# Undo window per PRD 6.2
UNDO_WINDOW_MINUTES = 5


class DedupeResult(str, Enum):
    """Result of deduplication check."""
    NEW = "new"  # No existing entry, proceed with action
    DUPLICATE = "duplicate"  # Existing entry found, skip action
    RETRY = "retry"  # Existing entry with error, may retry


@dataclass
class AuditEntry:
    """Structured audit log entry for tracking."""
    log_id: str | None = None
    action_type: ActionType = ActionType.CAPTURE
    idempotency_key: str | None = None
    request_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    input_text: str | None = None
    interpretation: str | None = None
    action_taken: str | None = None
    confidence: int | None = None
    entities_affected: list[str] = field(default_factory=list)
    external_api: str | None = None
    external_resource_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    correction: str | None = None
    corrected_at: datetime | None = None
    undo_available_until: datetime | None = None
    undone: bool = False
    dedupe_result: DedupeResult | None = None


class AuditLogger:
    """Comprehensive audit logging service.

    Handles:
    - Logging all system actions to Notion Log database
    - Idempotency checking to prevent duplicate actions
    - Undo window tracking per PRD 6.2
    - Correction tracking for pattern learning
    """

    def __init__(self, notion_client: Any | None = None):
        """Initialize audit logger.

        Args:
            notion_client: NotionClient instance (lazy import to avoid circular deps)
        """
        self._notion = notion_client
        self._checked_keys: dict[str, AuditEntry] = {}  # In-memory cache

    @property
    def notion(self) -> Any:
        """Get or create Notion client."""
        if self._notion is None:
            from assistant.notion import NotionClient
            self._notion = NotionClient() if settings.has_notion else None
        return self._notion

    def generate_idempotency_key(
        self,
        key_type: str,
        *parts: str,
    ) -> str:
        """Generate idempotency key per PRD 4.9.

        Args:
            key_type: Type of key (telegram, calendar, email, briefing)
            *parts: Variable parts to include in key

        Returns:
            Idempotency key string

        Examples:
            >>> logger.generate_idempotency_key("telegram", "12345", "67890")
            "telegram:12345:67890"
            >>> logger.generate_idempotency_key("calendar", "task-id", "2026-01-12")
            "calendar:task-id:2026-01-12"
        """
        return f"{key_type}:{':'.join(str(p) for p in parts)}"

    async def check_idempotency(
        self,
        idempotency_key: str,
    ) -> tuple[DedupeResult, AuditEntry | None]:
        """Check if action with this key was already processed.

        Per PRD 4.9 deduplication process.

        Args:
            idempotency_key: Key to check

        Returns:
            Tuple of (DedupeResult, existing entry if found)
        """
        # Check memory cache first
        if idempotency_key in self._checked_keys:
            entry = self._checked_keys[idempotency_key]
            if entry.error_code:
                return DedupeResult.RETRY, entry
            return DedupeResult.DUPLICATE, entry

        if not self.notion:
            return DedupeResult.NEW, None

        try:
            existing = await self.notion._check_dedupe("log", idempotency_key)
            if existing:
                # Fetch full entry details
                entry = AuditEntry(
                    log_id=existing,
                    idempotency_key=idempotency_key,
                    dedupe_result=DedupeResult.DUPLICATE,
                )
                self._checked_keys[idempotency_key] = entry
                return DedupeResult.DUPLICATE, entry
        except Exception as e:
            logger.warning(f"Idempotency check failed: {e}")

        return DedupeResult.NEW, None

    async def log_action(
        self,
        action_type: ActionType,
        idempotency_key: str | None = None,
        input_text: str | None = None,
        interpretation: str | None = None,
        action_taken: str | None = None,
        confidence: int | None = None,
        entities_affected: list[str] | None = None,
        external_api: str | None = None,
        external_resource_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retry_count: int = 0,
        correction: str | None = None,
        include_undo_window: bool = False,
    ) -> AuditEntry:
        """Log an action to the audit trail.

        AT-111: Every action gets a log entry with timestamp, action_type, input, action_taken.

        Args:
            action_type: Type of action (capture, create, update, etc.)
            idempotency_key: Key for deduplication
            input_text: Original user input (redacted if sensitive)
            interpretation: How AI understood the input
            action_taken: What was done
            confidence: AI confidence score 0-100
            entities_affected: List of Notion page IDs affected
            external_api: Which external API was called
            external_resource_id: ID in external system
            error_code: Error code if failed
            error_message: Error details if failed
            retry_count: Number of retries attempted
            correction: If corrected, what was wrong
            include_undo_window: Whether to include undo_available_until

        Returns:
            AuditEntry with log_id populated if successful
        """
        entry = AuditEntry(
            action_type=action_type,
            idempotency_key=idempotency_key,
            timestamp=datetime.utcnow(),
            input_text=input_text,
            interpretation=interpretation,
            action_taken=action_taken,
            confidence=confidence,
            entities_affected=entities_affected or [],
            external_api=external_api,
            external_resource_id=external_resource_id,
            error_code=error_code,
            error_message=error_message,
            retry_count=retry_count,
            correction=correction,
            corrected_at=datetime.utcnow() if correction else None,
        )

        # Set undo window for reversible actions
        if include_undo_window:
            entry.undo_available_until = datetime.utcnow() + timedelta(
                minutes=UNDO_WINDOW_MINUTES
            )

        if not self.notion:
            logger.debug(f"No Notion client, logging locally: {action_type.value}")
            return entry

        try:
            log_entry = LogEntry(
                action_type=action_type,
                idempotency_key=idempotency_key,
                input_text=input_text,
                interpretation=interpretation,
                action_taken=action_taken,
                confidence=confidence,
                entities_affected=entities_affected or [],
                external_api=external_api,
                external_resource_id=external_resource_id,
                error_code=error_code,
                error_message=error_message,
                retry_count=retry_count,
                correction=correction,
                corrected_at=entry.corrected_at,
                undo_available_until=entry.undo_available_until,
            )
            entry.log_id = await self.notion.create_log_entry(log_entry)

            # Update memory cache
            if idempotency_key:
                self._checked_keys[idempotency_key] = entry

        except Exception as e:
            logger.exception(f"Failed to create log entry: {e}")
            entry.error_message = str(e)

        return entry

    async def log_deduplicated(
        self,
        idempotency_key: str,
        original_log_id: str | None = None,
    ) -> AuditEntry:
        """Log that a duplicate action was skipped.

        AT-113: Second attempt logged as "deduplicated".

        Args:
            idempotency_key: Key that was duplicated
            original_log_id: ID of original log entry if known

        Returns:
            AuditEntry for the dedupe log
        """
        return await self.log_action(
            action_type=ActionType.CAPTURE,  # Use capture for dedupe events
            idempotency_key=f"dedupe:{idempotency_key}",
            action_taken=f"Deduplicated (original key: {idempotency_key})",
            entities_affected=[original_log_id] if original_log_id else [],
        )

    async def log_capture(
        self,
        idempotency_key: str,
        input_text: str,
        confidence: int,
        inbox_id: str | None = None,
        needs_clarification: bool = False,
    ) -> AuditEntry:
        """Log a message capture action.

        Args:
            idempotency_key: Telegram message key
            input_text: Original user input
            confidence: Confidence score
            inbox_id: Notion inbox item ID if created
            needs_clarification: Whether item needs review

        Returns:
            AuditEntry for the capture
        """
        action = "Added to inbox"
        if needs_clarification:
            action += " (needs clarification)"
        if inbox_id:
            action += f" [{inbox_id[:8]}...]"

        return await self.log_action(
            action_type=ActionType.CAPTURE,
            idempotency_key=idempotency_key,
            input_text=input_text,
            action_taken=action,
            confidence=confidence,
            entities_affected=[inbox_id] if inbox_id else [],
            external_api="telegram",
        )

    async def log_create(
        self,
        idempotency_key: str,
        input_text: str,
        entity_type: str,
        entity_id: str,
        title: str,
        confidence: int,
        interpretation: str | None = None,
        external_api: str | None = None,
        external_resource_id: str | None = None,
        include_undo_window: bool = True,
    ) -> AuditEntry:
        """Log a create action (task, person, place, calendar event, etc.).

        Args:
            idempotency_key: Action idempotency key
            input_text: Original user input
            entity_type: Type of entity (task, person, place, calendar_event)
            entity_id: Notion page ID of created entity
            title: Title/name of created entity
            confidence: Confidence score
            interpretation: How AI understood the input
            external_api: External API called (notion, google, etc.)
            external_resource_id: ID in external system
            include_undo_window: Whether to include undo window

        Returns:
            AuditEntry for the create
        """
        # Map entity type to action type
        action_type_map = {
            "task": ActionType.CREATE,
            "person": ActionType.CREATE,
            "place": ActionType.CREATE,
            "project": ActionType.CREATE,
            "calendar_event": ActionType.CALENDAR_CREATE,
            "email": ActionType.EMAIL_SEND,
        }
        action_type = action_type_map.get(entity_type, ActionType.CREATE)

        return await self.log_action(
            action_type=action_type,
            idempotency_key=idempotency_key,
            input_text=input_text,
            interpretation=interpretation,
            action_taken=f"Created {entity_type}: {title}",
            confidence=confidence,
            entities_affected=[entity_id],
            external_api=external_api or "notion",
            external_resource_id=external_resource_id,
            include_undo_window=include_undo_window,
        )

    async def log_update(
        self,
        entity_id: str,
        entity_type: str,
        field_name: str,
        old_value: str | None,
        new_value: str,
        reason: str | None = None,
    ) -> AuditEntry:
        """Log an update action.

        Args:
            entity_id: Notion page ID of updated entity
            entity_type: Type of entity
            field_name: Field that was updated
            old_value: Previous value
            new_value: New value
            reason: Why the update was made (e.g., "user correction")

        Returns:
            AuditEntry for the update
        """
        correction = None
        if old_value and old_value != new_value:
            correction = f"{old_value} → {new_value}"

        return await self.log_action(
            action_type=ActionType.UPDATE,
            action_taken=f"Updated {entity_type}.{field_name}: {old_value} → {new_value}",
            entities_affected=[entity_id],
            correction=correction,
            interpretation=reason,
            external_api="notion",
        )

    async def log_delete(
        self,
        entity_id: str,
        entity_type: str,
        title: str,
        soft: bool = True,
    ) -> AuditEntry:
        """Log a delete action.

        Args:
            entity_id: Notion page ID of deleted entity
            entity_type: Type of entity
            title: Title of deleted entity
            soft: Whether this was a soft delete

        Returns:
            AuditEntry for the delete
        """
        delete_type = "Soft deleted" if soft else "Hard deleted"

        return await self.log_action(
            action_type=ActionType.DELETE,
            action_taken=f"{delete_type} {entity_type}: {title}",
            entities_affected=[entity_id],
            external_api="notion",
            include_undo_window=soft,
        )

    async def log_calendar_create(
        self,
        task_id: str,
        event_id: str,
        title: str,
        start_time: datetime,
    ) -> AuditEntry:
        """Log calendar event creation.

        Args:
            task_id: Notion task ID
            event_id: Google Calendar event ID
            title: Event title
            start_time: Event start time

        Returns:
            AuditEntry for the calendar create
        """
        idempotency_key = self.generate_idempotency_key(
            "calendar", task_id, start_time.date().isoformat()
        )

        return await self.log_action(
            action_type=ActionType.CALENDAR_CREATE,
            idempotency_key=idempotency_key,
            action_taken=f"Created calendar event: {title}",
            entities_affected=[task_id],
            external_api="google",
            external_resource_id=event_id,
            include_undo_window=True,
        )

    async def log_calendar_update(
        self,
        task_id: str,
        event_id: str,
        change_description: str,
    ) -> AuditEntry:
        """Log calendar event update.

        Args:
            task_id: Notion task ID
            event_id: Google Calendar event ID
            change_description: What was changed

        Returns:
            AuditEntry for the calendar update
        """
        return await self.log_action(
            action_type=ActionType.CALENDAR_UPDATE,
            action_taken=f"Updated calendar event: {change_description}",
            entities_affected=[task_id],
            external_api="google",
            external_resource_id=event_id,
        )

    async def log_briefing(
        self,
        chat_id: str,
        date: str,
        sections_included: list[str],
    ) -> AuditEntry:
        """Log morning briefing delivery.

        Args:
            chat_id: Telegram chat ID
            date: Date of briefing (YYYY-MM-DD)
            sections_included: Which sections were in the briefing

        Returns:
            AuditEntry for the briefing
        """
        idempotency_key = self.generate_idempotency_key("briefing", date, chat_id)

        return await self.log_action(
            action_type=ActionType.SEND,
            idempotency_key=idempotency_key,
            action_taken=f"Sent morning briefing ({', '.join(sections_included)})",
            external_api="telegram",
        )

    async def log_error(
        self,
        error_code: str,
        error_message: str,
        action_attempted: str,
        idempotency_key: str | None = None,
        input_text: str | None = None,
        retry_count: int = 0,
    ) -> AuditEntry:
        """Log an error.

        Args:
            error_code: Error code
            error_message: Error details
            action_attempted: What action was being attempted
            idempotency_key: Key for the failed action
            input_text: Original input if relevant
            retry_count: Number of retries attempted

        Returns:
            AuditEntry for the error
        """
        return await self.log_action(
            action_type=ActionType.ERROR,
            idempotency_key=idempotency_key,
            input_text=input_text,
            action_taken=f"Failed: {action_attempted}",
            error_code=error_code,
            error_message=error_message,
            retry_count=retry_count,
        )

    async def mark_undone(
        self,
        log_id: str,
    ) -> None:
        """Mark a log entry as undone.

        Args:
            log_id: Notion page ID of log entry
        """
        if not self.notion:
            return

        try:
            await self.notion._request(
                "PATCH",
                f"/pages/{log_id}",
                {
                    "properties": {
                        "undone": {"checkbox": True},
                    }
                },
            )
        except Exception as e:
            logger.warning(f"Failed to mark log entry as undone: {e}")

    async def query_log(
        self,
        action_type: ActionType | None = None,
        since: datetime | None = None,
        entity_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query audit log entries.

        Args:
            action_type: Filter by action type
            since: Only entries after this time
            entity_id: Filter by affected entity
            limit: Maximum results

        Returns:
            List of log entries from Notion
        """
        if not self.notion:
            return []

        filters = []

        if action_type:
            filters.append({
                "property": "action_type",
                "select": {"equals": action_type.value},
            })

        if since:
            filters.append({
                "property": "timestamp",
                "date": {"on_or_after": since.isoformat()},
            })

        if entity_id:
            filters.append({
                "property": "entities_affected",
                "rich_text": {"contains": entity_id},
            })

        query_filter = {"and": filters} if len(filters) > 1 else (filters[0] if filters else None)

        try:
            result = await self.notion._request(
                "POST",
                f"/databases/{settings.notion_log_db_id}/query",
                {
                    "filter": query_filter,
                    "page_size": limit,
                    "sorts": [{"property": "timestamp", "direction": "descending"}],
                } if query_filter else {
                    "page_size": limit,
                    "sorts": [{"property": "timestamp", "direction": "descending"}],
                },
            )
            results: list[dict[str, Any]] = result.get("results", [])
            return results
        except Exception as e:
            logger.exception(f"Failed to query log: {e}")
            return []


# Module-level singleton
_audit_logger: AuditLogger | None = None


def get_audit_logger(notion_client: Any | None = None) -> AuditLogger:
    """Get or create the audit logger singleton.

    Args:
        notion_client: Optional NotionClient to use

    Returns:
        AuditLogger instance
    """
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(notion_client)
    return _audit_logger


async def log_action(
    action_type: ActionType,
    **kwargs: Any,
) -> AuditEntry:
    """Convenience function to log an action.

    Args:
        action_type: Type of action
        **kwargs: Additional arguments for log_action

    Returns:
        AuditEntry for the action
    """
    logger = get_audit_logger()
    return await logger.log_action(action_type, **kwargs)


async def check_and_log_idempotency(
    idempotency_key: str,
) -> tuple[bool, AuditEntry | None]:
    """Check idempotency and log if duplicate.

    Args:
        idempotency_key: Key to check

    Returns:
        Tuple of (should_proceed, dedupe_entry)
        - If should_proceed is False, skip the action
        - dedupe_entry is the logged entry if duplicate
    """
    logger = get_audit_logger()
    result, existing = await logger.check_idempotency(idempotency_key)

    if result == DedupeResult.DUPLICATE:
        # AT-113: Log the dedupe event
        dedupe_entry = await logger.log_deduplicated(
            idempotency_key,
            existing.log_id if existing else None,
        )
        return False, dedupe_entry

    # NEW or RETRY - proceed with action
    return True, None
