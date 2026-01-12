"""Interactive debrief handler for Second Brain.

Implements AT-107: On-Demand Debrief
- /debrief command starts interactive review session
- Each unclear item presented for clarification
- User can clarify items, skip items, or end session
- All needs_clarification items addressed or skipped

Uses aiogram FSM (Finite State Machine) for multi-turn conversation flow.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from assistant.services.clarification import ClarificationService, UnclearItem

logger = logging.getLogger(__name__)

# Create router for debrief handlers
router = Router()


class DebriefStates(StatesGroup):
    """FSM states for debrief flow."""

    reviewing = State()  # Showing item to user
    awaiting_clarification = State()  # Waiting for user's clarification text


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
            "✅ **All clear!**\n\n"
            "No items need clarification. You're all caught up!"
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
    - Type clarification text to create a task
    - Type 'skip' to dismiss current item
    - Type 'done' to end session early
    """
    response = message.text.strip().lower()
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

    # Handle clarification - create task with user's clarification text
    # Use the original case for the task title
    task_title = message.text.strip()

    service = ClarificationService()
    result = await service.create_task_from_item(
        item_id=current_item.id,
        title=task_title,
        chat_id=data.get("chat_id"),
    )

    if result.action == "created_task":
        stats["clarified"] += 1
        await message.answer(
            f"✅ Created task: **{task_title}**\n"
        )
    else:
        await message.answer(
            f"⚠️ Couldn't create task: {result.message}\n"
            f"Let's continue..."
        )

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
    lines.append(f"You said: \"{item.raw_input}\"")

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


def setup_debrief_handlers(dp) -> None:
    """Set up debrief handlers on the dispatcher."""
    dp.include_router(router)
