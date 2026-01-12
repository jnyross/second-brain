"""Correction handler service for Second Brain.

Handles user corrections like "Wrong, I said Tess not Jess" by:
1. Detecting correction patterns in messages
2. Tracking recently created tasks per chat for context
3. Extracting the intended correction
4. Updating affected records in Notion
5. Logging corrections for pattern learning

Per PRD Section 5.7 - Corrections:
- Immediate corrections update the affected record
- Pattern corrections (repeated similar corrections) are stored for learning
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from assistant.notion import NotionClient
from assistant.notion.schemas import ActionType

logger = logging.getLogger(__name__)


@dataclass
class RecentAction:
    """Tracks a recent action taken by the AI for potential correction."""

    action_type: str  # "task_created", "person_created", etc.
    entity_id: str  # Notion page ID
    title: str  # The title/name that was created
    timestamp: datetime = field(default_factory=datetime.utcnow)
    chat_id: str = ""
    message_id: str = ""

    def is_expired(self, max_age_minutes: int = 30) -> bool:
        """Check if this action is too old to be corrected."""
        return datetime.utcnow() - self.timestamp > timedelta(minutes=max_age_minutes)


@dataclass
class CorrectionResult:
    """Result of processing a correction."""

    is_correction: bool
    original_value: Optional[str] = None
    corrected_value: Optional[str] = None
    correction_type: Optional[str] = None  # "name", "title", "date", "person"
    entity_id: Optional[str] = None
    success: bool = False
    message: str = ""


# Patterns that indicate a correction is being made
CORRECTION_PATTERNS = [
    # Direct "wrong" statements
    re.compile(r"^wrong\b", re.IGNORECASE),
    re.compile(r"^that'?s wrong\b", re.IGNORECASE),
    re.compile(r"^that'?s not (right|correct)\b", re.IGNORECASE),
    re.compile(r"^no,?\s", re.IGNORECASE),
    re.compile(r"^incorrect\b", re.IGNORECASE),
    re.compile(r"^actually\b", re.IGNORECASE),
    re.compile(r"^not (?:that|this)\b", re.IGNORECASE),

    # "I said X not Y" patterns
    re.compile(r"i said\b", re.IGNORECASE),
    re.compile(r"i meant\b", re.IGNORECASE),
    re.compile(r"should (?:be|have been)\b", re.IGNORECASE),
    re.compile(r"(?:it'?s|it was|that was)\s+(\w+)\s+not\s+(\w+)", re.IGNORECASE),

    # Undo requests
    re.compile(r"^undo\b", re.IGNORECASE),
    re.compile(r"^cancel\s+(?:that|this|it)\b", re.IGNORECASE),
    re.compile(r"^delete\s+(?:that|this|it)\b", re.IGNORECASE),
]

# Patterns to extract the corrected value
# Match "I said X not Y" -> extracts X (correct) and Y (wrong)
CORRECTION_EXTRACTION_PATTERNS = [
    # "I said Tess not Jess" -> correct=Tess, wrong=Jess
    re.compile(r"i said\s+['\"]?([^'\"]+?)['\"]?\s+not\s+['\"]?([^'\"]+?)['\"]?(?:\s|$|\.)", re.IGNORECASE),

    # "I meant Tess not Jess"
    re.compile(r"i meant\s+['\"]?([^'\"]+?)['\"]?\s+not\s+['\"]?([^'\"]+?)['\"]?(?:\s|$|\.)", re.IGNORECASE),

    # "should be Tess not Jess"
    re.compile(r"should (?:be|have been)\s+['\"]?([^'\"]+?)['\"]?\s+not\s+['\"]?([^'\"]+?)['\"]?(?:\s|$|\.)", re.IGNORECASE),

    # "it's Tess not Jess" or "that was Tess not Jess"
    re.compile(r"(?:it'?s|it was|that'?s|that was)\s+['\"]?([^'\"]+?)['\"]?\s+not\s+['\"]?([^'\"]+?)['\"]?(?:\s|$|\.)", re.IGNORECASE),

    # "Wrong, I said Tess" - just extracts the correct value
    re.compile(r"wrong[,.]?\s+i said\s+['\"]?([^'\"]+?)['\"]?(?:\s|$|\.)", re.IGNORECASE),

    # "Wrong, it's Tess" - just extracts the correct value
    re.compile(r"wrong[,.]?\s+(?:it'?s|it was|that'?s|that was)\s+['\"]?([^'\"]+?)['\"]?(?:\s|$|\.)", re.IGNORECASE),

    # "change X to Y" pattern
    re.compile(r"change\s+['\"]?([^'\"]+?)['\"]?\s+to\s+['\"]?([^'\"]+?)['\"]?(?:\s|$|\.)", re.IGNORECASE),
]


class CorrectionHandler:
    """Handles user corrections to AI-created content.

    Maintains a per-chat history of recent actions for context.
    When a correction is detected, updates the affected record.
    """

    # Maximum number of recent actions to keep per chat
    MAX_RECENT_ACTIONS = 10

    # Maximum age of actions that can be corrected (in minutes)
    MAX_ACTION_AGE = 30

    def __init__(self, notion_client: Optional[NotionClient] = None):
        """Initialize the correction handler.

        Args:
            notion_client: Optional NotionClient instance. If not provided,
                          one will be created when needed.
        """
        self._notion = notion_client

        # Per-chat recent action history: chat_id -> list of RecentAction
        self._recent_actions: dict[str, list[RecentAction]] = defaultdict(list)

    @property
    def notion(self) -> NotionClient:
        """Get or create NotionClient instance."""
        if self._notion is None:
            self._notion = NotionClient()
        return self._notion

    def track_action(
        self,
        chat_id: str,
        message_id: str,
        action_type: str,
        entity_id: str,
        title: str,
    ) -> None:
        """Track a recent action for potential correction.

        Args:
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            action_type: Type of action (e.g., "task_created", "person_created")
            entity_id: Notion page ID of the created entity
            title: The title/name of the created entity
        """
        action = RecentAction(
            action_type=action_type,
            entity_id=entity_id,
            title=title,
            chat_id=chat_id,
            message_id=message_id,
        )

        # Add to chat's action list
        actions = self._recent_actions[chat_id]
        actions.append(action)

        # Prune old/expired actions
        self._recent_actions[chat_id] = [
            a for a in actions
            if not a.is_expired(self.MAX_ACTION_AGE)
        ][-self.MAX_RECENT_ACTIONS:]

        logger.debug(
            f"Tracked action: {action_type} '{title}' (id={entity_id}) "
            f"for chat {chat_id}"
        )

    def get_last_action(self, chat_id: str) -> Optional[RecentAction]:
        """Get the most recent action for a chat.

        Args:
            chat_id: Telegram chat ID

        Returns:
            Most recent non-expired action, or None
        """
        actions = self._recent_actions.get(chat_id, [])

        # Filter out expired actions and get the last one
        valid_actions = [
            a for a in actions
            if not a.is_expired(self.MAX_ACTION_AGE)
        ]

        return valid_actions[-1] if valid_actions else None

    def is_correction(self, text: str) -> bool:
        """Check if a message is a correction.

        Args:
            text: The user's message text

        Returns:
            True if the message appears to be a correction
        """
        text = text.strip()

        for pattern in CORRECTION_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def extract_correction(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract the corrected value from a correction message.

        Args:
            text: The user's correction message

        Returns:
            Tuple of (correct_value, wrong_value) or (None, None) if not extractable.
            wrong_value may be None even when correct_value is found.
        """
        text = text.strip()

        for pattern in CORRECTION_EXTRACTION_PATTERNS:
            match = pattern.search(text)
            if match:
                groups = match.groups()

                if len(groups) >= 2:
                    # Pattern matched both correct and wrong values
                    correct, wrong = groups[0].strip(), groups[1].strip()

                    # For "change X to Y" pattern, swap the order
                    if "change" in pattern.pattern.lower():
                        wrong, correct = correct, wrong

                    return correct, wrong
                elif len(groups) == 1:
                    # Pattern only matched the correct value
                    return groups[0].strip(), None

        return None, None

    async def process_correction(
        self,
        text: str,
        chat_id: str,
        message_id: str,
    ) -> CorrectionResult:
        """Process a potential correction message.

        Args:
            text: The user's message
            chat_id: Telegram chat ID
            message_id: Telegram message ID

        Returns:
            CorrectionResult with details of what was corrected (if anything)
        """
        # Check if this is a correction
        if not self.is_correction(text):
            return CorrectionResult(is_correction=False)

        # Get the last action for this chat
        last_action = self.get_last_action(chat_id)
        if not last_action:
            return CorrectionResult(
                is_correction=True,
                success=False,
                message="I don't have a recent action to correct. What would you like me to fix?",
            )

        # Extract what the correction should be
        correct_value, wrong_value = self.extract_correction(text)

        # Handle simple "undo" or "delete that"
        if self._is_undo_request(text):
            return await self._handle_undo(last_action, chat_id, message_id)

        # If we couldn't extract the correction, ask for clarification
        if not correct_value:
            return CorrectionResult(
                is_correction=True,
                success=False,
                message=(
                    f"I created \"{last_action.title}\" - what should it be instead? "
                    f"(Say something like 'I said X not {last_action.title}')"
                ),
            )

        # Apply the correction
        return await self._apply_correction(
            action=last_action,
            correct_value=correct_value,
            wrong_value=wrong_value,
            chat_id=chat_id,
            message_id=message_id,
        )

    def _is_undo_request(self, text: str) -> bool:
        """Check if the message is an undo/delete request."""
        text_lower = text.lower().strip()
        undo_patterns = [
            r"^undo\b",
            r"^cancel\s+(?:that|this|it)\b",
            r"^delete\s+(?:that|this|it)\b",
            r"^remove\s+(?:that|this|it)\b",
            r"^never\s*mind\b",
            r"^forget\s+(?:that|this|it)\b",
        ]

        for pattern in undo_patterns:
            if re.match(pattern, text_lower):
                return True
        return False

    async def _handle_undo(
        self,
        action: RecentAction,
        chat_id: str,
        message_id: str,
    ) -> CorrectionResult:
        """Handle an undo/delete request.

        Args:
            action: The action to undo
            chat_id: Telegram chat ID
            message_id: Telegram message ID

        Returns:
            CorrectionResult with undo details
        """
        try:
            # Soft delete the entity
            await self.notion.soft_delete(action.entity_id)

            # Log the undo action
            await self.notion.log_action(
                action_type=ActionType.DELETE,
                idempotency_key=f"undo:{chat_id}:{message_id}",
                input_text=f"Undo {action.action_type}",
                action_taken=f"Deleted: {action.title}",
                entities_affected=[action.entity_id],
            )

            # Remove from recent actions
            if chat_id in self._recent_actions:
                self._recent_actions[chat_id] = [
                    a for a in self._recent_actions[chat_id]
                    if a.entity_id != action.entity_id
                ]

            return CorrectionResult(
                is_correction=True,
                original_value=action.title,
                correction_type="undo",
                entity_id=action.entity_id,
                success=True,
                message=f"Done. Removed \"{action.title}\".",
            )

        except Exception as e:
            logger.exception(f"Failed to undo action: {e}")
            return CorrectionResult(
                is_correction=True,
                success=False,
                message=f"Sorry, I couldn't undo that. Please try again or edit directly in Notion.",
            )

    async def _apply_correction(
        self,
        action: RecentAction,
        correct_value: str,
        wrong_value: Optional[str],
        chat_id: str,
        message_id: str,
    ) -> CorrectionResult:
        """Apply a correction to an entity.

        Args:
            action: The action to correct
            correct_value: The value it should be changed to
            wrong_value: The original wrong value (for logging)
            chat_id: Telegram chat ID
            message_id: Telegram message ID

        Returns:
            CorrectionResult with correction details
        """
        try:
            original_value = action.title

            # Determine what type of entity we're correcting
            if action.action_type == "task_created":
                await self._update_task_title(action.entity_id, correct_value)
                entity_type = "task"
            elif action.action_type == "person_created":
                await self._update_person_name(action.entity_id, correct_value)
                entity_type = "person"
            elif action.action_type == "place_created":
                await self._update_place_name(action.entity_id, correct_value)
                entity_type = "place"
            elif action.action_type == "project_created":
                await self._update_project_name(action.entity_id, correct_value)
                entity_type = "project"
            else:
                # Generic title update
                await self._update_task_title(action.entity_id, correct_value)
                entity_type = "item"

            # Log the correction
            correction_note = (
                f"Changed from '{original_value}' to '{correct_value}'"
                if wrong_value
                else f"Changed to '{correct_value}'"
            )

            await self.notion.log_action(
                action_type=ActionType.UPDATE,
                idempotency_key=f"correction:{chat_id}:{message_id}",
                input_text=f"Correction: {correction_note}",
                action_taken=f"Updated {entity_type}: {original_value} → {correct_value}",
                entities_affected=[action.entity_id],
            )

            # Log specifically as a correction for pattern learning
            await self._log_correction(
                entity_id=action.entity_id,
                original_value=original_value,
                corrected_value=correct_value,
            )

            # Track this correction for pattern detection
            from assistant.services.patterns import add_correction as add_pattern_correction
            detected_patterns = add_pattern_correction(
                original_value=original_value,
                corrected_value=correct_value,
                entity_type=entity_type,
            )

            # If patterns detected, notify in message
            if detected_patterns:
                pattern = detected_patterns[0]
                return CorrectionResult(
                    is_correction=True,
                    original_value=original_value,
                    corrected_value=correct_value,
                    correction_type="title",
                    entity_id=action.entity_id,
                    success=True,
                    message=(
                        f"Fixed. Changed \"{original_value}\" to \"{correct_value}\".\n\n"
                        f"I've noticed you correct '{pattern.trigger}' to '{pattern.meaning}' "
                        f"frequently ({pattern.occurrences} times). I'll remember this!"
                    ),
                )

            # Update our tracked action with the new title
            action.title = correct_value

            return CorrectionResult(
                is_correction=True,
                original_value=original_value,
                corrected_value=correct_value,
                correction_type="title",
                entity_id=action.entity_id,
                success=True,
                message=f"Fixed. Changed \"{original_value}\" to \"{correct_value}\".",
            )

        except Exception as e:
            logger.exception(f"Failed to apply correction: {e}")
            return CorrectionResult(
                is_correction=True,
                success=False,
                message=f"Sorry, I couldn't make that correction. Please edit directly in Notion.",
            )

    async def _update_task_title(self, page_id: str, new_title: str) -> None:
        """Update a task's title in Notion."""
        await self.notion._request(
            "PATCH",
            f"/pages/{page_id}",
            {
                "properties": {
                    "title": {"title": [{"text": {"content": new_title}}]},
                    "last_modified_at": {"date": {"start": datetime.utcnow().isoformat()}},
                }
            },
        )

    async def _update_person_name(self, page_id: str, new_name: str) -> None:
        """Update a person's name in Notion."""
        await self.notion._request(
            "PATCH",
            f"/pages/{page_id}",
            {
                "properties": {
                    "name": {"title": [{"text": {"content": new_name}}]},
                }
            },
        )

    async def _update_place_name(self, page_id: str, new_name: str) -> None:
        """Update a place's name in Notion."""
        await self.notion._request(
            "PATCH",
            f"/pages/{page_id}",
            {
                "properties": {
                    "name": {"title": [{"text": {"content": new_name}}]},
                }
            },
        )

    async def _update_project_name(self, page_id: str, new_name: str) -> None:
        """Update a project's name in Notion."""
        await self.notion._request(
            "PATCH",
            f"/pages/{page_id}",
            {
                "properties": {
                    "name": {"title": [{"text": {"content": new_name}}]},
                }
            },
        )

    async def _log_correction(
        self,
        entity_id: str,
        original_value: str,
        corrected_value: str,
    ) -> None:
        """Log a correction for pattern learning.

        This creates a log entry specifically marked as a correction,
        which can be used by the pattern detection system (T-091).
        """
        # Create a log entry with the correction field populated
        from assistant.notion.schemas import LogEntry

        entry = LogEntry(
            action_type=ActionType.UPDATE,
            action_taken=f"Correction: {original_value} → {corrected_value}",
            entities_affected=[entity_id],
            correction=f"{original_value} → {corrected_value}",
            corrected_at=datetime.utcnow(),
        )

        await self.notion.create_log_entry(entry)

    async def close(self) -> None:
        """Close the Notion client connection."""
        if self._notion:
            await self._notion.close()


# Module-level convenience functions

_handler: Optional[CorrectionHandler] = None


def get_correction_handler() -> CorrectionHandler:
    """Get or create the global CorrectionHandler instance."""
    global _handler
    if _handler is None:
        _handler = CorrectionHandler()
    return _handler


def is_correction_message(text: str) -> bool:
    """Check if a message is a correction.

    Convenience function that uses the global handler.
    """
    return get_correction_handler().is_correction(text)


def track_created_task(
    chat_id: str,
    message_id: str,
    task_id: str,
    title: str,
) -> None:
    """Track a newly created task for potential correction.

    Convenience function that uses the global handler.
    """
    get_correction_handler().track_action(
        chat_id=chat_id,
        message_id=message_id,
        action_type="task_created",
        entity_id=task_id,
        title=title,
    )


async def process_correction(
    text: str,
    chat_id: str,
    message_id: str,
) -> CorrectionResult:
    """Process a potential correction message.

    Convenience function that uses the global handler.
    """
    return await get_correction_handler().process_correction(
        text=text,
        chat_id=chat_id,
        message_id=message_id,
    )
