import logging
from dataclasses import dataclass
from datetime import datetime

from assistant.config import settings
from assistant.notion import NotionClient
from assistant.notion.schemas import (
    InboxItem,
    InboxSource,
    Task,
    TaskSource,
    TaskPriority,
    Person,
    ActionType,
)
from assistant.services.parser import Parser, ParsedIntent

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    response: str
    task_id: str | None = None
    inbox_id: str | None = None
    confidence: int = 0
    needs_clarification: bool = False


class MessageProcessor:
    def __init__(self):
        self.parser = Parser()
        self.notion = NotionClient() if settings.has_notion else None

    async def process(
        self,
        text: str,
        chat_id: str,
        message_id: str,
    ) -> ProcessResult:
        parsed = self.parser.parse(text)
        idempotency_key = f"telegram:{chat_id}:{message_id}"

        if parsed.confidence < settings.confidence_threshold:
            return await self._handle_low_confidence(parsed, chat_id, message_id, idempotency_key)

        return await self._handle_high_confidence(parsed, chat_id, message_id, idempotency_key)

    async def _handle_low_confidence(
        self,
        parsed: ParsedIntent,
        chat_id: str,
        message_id: str,
        idempotency_key: str,
    ) -> ProcessResult:
        inbox_id = None

        if self.notion:
            try:
                item = InboxItem(
                    raw_input=parsed.raw_text,
                    source=InboxSource.TELEGRAM_TEXT,
                    telegram_chat_id=chat_id,
                    telegram_message_id=message_id,
                    confidence=parsed.confidence,
                    needs_clarification=True,
                    interpretation=f"Possibly a {parsed.intent_type}: {parsed.title}",
                )
                inbox_id = await self.notion.create_inbox_item(item)

                await self.notion.log_action(
                    action_type=ActionType.CAPTURE,
                    idempotency_key=idempotency_key,
                    input_text=parsed.raw_text,
                    action_taken="Added to inbox (needs clarification)",
                    confidence=parsed.confidence,
                    entities_affected=[inbox_id] if inbox_id else [],
                )
            except Exception as e:
                logger.exception("Failed to save to Notion")
                return ProcessResult(
                    response=f"Got it. Saved locally - will sync when Notion is available.",
                    confidence=parsed.confidence,
                    needs_clarification=True,
                )
            finally:
                await self.notion.close()

        return ProcessResult(
            response=(
                f"Got it. I've added this to your inbox - "
                f"we'll clarify in your next review."
            ),
            inbox_id=inbox_id,
            confidence=parsed.confidence,
            needs_clarification=True,
        )

    async def _handle_high_confidence(
        self,
        parsed: ParsedIntent,
        chat_id: str,
        message_id: str,
        idempotency_key: str,
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

                await self.notion.log_action(
                    action_type=ActionType.CREATE,
                    idempotency_key=idempotency_key,
                    input_text=parsed.raw_text,
                    action_taken=f"Created task: {parsed.title}",
                    confidence=parsed.confidence,
                    entities_affected=[task_id] if task_id else [],
                )
            except Exception as e:
                logger.exception("Failed to create task in Notion")
                return ProcessResult(
                    response="Got it. Saved locally - will sync when Notion is available.",
                    confidence=parsed.confidence,
                )
            finally:
                await self.notion.close()

        response = self._generate_response(parsed, people_linked)

        return ProcessResult(
            response=response,
            task_id=task_id,
            confidence=parsed.confidence,
        )

    def _generate_response(self, parsed: ParsedIntent, people: list[str]) -> str:
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

        return "".join(parts)
