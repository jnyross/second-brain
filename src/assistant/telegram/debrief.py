"""Interactive debrief handler for Second Brain.

Implements AT-107: On-Demand Debrief
- /debrief command starts interactive review session
- Each unclear item presented for clarification
- User can clarify items, skip items, or end session
- All needs_clarification items addressed or skipped

Implements T-083: Interactive Clarification Flow (PRD 5.3)
- Parse clarification text for entities (people, places, dates)
- Link entities to Notion records
- Ask follow-up questions (due date)
- Handle "cancel" and "already done" patterns

Uses aiogram FSM (Finite State Machine) for multi-turn conversation flow.
"""

import logging
import re
from datetime import datetime
from typing import Any

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from assistant.services.clarification import ClarificationService, UnclearItem
from assistant.services.entities import EntityExtractor, ExtractedEntities

logger = logging.getLogger(__name__)

# Create router for debrief handlers
router = Router()


class DebriefStates(StatesGroup):
    """FSM states for debrief flow."""

    reviewing = State()  # Showing item to user
    awaiting_clarification = State()  # Waiting for user's clarification text
    awaiting_due_date = State()  # Waiting for due date after clarification


# Cancel patterns for detecting "cancel that", "already done", etc.
# Note: "done" alone is NOT a cancel - it ends the session
CANCEL_PATTERNS = [
    r"^cancel(\s+that)?$",
    r"^already\s+d(id|one)(\s+that)?$",
    r"^done\s+already$",  # Only "done already", not "done" alone
    r"^already\s+done?$",
    r"^nevermind$",
    r"^never\s*mind$",
    r"^forget(\s+it)?$",
    r"^not\s+needed$",
    r"^ignore(\s+this)?$",
]


def _is_cancel_command(text: str) -> bool:
    """Check if text is a cancel/dismiss command.

    Matches patterns like:
    - "cancel that"
    - "already done"
    - "done already"
    - "nevermind"
    - "forget it"
    """
    text_lower = text.lower().strip()
    for pattern in CANCEL_PATTERNS:
        if re.match(pattern, text_lower):
            return True
    return False


@router.message(Command("debrief"))
async def cmd_debrief(message: Message, state: FSMContext) -> None:
    """Handle /debrief command - start interactive review session.

    AT-107: Interactive review session starts when user sends /debrief.
    """
    chat_id = str(message.chat.id)

    # Get unclear items
    service = ClarificationService()
    items = await service.get_unclear_items(limit=20)

    if not items:
        await message.answer(
            "✅ **All clear!**\n\nNo items need clarification. You're all caught up!"
        )
        return

    # Store items in FSM state
    await state.update_data(
        items=[_item_to_dict(item) for item in items],
        current_index=0,
        chat_id=chat_id,
        stats={"clarified": 0, "skipped": 0, "dismissed": 0},
    )

    # Set state to reviewing
    await state.set_state(DebriefStates.reviewing)

    # Show intro and first item
    intro = (
        f"📋 **Debrief Session**\n\n"
        f"I have **{len(items)}** item(s) that need clarification.\n"
        f"Let's go through them one by one.\n\n"
        f"For each item you can:\n"
        f"• Type what you meant (to create a task)\n"
        f"• Type `skip` to dismiss this item\n"
        f"• Type `done` to end the session\n\n"
        f"---\n\n"
    )

    first_item_text = _format_item_for_review(items[0], 1, len(items))
    await message.answer(intro + first_item_text)


@router.message(DebriefStates.reviewing, F.text)
async def handle_debrief_response(message: Message, state: FSMContext) -> None:
    """Handle user response during debrief review.

    User can:
    - Type clarification text to create a task (entities parsed)
    - Type 'skip' to dismiss current item
    - Type 'done' to end session early
    - Type 'cancel', 'already done', etc. to dismiss as completed

    T-083: Enhanced interactive clarification flow:
    - Parse clarification for entities (people, places, dates)
    - Ask for due date if not specified
    - Handle cancel patterns
    """
    text = message.text or ""
    response = text.strip().lower()
    data = await state.get_data()

    items_data = data.get("items", [])
    current_index = data.get("current_index", 0)
    stats = data.get("stats", {"clarified": 0, "skipped": 0, "dismissed": 0})

    # Handle empty response
    if not response:
        await message.answer("Please type what you meant, 'skip' to dismiss, or 'done' to end.")
        return

    # Get current item
    if current_index >= len(items_data):
        await _end_debrief_session(message, state, stats)
        return

    current_item = _dict_to_item(items_data[current_index])

    # Handle 'done' command
    if response == "done":
        await _end_debrief_session(message, state, stats)
        return

    # Handle 'skip' command
    if response == "skip":
        # Dismiss the item
        service = ClarificationService()
        await service.dismiss_item(current_item.id, reason="Skipped in debrief")
        stats["skipped"] += 1

        await message.answer(f"⏭️ Skipped item {current_index + 1}.")

        # Move to next item
        await _advance_to_next_item(message, state, items_data, current_index + 1, stats)
        return

    # Handle cancel patterns ("cancel that", "already done", etc.)
    if _is_cancel_command(response):
        service = ClarificationService()
        await service.dismiss_item(
            current_item.id, reason="Cancelled by user - already done or not needed"
        )
        stats["skipped"] += 1

        await message.answer("✓ Removed from inbox.")

        # Move to next item
        await _advance_to_next_item(message, state, items_data, current_index + 1, stats)
        return

    # Handle clarification - parse for entities and create task
    # Use the original case for the task title
    task_title = (message.text or "").strip()

    # Parse clarification text for entities (T-083)
    extractor = EntityExtractor()
    entities = extractor.extract(task_title)

    # Check if due date was extracted
    due_date = None
    if entities.dates:
        due_date = entities.dates[0].datetime_value

    # If no date and clarification looks actionable, ask for due date
    if not due_date and _should_ask_for_due_date(task_title):
        # Store pending task info and ask for due date
        await state.update_data(
            pending_task_title=task_title,
            pending_item_id=current_item.id,
            pending_entities=_entities_to_dict(entities),
        )
        await state.set_state(DebriefStates.awaiting_due_date)
        await message.answer(
            f"📝 Got it: **{task_title}**\n\n"
            f"When is it due?\n"
            f"_(Type a date like 'tomorrow', 'Friday', or 'skip' for no due date)_"
        )
        return

    # Create task with parsed entities
    await _create_task_with_entities(
        message=message,
        state=state,
        item_id=current_item.id,
        title=task_title,
        due_date=due_date,
        entities=entities,
        chat_id=data.get("chat_id"),
        items_data=items_data,
        current_index=current_index,
        stats=stats,
    )


@router.message(DebriefStates.awaiting_due_date, F.text)
async def handle_due_date_response(message: Message, state: FSMContext) -> None:
    """Handle due date response after clarification.

    T-083: Follow-up question for due date.
    User can:
    - Type a date ('tomorrow', 'Friday', '2024-01-15')
    - Type 'skip' or 'no' to create task without due date
    - Type 'cancel' to cancel task creation
    """
    response = (message.text or "").strip().lower()
    data = await state.get_data()

    pending_title = data.get("pending_task_title")
    pending_item_id = data.get("pending_item_id")
    pending_entities_dict = data.get("pending_entities", {})

    if not pending_title or not pending_item_id:
        # Something went wrong, return to reviewing state
        await state.set_state(DebriefStates.reviewing)
        await message.answer("⚠️ Something went wrong. Let's continue.")
        return

    # Handle cancel
    if response in ("cancel", "nevermind", "back"):
        # Clear pending and return to reviewing
        await state.update_data(
            pending_task_title=None,
            pending_item_id=None,
            pending_entities=None,
        )
        await state.set_state(DebriefStates.reviewing)
        await message.answer(
            "OK, let's try again.\n\n"
            + _format_item_for_review(
                _dict_to_item(data["items"][data["current_index"]]),
                data["current_index"] + 1,
                len(data["items"]),
            )
        )
        return

    # Handle skip (no due date)
    due_date = None
    if response not in ("skip", "no", "none", "no due date"):
        # Try to parse the date
        extractor = EntityExtractor()
        date_entities = extractor.extract_dates((message.text or "").strip())
        if date_entities:
            due_date = date_entities[0].datetime_value
        else:
            # Couldn't parse - ask again or proceed without
            await message.answer(
                "I couldn't understand that date. Creating task without due date.\n"
                "_(You can update the date in Notion)_"
            )

    # Restore entities from dict
    entities = _dict_to_entities(pending_entities_dict)

    # Get current session data
    items_data = data.get("items", [])
    current_index = data.get("current_index", 0)
    stats = data.get("stats", {"clarified": 0, "skipped": 0, "dismissed": 0})

    # Clear pending data
    await state.update_data(
        pending_task_title=None,
        pending_item_id=None,
        pending_entities=None,
    )

    # Return to reviewing state before creating task
    await state.set_state(DebriefStates.reviewing)

    # Create the task
    await _create_task_with_entities(
        message=message,
        state=state,
        item_id=pending_item_id,
        title=pending_title,
        due_date=due_date,
        entities=entities,
        chat_id=data.get("chat_id"),
        items_data=items_data,
        current_index=current_index,
        stats=stats,
    )


async def _create_task_with_entities(
    message: Message,
    state: FSMContext,
    item_id: str,
    title: str,
    due_date: datetime | None,
    entities: ExtractedEntities,
    chat_id: str | None,
    items_data: list[dict],
    current_index: int,
    stats: dict,
) -> None:
    """Create task with linked entities and advance to next item.

    T-083: Entity linking for tasks created during debrief.
    """
    service = ClarificationService()

    # Build message components
    entity_summary = _format_entity_summary(entities)

    result = await service.create_task_from_item(
        item_id=item_id,
        title=title,
        due_date=due_date,
        chat_id=chat_id,
        # Pass entities for linking (will be handled by ClarificationService)
        people_names=[p.name for p in entities.people] if entities.people else None,
        place_names=[p.name for p in entities.places] if entities.places else None,
    )

    if result.action == "created_task":
        stats["clarified"] += 1

        # Build confirmation message
        confirmation_parts = [f"✅ Created task: **{title}**"]

        if due_date:
            confirmation_parts.append(f"📅 Due: {_format_due_date(due_date)}")

        if entity_summary:
            confirmation_parts.append(entity_summary)

        await message.answer("\n".join(confirmation_parts))
    else:
        await message.answer(f"⚠️ Couldn't create task: {result.message}\nLet's continue...")

    # Move to next item
    await _advance_to_next_item(message, state, items_data, current_index + 1, stats)


async def _advance_to_next_item(
    message: Message,
    state: FSMContext,
    items_data: list[dict],
    next_index: int,
    stats: dict,
) -> None:
    """Advance to the next item or end session if done."""
    if next_index >= len(items_data):
        await _end_debrief_session(message, state, stats)
        return

    # Update state
    await state.update_data(current_index=next_index, stats=stats)

    # Show next item
    next_item = _dict_to_item(items_data[next_index])
    item_text = _format_item_for_review(next_item, next_index + 1, len(items_data))

    await message.answer(item_text)


async def _end_debrief_session(message: Message, state: FSMContext, stats: dict) -> None:
    """End the debrief session with summary."""
    await state.clear()

    clarified = stats.get("clarified", 0)
    skipped = stats.get("skipped", 0)
    total = clarified + skipped

    if total == 0:
        await message.answer("✅ Debrief session ended.")
        return

    summary_lines = ["📊 **Debrief Complete**\n"]

    if clarified > 0:
        summary_lines.append(f"✅ {clarified} task(s) created")

    if skipped > 0:
        summary_lines.append(f"⏭️ {skipped} item(s) skipped")

    remaining = await _get_remaining_count()
    if remaining > 0:
        summary_lines.append(f"\n📌 {remaining} item(s) still need review.")
        summary_lines.append("Run /debrief again to continue.")
    else:
        summary_lines.append("\n🎉 All items have been reviewed!")

    await message.answer("\n".join(summary_lines))


def _format_item_for_review(item: UnclearItem, index: int, total: int) -> str:
    """Format an unclear item for presentation to user.

    Format:
    📝 Item 1 of 5

    You said: "that thing for Mike's project"
    (voice) [60%]

    What did you mean?
    """
    lines = [f"📝 **Item {index} of {total}**\n"]

    # Show original input
    lines.append(f'You said: "{item.raw_input}"')

    # Add voice indicator and confidence
    indicators = []
    if item.voice_transcript:
        indicators.append("🎤 voice")
    indicators.append(f"{item.confidence}% confidence")
    lines.append(f"_({', '.join(indicators)})_")

    # Show AI interpretation if available
    if item.interpretation:
        lines.append(f"\nI thought: _{item.interpretation}_")

    lines.append("\n**What did you mean?**")
    lines.append("_(Type the task, 'skip' to dismiss, or 'done' to end)_")

    return "\n".join(lines)


def _item_to_dict(item: UnclearItem) -> dict:
    """Convert UnclearItem to dict for FSM storage."""
    return {
        "id": item.id,
        "raw_input": item.raw_input,
        "interpretation": item.interpretation,
        "confidence": item.confidence,
        "source": item.source,
        "timestamp": item.timestamp.isoformat(),
        "voice_transcript": item.voice_transcript,
    }


def _dict_to_item(data: dict) -> UnclearItem:
    """Convert dict back to UnclearItem from FSM storage."""
    from datetime import datetime

    return UnclearItem(
        id=data["id"],
        raw_input=data["raw_input"],
        interpretation=data.get("interpretation"),
        confidence=data["confidence"],
        source=data["source"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
        voice_transcript=data.get("voice_transcript", False),
    )


async def _get_remaining_count() -> int:
    """Get count of remaining unclear items."""
    service = ClarificationService()
    return await service.get_unclear_count()


def _should_ask_for_due_date(title: str) -> bool:
    """Determine if we should ask for due date.

    Ask for due date if the task looks actionable but doesn't have a date.
    Skip for general notes or ongoing tasks.

    T-083: Follow-up question logic.
    """
    # Words that suggest a specific action (should ask for due date)
    action_words = [
        "send",
        "email",
        "call",
        "meet",
        "buy",
        "book",
        "schedule",
        "finish",
        "complete",
        "submit",
        "review",
        "prepare",
        "write",
        "pay",
        "order",
        "pick up",
        "drop off",
        "deliver",
        "remind",
    ]

    # Words that suggest general notes (don't ask for due date)
    note_words = [
        "remember",
        "idea",
        "note",
        "thought",
        "maybe",
        "consider",
        "someday",
        "when possible",
        "eventually",
        "later",
    ]

    title_lower = title.lower()

    # Don't ask for notes or vague items
    for word in note_words:
        if word in title_lower:
            return False

    # Ask for actionable items
    for word in action_words:
        if word in title_lower:
            return True

    # Default: don't ask (user can set date in Notion)
    return False


def _entities_to_dict(entities: ExtractedEntities) -> dict:
    """Convert ExtractedEntities to dict for FSM storage.

    T-083: Entity serialization for multi-turn clarification.
    """
    return {
        "people": [
            {"name": p.name, "confidence": p.confidence, "context": p.context}
            for p in entities.people
        ],
        "places": [
            {"name": p.name, "confidence": p.confidence, "context": p.context}
            for p in entities.places
        ],
        "dates": [
            {
                "datetime_value": d.datetime_value.isoformat(),
                "confidence": d.confidence,
                "original_text": d.original_text,
            }
            for d in entities.dates
        ],
        "raw_text": entities.raw_text,
    }


def _dict_to_entities(data: dict) -> ExtractedEntities:
    """Convert dict back to ExtractedEntities from FSM storage.

    T-083: Entity deserialization for multi-turn clarification.
    """
    from assistant.services.entities import (
        ExtractedDate,
        ExtractedEntities,
        ExtractedPerson,
        ExtractedPlace,
    )

    if not data:
        return ExtractedEntities()

    people = [
        ExtractedPerson(name=p["name"], confidence=p["confidence"], context=p.get("context", ""))
        for p in data.get("people", [])
    ]

    places = [
        ExtractedPlace(name=p["name"], confidence=p["confidence"], context=p.get("context", ""))
        for p in data.get("places", [])
    ]

    dates = []
    for d in data.get("dates", []):
        dt_value = datetime.fromisoformat(d["datetime_value"])
        dates.append(
            ExtractedDate(
                datetime_value=dt_value,
                confidence=d["confidence"],
                original_text=d["original_text"],
            )
        )

    return ExtractedEntities(
        people=people,
        places=places,
        dates=dates,
        raw_text=data.get("raw_text", ""),
    )


def _format_entity_summary(entities: ExtractedEntities) -> str:
    """Format extracted entities for display.

    T-083: Show linked entities in task confirmation.

    Examples:
    - "👤 with Mike"
    - "📍 at Starbucks"
    - "👤 with Mike 📍 at Starbucks"
    """
    parts = []

    if entities.people:
        names = [p.name for p in entities.people]
        if len(names) == 1:
            parts.append(f"👤 with {names[0]}")
        else:
            parts.append(f"👤 with {', '.join(names)}")

    if entities.places:
        names = [p.name for p in entities.places]
        parts.append(f"📍 at {', '.join(names)}")

    return " ".join(parts)


def _format_due_date(due_date: datetime) -> str:
    """Format due date for display.

    Shows relative time for nearby dates, absolute for distant.
    """
    now = datetime.now(due_date.tzinfo) if due_date.tzinfo else datetime.now()
    delta = (due_date.date() - now.date()).days

    if delta == 0:
        return "Today"
    elif delta == 1:
        return "Tomorrow"
    elif delta < 7:
        return due_date.strftime("%A")  # Weekday name
    else:
        return due_date.strftime("%B %d")  # "January 15"


def setup_debrief_handlers(dp: Dispatcher) -> None:
    """Set up debrief handlers on the dispatcher."""
    dp.include_router(router)
