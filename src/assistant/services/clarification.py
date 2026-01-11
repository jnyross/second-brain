"""Clarification service for low-confidence items.

Manages items that need human review due to low confidence scores.
Provides functionality for the /debrief command and morning briefing.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any

from assistant.config import settings
from assistant.notion import NotionClient
from assistant.notion.schemas import (
    InboxItem,
    InboxSource,
    Task,
    TaskSource,
    ActionType,
)

logger = logging.getLogger(__name__)


@dataclass
class UnclearItem:
    """An item that needs clarification."""

    id: str
    raw_input: str
    interpretation: Optional[str]
    confidence: int
    source: str
    timestamp: datetime
    voice_transcript: bool = False


@dataclass
class ClarificationResult:
    """Result of a clarification action."""

    item_id: str
    action: str  # "created_task", "dismissed", "clarified"
    task_id: Optional[str] = None
    message: str = ""


class ClarificationService:
    """Service for managing items needing clarification.

    Features:
    - Query items flagged for review
    - Present items for debrief
    - Create tasks from clarified items
    - Dismiss false positives
    """

    def __init__(self, notion: Optional[NotionClient] = None):
        self.notion = notion or (NotionClient() if settings.has_notion else None)

    async def get_unclear_items(self, limit: int = 10) -> list[UnclearItem]:
        """Get items that need clarification.

        Returns unprocessed inbox items with needs_clarification=True,
        sorted by most recent first.
        """
        if not self.notion:
            logger.warning("Notion not configured - cannot query unclear items")
            return []

        try:
            results = await self.notion.query_inbox(
                needs_clarification=True,
                processed=False,
                limit=limit,
            )

            items = []
            for result in results:
                props = result.get("properties", {})

                # Extract raw_input from rich_text
                raw_input = ""
                if raw_text := props.get("raw_input", {}).get("rich_text", []):
                    raw_input = raw_text[0].get("text", {}).get("content", "")

                # Extract interpretation
                interpretation = None
                if interp := props.get("interpretation", {}).get("rich_text", []):
                    interpretation = interp[0].get("text", {}).get("content", "")

                # Extract confidence
                confidence = props.get("confidence", {}).get("number", 0) or 0

                # Extract source
                source = props.get("source", {}).get("select", {}).get("name", "unknown")

                # Extract timestamp
                timestamp_str = props.get("timestamp", {}).get("date", {}).get("start")
                timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.utcnow()

                # Check if from voice
                voice_file = props.get("voice_file_id", {}).get("rich_text", [])
                voice_transcript = bool(voice_file)

                items.append(UnclearItem(
                    id=result["id"],
                    raw_input=raw_input,
                    interpretation=interpretation,
                    confidence=confidence,
                    source=source,
                    timestamp=timestamp,
                    voice_transcript=voice_transcript,
                ))

            return items

        except Exception as e:
            logger.exception(f"Failed to query unclear items: {e}")
            return []
        finally:
            if self.notion:
                await self.notion.close()

    async def get_unclear_count(self) -> int:
        """Get count of items needing clarification."""
        items = await self.get_unclear_items(limit=100)
        return len(items)

    async def create_task_from_item(
        self,
        item_id: str,
        title: str,
        due_date: Optional[datetime] = None,
        chat_id: Optional[str] = None,
    ) -> ClarificationResult:
        """Create a task from an unclear item after clarification.

        Args:
            item_id: Notion page ID of the inbox item
            title: Clarified task title
            due_date: Optional due date
            chat_id: Telegram chat ID for idempotency

        Returns:
            ClarificationResult with created task ID
        """
        if not self.notion:
            return ClarificationResult(
                item_id=item_id,
                action="error",
                message="Notion not configured",
            )

        try:
            # Create the task
            task = Task(
                title=title,
                due_date=due_date,
                source=TaskSource.MANUAL,
                source_inbox_item_id=item_id,
                confidence=100,  # User-clarified = high confidence
                created_by="user",
            )
            task_id = await self.notion.create_task(task)

            # Mark inbox item as processed
            await self.notion.mark_inbox_processed(item_id, task_id)

            # Log the clarification
            idempotency_key = f"clarify:{item_id}" if chat_id else None
            await self.notion.log_action(
                action_type=ActionType.CLASSIFY,
                idempotency_key=idempotency_key,
                input_text=title,
                action_taken=f"Created task from clarified inbox item",
                confidence=100,
                entities_affected=[task_id, item_id],
            )

            return ClarificationResult(
                item_id=item_id,
                action="created_task",
                task_id=task_id,
                message=f"Created task: {title}",
            )

        except Exception as e:
            logger.exception(f"Failed to create task from item: {e}")
            return ClarificationResult(
                item_id=item_id,
                action="error",
                message=str(e),
            )
        finally:
            if self.notion:
                await self.notion.close()

    async def dismiss_item(
        self,
        item_id: str,
        reason: Optional[str] = None,
    ) -> ClarificationResult:
        """Dismiss an unclear item as not actionable.

        Args:
            item_id: Notion page ID of the inbox item
            reason: Optional reason for dismissal

        Returns:
            ClarificationResult
        """
        if not self.notion:
            return ClarificationResult(
                item_id=item_id,
                action="error",
                message="Notion not configured",
            )

        try:
            # Mark as processed without creating task
            await self.notion.mark_inbox_processed(item_id)

            # Log the dismissal
            await self.notion.log_action(
                action_type=ActionType.CLASSIFY,
                input_text=reason or "Dismissed by user",
                action_taken="Dismissed unclear inbox item",
                entities_affected=[item_id],
            )

            return ClarificationResult(
                item_id=item_id,
                action="dismissed",
                message="Item dismissed",
            )

        except Exception as e:
            logger.exception(f"Failed to dismiss item: {e}")
            return ClarificationResult(
                item_id=item_id,
                action="error",
                message=str(e),
            )
        finally:
            if self.notion:
                await self.notion.close()

    def format_for_debrief(self, items: list[UnclearItem]) -> str:
        """Format unclear items for debrief message.

        Returns Telegram-friendly markdown listing items for review.
        """
        if not items:
            return "No items need clarification! You're all caught up."

        lines = [f"**{len(items)} item(s) need clarification:**\n"]

        for i, item in enumerate(items, 1):
            # Format timestamp
            time_str = item.timestamp.strftime("%I:%M %p")

            # Add voice indicator
            voice = " (voice)" if item.voice_transcript else ""

            # Add confidence indicator
            conf = f"[{item.confidence}%]"

            lines.append(f"{i}. \"{item.raw_input}\"{voice}")

            if item.interpretation:
                lines.append(f"   _Possibly: {item.interpretation}_")

            lines.append(f"   {conf} at {time_str}")
            lines.append("")

        lines.append("Reply with a number to clarify, or 'skip' to dismiss all.")

        return "\n".join(lines)


# Convenience functions


async def get_unclear_items(limit: int = 10) -> list[UnclearItem]:
    """Get items needing clarification."""
    service = ClarificationService()
    return await service.get_unclear_items(limit)


async def get_unclear_count() -> int:
    """Get count of items needing clarification."""
    service = ClarificationService()
    return await service.get_unclear_count()


async def format_debrief() -> str:
    """Get formatted debrief message."""
    service = ClarificationService()
    items = await service.get_unclear_items()
    return service.format_for_debrief(items)
