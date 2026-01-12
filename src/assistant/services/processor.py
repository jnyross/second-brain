"""Message processor for Second Brain.

Handles the core message processing pipeline:
1. Parse input text to extract intent and entities
2. Apply stored patterns to correct likely errors (T-093)
3. Route to appropriate handler based on confidence
4. Create tasks/inbox items in Notion
"""

import logging
from dataclasses import dataclass, field

from assistant.config import settings
from assistant.notion import NotionClient
from assistant.notion.schemas import (
    ActionType,
    InboxItem,
    InboxSource,
    Person,
    Task,
    TaskSource,
)
from assistant.services.parser import ParsedIntent, Parser
from assistant.services.pattern_applicator import (
    AppliedPattern,
    PatternApplicationResult,
    PatternApplicator,
)

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    response: str
    task_id: str | None = None
    inbox_id: str | None = None
    confidence: int = 0
    needs_clarification: bool = False
    patterns_applied: list[AppliedPattern] = field(default_factory=list)


class MessageProcessor:
    def __init__(self) -> None:
        self.parser = Parser()
        self.notion = NotionClient() if settings.has_notion else None
        self.pattern_applicator = PatternApplicator(notion_client=self.notion)

    async def process(
        self,
        text: str,
        chat_id: str,
        message_id: str,
        voice_file_id: str | None = None,
        transcript_confidence: int | None = None,
        language: str | None = None,
    ) -> ProcessResult:
        """Process an incoming message.

        Args:
            text: Message text (or transcription for voice)
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            voice_file_id: Telegram voice file ID (for voice messages)
            transcript_confidence: Whisper confidence 0-100 (for voice messages)
            language: Detected language (for voice messages)

        Returns:
            ProcessResult with response and metadata
        """
        parsed = self.parser.parse(text)
        idempotency_key = f"telegram:{chat_id}:{message_id}"

        # T-093: Apply stored patterns before further processing
        pattern_result = await self._apply_patterns(parsed)

        # T-117: For low-confidence Whisper transcriptions, always flag for review
        # regardless of parser confidence
        force_low_confidence = transcript_confidence is not None and transcript_confidence < 80

        if parsed.confidence < settings.confidence_threshold or force_low_confidence:
            return await self._handle_low_confidence(
                parsed,
                chat_id,
                message_id,
                idempotency_key,
                pattern_result,
                voice_file_id=voice_file_id,
                transcript_confidence=transcript_confidence,
                language=language,
            )

        return await self._handle_high_confidence(
            parsed, chat_id, message_id, idempotency_key, pattern_result
        )

    async def _apply_patterns(self, parsed: ParsedIntent) -> PatternApplicationResult:
        """Apply stored patterns to parsed intent.

        T-093: Check patterns before classification and apply learned behaviors.

        Args:
            parsed: Parsed intent with extracted entities

        Returns:
            Pattern application result with original and corrected values
        """
        try:
            result = await self.pattern_applicator.apply_patterns(
                text=parsed.raw_text,
                people=parsed.people,
                places=parsed.places,
                title=parsed.title,
            )

            # Update parsed intent with corrected values
            if result.has_corrections:
                # Update people list with corrected names
                if result.corrected_people != result.original_people:
                    parsed.people = result.corrected_people
                    logger.info(
                        f"Pattern corrected people: "
                        f"{result.original_people} → {result.corrected_people}"
                    )

                # Update places list with corrected names
                if result.corrected_places != result.original_places:
                    parsed.places = result.corrected_places
                    logger.info(
                        f"Pattern corrected places: "
                        f"{result.original_places} → {result.corrected_places}"
                    )

                # Update title with corrected names
                if result.corrected_title != result.original_title:
                    parsed.title = result.corrected_title
                    logger.info(
                        f"Pattern corrected title: "
                        f"'{result.original_title}' → '{result.corrected_title}'"
                    )

            return result

        except Exception as e:
            logger.warning(f"Failed to apply patterns: {e}")
            # Return empty result on error - don't block processing
            return PatternApplicationResult(
                original_text=parsed.raw_text,
                original_people=parsed.people,
                original_places=parsed.places,
                original_title=parsed.title,
            )

    async def _handle_low_confidence(
        self,
        parsed: ParsedIntent,
        chat_id: str,
        message_id: str,
        idempotency_key: str,
        pattern_result: PatternApplicationResult,
        voice_file_id: str | None = None,
        transcript_confidence: int | None = None,
        language: str | None = None,
    ) -> ProcessResult:
        inbox_id = None

        # T-117: Determine source type based on whether this is a voice message
        is_voice = voice_file_id is not None
        source = InboxSource.TELEGRAM_VOICE if is_voice else InboxSource.TELEGRAM_TEXT

        if self.notion:
            try:
                item = InboxItem(
                    raw_input=parsed.raw_text,
                    source=source,
                    telegram_chat_id=chat_id,
                    telegram_message_id=message_id,
                    confidence=parsed.confidence,
                    needs_clarification=True,
                    interpretation=f"Possibly a {parsed.intent_type}: {parsed.title}",
                    # T-117: Include voice metadata for Whisper transcriptions
                    voice_file_id=voice_file_id,
                    transcript_confidence=transcript_confidence,
                    language=language,
                )
                inbox_id = await self.notion.create_inbox_item(item)

                # Include pattern info in log if patterns were applied
                action_taken = "Added to inbox (needs clarification)"
                if pattern_result.has_corrections:
                    action_taken += f" [Patterns applied: {pattern_result.summary()}]"

                await self.notion.log_action(
                    action_type=ActionType.CAPTURE,
                    idempotency_key=idempotency_key,
                    input_text=parsed.raw_text,
                    action_taken=action_taken,
                    confidence=parsed.confidence,
                    entities_affected=[inbox_id] if inbox_id else [],
                )
            except Exception:
                logger.exception("Failed to save to Notion")
                return ProcessResult(
                    response="Got it. Saved locally - will sync when Notion is available.",
                    confidence=parsed.confidence,
                    needs_clarification=True,
                    patterns_applied=pattern_result.patterns_applied,
                )
            finally:
                await self.notion.close()

        return ProcessResult(
            response=("Got it. I've added this to your inbox - we'll clarify in your next review."),
            inbox_id=inbox_id,
            confidence=parsed.confidence,
            needs_clarification=True,
            patterns_applied=pattern_result.patterns_applied,
        )

    async def _handle_high_confidence(
        self,
        parsed: ParsedIntent,
        chat_id: str,
        message_id: str,
        idempotency_key: str,
        pattern_result: PatternApplicationResult,
    ) -> ProcessResult:
        task_id = None
        people_linked: list[str] = []

        if self.notion:
            try:
                for person_name in parsed.people:
                    existing = await self.notion.query_people(name=person_name)
                    if existing:
                        people_linked.append(person_name)
                    else:
                        person = Person(name=person_name)
                        await self.notion.create_person(person)
                        people_linked.append(person_name)

                task = Task(
                    title=parsed.title,
                    due_date=parsed.due_date,
                    due_timezone=parsed.due_timezone,
                    source=TaskSource.TELEGRAM,
                    confidence=parsed.confidence,
                    created_by="ai",
                )
                task_id = await self.notion.create_task(task)

                # Include pattern info in log if patterns were applied
                action_taken = f"Created task: {parsed.title}"
                if pattern_result.has_corrections:
                    action_taken += f" [Patterns applied: {pattern_result.summary()}]"

                await self.notion.log_action(
                    action_type=ActionType.CREATE,
                    idempotency_key=idempotency_key,
                    input_text=parsed.raw_text,
                    action_taken=action_taken,
                    confidence=parsed.confidence,
                    entities_affected=[task_id] if task_id else [],
                )

                # Update pattern usage timestamps
                for applied in pattern_result.patterns_applied:
                    try:
                        await self.pattern_applicator.update_pattern_usage(applied.pattern_id)
                    except Exception as e:
                        logger.warning(f"Failed to update pattern usage: {e}")

            except Exception:
                logger.exception("Failed to create task in Notion")
                return ProcessResult(
                    response="Got it. Saved locally - will sync when Notion is available.",
                    confidence=parsed.confidence,
                    patterns_applied=pattern_result.patterns_applied,
                )
            finally:
                await self.notion.close()

        response = self._generate_response(parsed, people_linked, pattern_result)

        return ProcessResult(
            response=response,
            task_id=task_id,
            confidence=parsed.confidence,
            patterns_applied=pattern_result.patterns_applied,
        )

    def _generate_response(
        self,
        parsed: ParsedIntent,
        people: list[str],
        pattern_result: PatternApplicationResult,
    ) -> str:
        """Generate response message for high-confidence processing.

        Args:
            parsed: Parsed intent (may have been modified by patterns)
            people: List of people linked
            pattern_result: Result of pattern application

        Returns:
            Response message string
        """
        parts = [f"Got it. {parsed.title}"]

        if parsed.due_date:
            date_str = parsed.due_date.strftime("%A at %I:%M %p")
            parts.append(f", {date_str}")

        if people:
            if len(people) == 1:
                parts.append(f" with {people[0]}")
            else:
                parts.append(f" with {', '.join(people[:-1])} and {people[-1]}")

        if parsed.places:
            parts.append(f" at {parsed.places[0]}")

        parts.append(".")

        # T-093: Add note about pattern corrections if any were applied
        if pattern_result.has_corrections:
            # Only mention corrections for name changes (not internal pattern types)
            name_corrections = [
                p
                for p in pattern_result.patterns_applied
                if p.original_value.lower() != p.corrected_value.lower()
            ]
            if name_corrections:
                corrections_text = ", ".join(
                    f"'{p.original_value}' → '{p.corrected_value}'"
                    for p in name_corrections[:2]  # Limit to 2 for readability
                )
                parts.append(f"\n(I corrected {corrections_text} based on learned patterns)")

        return "".join(parts)
