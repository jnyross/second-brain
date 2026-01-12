"""Proactive nudge service for Second Brain.

Sends "Don't forget X" reminders proactively based on task due dates.
Per PRD Section 2.2 ("Tap on Shoulder" / Proactive Surfacing):
- Push relevant info at the right time
- Morning briefing handles daily overview
- Nudges handle timely reminders throughout the day

Nudge timing rules:
- Tasks due TODAY: Nudge at 2pm if not completed
- Tasks due TOMORROW: Nudge at 6pm evening before
- Overdue tasks: Nudge once per day until resolved
- High priority: More aggressive nudging

Deduplication:
- Each task+date combination gets ONE nudge per window
- Tracked in ~/.second-brain/nudges/sent.json
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import pytz

from assistant.config import settings
from assistant.notion import NotionClient

logger = logging.getLogger(__name__)


class NudgeType(Enum):
    """Types of proactive nudges."""

    DUE_TODAY = "due_today"  # Task due today, reminder in afternoon
    DUE_TOMORROW = "due_tomorrow"  # Task due tomorrow, evening heads-up
    OVERDUE = "overdue"  # Task past due date
    HIGH_PRIORITY = "high_priority"  # Urgent/high priority tasks


@dataclass
class NudgeCandidate:
    """A task that may need a nudge."""

    task_id: str
    title: str
    due_date: datetime
    priority: str | None
    nudge_type: NudgeType
    days_overdue: int = 0


@dataclass
class NudgeResult:
    """Result of sending a nudge."""

    success: bool
    task_id: str
    message: str
    nudge_type: NudgeType
    error: str | None = None


@dataclass
class NudgeReport:
    """Summary of a nudge run."""

    candidates_found: int = 0
    nudges_sent: int = 0
    nudges_skipped: int = 0  # Already nudged today
    nudges_failed: int = 0
    results: list[NudgeResult] = field(default_factory=list)

    @property
    def all_successful(self) -> bool:
        """Check if all attempted nudges succeeded."""
        return self.nudges_failed == 0 and self.nudges_sent > 0


# Nudge window hours (24h format)
NUDGE_WINDOW_DUE_TODAY_START = 14  # 2pm - nudge for tasks due today
NUDGE_WINDOW_DUE_TODAY_END = 20  # 8pm
NUDGE_WINDOW_DUE_TOMORROW_START = 18  # 6pm - heads up for tomorrow
NUDGE_WINDOW_DUE_TOMORROW_END = 21  # 9pm
NUDGE_WINDOW_OVERDUE_START = 9  # 9am - overdue reminders
NUDGE_WINDOW_OVERDUE_END = 12  # noon


def get_nudge_tracker_path() -> Path:
    """Get path to nudge tracking file."""
    data_dir = Path(settings.data_dir) / "nudges"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "sent.json"


def load_sent_nudges() -> dict[str, str]:
    """Load record of sent nudges.

    Returns:
        Dict mapping "task_id:date" to ISO timestamp when sent
    """
    path = get_nudge_tracker_path()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_sent_nudges(nudges: dict[str, str]) -> None:
    """Save record of sent nudges."""
    path = get_nudge_tracker_path()
    with open(path, "w") as f:
        json.dump(nudges, f, indent=2)


def has_been_nudged_today(task_id: str, nudge_type: NudgeType, now: datetime) -> bool:
    """Check if task was already nudged today for this type.

    Args:
        task_id: Notion task page ID
        nudge_type: Type of nudge
        now: Current datetime

    Returns:
        True if already nudged today for this type
    """
    sent = load_sent_nudges()
    today_str = now.strftime("%Y-%m-%d")
    key = f"{task_id}:{nudge_type.value}:{today_str}"
    return key in sent


def mark_nudge_sent(task_id: str, nudge_type: NudgeType, now: datetime) -> None:
    """Record that a nudge was sent.

    Args:
        task_id: Notion task page ID
        nudge_type: Type of nudge
        now: When the nudge was sent
    """
    sent = load_sent_nudges()
    today_str = now.strftime("%Y-%m-%d")
    key = f"{task_id}:{nudge_type.value}:{today_str}"
    sent[key] = now.isoformat()

    # Cleanup old entries (older than 7 days)
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    sent = {k: v for k, v in sent.items() if k.split(":")[2] >= cutoff}

    save_sent_nudges(sent)


def is_in_nudge_window(nudge_type: NudgeType, now: datetime) -> bool:
    """Check if current time is within the nudge window for this type.

    Args:
        nudge_type: Type of nudge
        now: Current datetime (timezone-aware)

    Returns:
        True if within the appropriate nudge window
    """
    hour = now.hour

    if nudge_type == NudgeType.DUE_TODAY:
        return NUDGE_WINDOW_DUE_TODAY_START <= hour < NUDGE_WINDOW_DUE_TODAY_END

    if nudge_type == NudgeType.DUE_TOMORROW:
        return NUDGE_WINDOW_DUE_TOMORROW_START <= hour < NUDGE_WINDOW_DUE_TOMORROW_END

    if nudge_type in (NudgeType.OVERDUE, NudgeType.HIGH_PRIORITY):
        # More flexible window for urgent items
        return NUDGE_WINDOW_OVERDUE_START <= hour < NUDGE_WINDOW_DUE_TODAY_END

    return False


def format_nudge_message(candidate: NudgeCandidate) -> str:
    """Format the nudge message for a task.

    Args:
        candidate: Task to nudge about

    Returns:
        Formatted message string
    """
    priority_prefix = ""
    if candidate.priority in ("urgent", "high"):
        priority_prefix = "Priority: "

    if candidate.nudge_type == NudgeType.OVERDUE:
        if candidate.days_overdue == 1:
            return f'Overdue: "{candidate.title}" was due yesterday'
        return f'Overdue ({candidate.days_overdue} days): "{candidate.title}"'

    if candidate.nudge_type == NudgeType.DUE_TODAY:
        return f'{priority_prefix}Don\'t forget: "{candidate.title}" is due today'

    if candidate.nudge_type == NudgeType.DUE_TOMORROW:
        return f'Heads up: "{candidate.title}" is due tomorrow'

    if candidate.nudge_type == NudgeType.HIGH_PRIORITY:
        return f'Urgent reminder: "{candidate.title}"'

    return f'Reminder: "{candidate.title}"'


class NudgeService:
    """Service for sending proactive task reminders.

    Queries Notion for tasks with upcoming due dates and sends
    appropriate reminders via Telegram based on timing rules.
    """

    def __init__(self, notion_client: NotionClient | None = None):
        """Initialize nudge service.

        Args:
            notion_client: Optional NotionClient instance
        """
        self.notion = (
            notion_client
            if notion_client is not None
            else (NotionClient() if settings.has_notion else None)
        )
        self.timezone = pytz.timezone(settings.user_timezone)

    async def get_nudge_candidates(self, now: datetime | None = None) -> list[NudgeCandidate]:
        """Get tasks that are candidates for nudging.

        Args:
            now: Current datetime (defaults to now in user timezone)

        Returns:
            List of tasks that should potentially be nudged
        """
        if not self.notion:
            return []

        now = now or datetime.now(self.timezone)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        day_after_tomorrow = today + timedelta(days=2)

        candidates: list[NudgeCandidate] = []

        try:
            # Get tasks due today (not completed)
            tasks_today = await self.notion.query_tasks(
                due_after=today,
                due_before=tomorrow,
                exclude_statuses=["done", "cancelled", "deleted"],
                limit=20,
            )

            for task in tasks_today:
                candidate = self._task_to_candidate(task, NudgeType.DUE_TODAY, now)
                if candidate:
                    candidates.append(candidate)

            # Get tasks due tomorrow (heads up)
            tasks_tomorrow = await self.notion.query_tasks(
                due_after=tomorrow,
                due_before=day_after_tomorrow,
                exclude_statuses=["done", "cancelled", "deleted"],
                limit=10,
            )

            for task in tasks_tomorrow:
                candidate = self._task_to_candidate(task, NudgeType.DUE_TOMORROW, now)
                if candidate:
                    candidates.append(candidate)

            # Get overdue tasks
            tasks_overdue = await self.notion.query_tasks(
                due_before=today,
                exclude_statuses=["done", "cancelled", "deleted"],
                limit=10,
            )

            for task in tasks_overdue:
                candidate = self._task_to_candidate(task, NudgeType.OVERDUE, now)
                if candidate:
                    # Calculate days overdue
                    if candidate.due_date:
                        due_date = (
                            candidate.due_date.date()
                            if hasattr(candidate.due_date, "date")
                            else candidate.due_date
                        )
                        today_date = today.date() if hasattr(today, "date") else today
                        candidate.days_overdue = (today_date - due_date).days

                    candidates.append(candidate)

        except Exception as e:
            logger.exception(f"Failed to fetch nudge candidates: {e}")

        return candidates

    def _task_to_candidate(
        self,
        task: dict[str, Any],
        nudge_type: NudgeType,
        now: datetime,
    ) -> NudgeCandidate | None:
        """Convert Notion task to NudgeCandidate.

        Args:
            task: Notion task response
            nudge_type: Type of nudge
            now: Current datetime

        Returns:
            NudgeCandidate or None if invalid
        """
        task_id = task.get("id")
        if not task_id:
            return None

        props = task.get("properties", {})

        # Extract title
        title_prop = props.get("title", {})
        title_list = title_prop.get("title", [])
        title = (
            title_list[0].get("text", {}).get("content", "Untitled") if title_list else "Untitled"
        )

        # Extract priority
        priority_prop = props.get("priority", {})
        priority_select = priority_prop.get("select")
        priority = priority_select.get("name") if priority_select else None

        # Extract due date
        due_prop = props.get("due_date", {})
        due_value = due_prop.get("date")
        due_date = None
        if due_value:
            start = due_value.get("start")
            if start:
                try:
                    if "T" in start:
                        due_date = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    else:
                        due_date = datetime.strptime(start, "%Y-%m-%d")
                        due_date = self.timezone.localize(due_date)
                except (ValueError, TypeError):
                    pass

        if not due_date:
            return None

        # Upgrade to HIGH_PRIORITY if urgent/high and due today
        effective_type = nudge_type
        if nudge_type == NudgeType.DUE_TODAY and priority in ("urgent", "high"):
            effective_type = NudgeType.HIGH_PRIORITY

        return NudgeCandidate(
            task_id=task_id,
            title=title,
            due_date=due_date,
            priority=priority,
            nudge_type=effective_type,
        )

    async def filter_candidates(
        self,
        candidates: list[NudgeCandidate],
        now: datetime | None = None,
    ) -> list[NudgeCandidate]:
        """Filter candidates to only those that should be nudged now.

        Applies:
        - Time window checks
        - Deduplication (already nudged today)

        Args:
            candidates: List of potential nudge candidates
            now: Current datetime

        Returns:
            Filtered list of candidates to nudge
        """
        now = now or datetime.now(self.timezone)
        filtered = []

        for candidate in candidates:
            # Check if in appropriate time window
            if not is_in_nudge_window(candidate.nudge_type, now):
                continue

            # Check if already nudged today for this type
            if has_been_nudged_today(candidate.task_id, candidate.nudge_type, now):
                continue

            filtered.append(candidate)

        return filtered

    async def send_nudges(
        self,
        candidates: list[NudgeCandidate],
        send_func: Any = None,
    ) -> NudgeReport:
        """Send nudges for candidates.

        Args:
            candidates: List of candidates to nudge
            send_func: Async function to send message (for testing).
                       Signature: async def send(chat_id: str, message: str)

        Returns:
            NudgeReport with results
        """
        now = datetime.now(self.timezone)
        report = NudgeReport(candidates_found=len(candidates))

        # Filter to only actionable candidates
        to_nudge = await self.filter_candidates(candidates, now)
        report.nudges_skipped = len(candidates) - len(to_nudge)

        for candidate in to_nudge:
            message = format_nudge_message(candidate)

            try:
                if send_func:
                    await send_func(settings.user_telegram_chat_id, message)
                else:
                    # Import here to avoid circular dependency
                    from assistant.telegram import SecondBrainBot

                    bot = SecondBrainBot()
                    await bot.send_message(settings.user_telegram_chat_id, message)
                    await bot.stop()

                # Mark as sent
                mark_nudge_sent(candidate.task_id, candidate.nudge_type, now)

                report.results.append(
                    NudgeResult(
                        success=True,
                        task_id=candidate.task_id,
                        message=message,
                        nudge_type=candidate.nudge_type,
                    )
                )
                report.nudges_sent += 1

            except Exception as e:
                logger.exception(f"Failed to send nudge for task {candidate.task_id}: {e}")
                report.results.append(
                    NudgeResult(
                        success=False,
                        task_id=candidate.task_id,
                        message=message,
                        nudge_type=candidate.nudge_type,
                        error=str(e),
                    )
                )
                report.nudges_failed += 1

        return report

    async def run(self, send_func: Any = None) -> NudgeReport:
        """Run the full nudge check and send cycle.

        Args:
            send_func: Optional send function for testing

        Returns:
            NudgeReport with results
        """
        try:
            candidates = await self.get_nudge_candidates()
            return await self.send_nudges(candidates, send_func)
        finally:
            if self.notion:
                await self.notion.close()


# Module-level convenience functions

_nudge_service: NudgeService | None = None


def get_nudge_service() -> NudgeService:
    """Get or create the global NudgeService instance."""
    global _nudge_service
    if _nudge_service is None:
        _nudge_service = NudgeService()
    return _nudge_service


async def run_nudges(send_func: Any = None) -> NudgeReport:
    """Run nudge check and send cycle.

    Args:
        send_func: Optional send function for testing

    Returns:
        NudgeReport with results
    """
    service = NudgeService()  # Fresh instance to avoid stale connections
    return await service.run(send_func)


async def get_pending_nudges() -> list[NudgeCandidate]:
    """Get tasks that are due for nudging.

    Returns:
        List of NudgeCandidate objects
    """
    service = NudgeService()
    try:
        candidates = await service.get_nudge_candidates()
        now = datetime.now(pytz.timezone(settings.user_timezone))
        return await service.filter_candidates(candidates, now)
    finally:
        if service.notion:
            await service.notion.close()
