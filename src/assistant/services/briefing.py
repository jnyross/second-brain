"""Morning briefing generator for Second Brain.

Generates a comprehensive morning briefing including:
- Today's calendar events (from Google Calendar)
- Emails needing attention (requires Gmail integration)
- Tasks due today
- Items needing clarification
- This week's upcoming tasks and deadlines
"""

import logging
from datetime import datetime, timedelta
from typing import Any
import pytz

from assistant.config import settings
from assistant.notion import NotionClient
from assistant.google.calendar import CalendarClient, CalendarEvent, get_calendar_client

logger = logging.getLogger(__name__)


class BriefingGenerator:
    """Generates morning briefings from Notion data.

    The briefing format follows PRD Section 5.2:
    - 📅 TODAY - Calendar events (placeholder until Google Calendar integration)
    - 📧 EMAIL - Emails needing attention (placeholder until Gmail integration)
    - ✅ DUE TODAY - Tasks due today
    - ⚠️ NEEDS CLARIFICATION - Flagged inbox items
    - 📊 THIS WEEK - Upcoming tasks and deadlines
    """

    def __init__(
        self,
        notion_client: NotionClient | None = None,
        calendar_client: CalendarClient | None = None,
    ):
        """Initialize briefing generator.

        Args:
            notion_client: Optional NotionClient instance. If not provided,
                           creates one if Notion is configured.
            calendar_client: Optional CalendarClient instance. If not provided,
                             uses the global singleton if Google OAuth is configured.
        """
        self.notion = notion_client if notion_client is not None else (
            NotionClient() if settings.has_notion else None
        )
        self.calendar = calendar_client if calendar_client is not None else get_calendar_client()
        self.timezone = pytz.timezone(settings.user_timezone)

    async def generate_morning_briefing(self) -> str:
        """Generate the complete morning briefing.

        Returns:
            Formatted briefing string ready to send via Telegram
        """
        now = datetime.now(self.timezone)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        week_end = today_start + timedelta(days=7)

        sections = []
        sections.append(f"Good morning! Here's your day for {now.strftime('%A, %B %d')}:\n")

        if self.notion:
            try:
                # 📅 TODAY section (calendar - placeholder)
                calendar_section = await self._generate_calendar_section()
                if calendar_section:
                    sections.append(calendar_section)

                # 📧 EMAIL section (placeholder until Gmail integration)
                email_section = await self._generate_email_section()
                if email_section:
                    sections.append(email_section)

                # ✅ DUE TODAY section
                tasks_today = await self._get_tasks_due_today(today_start, today_end)
                tasks_section = self._format_tasks_due_today(tasks_today)
                if tasks_section:
                    sections.append(tasks_section)

                # ⚠️ NEEDS CLARIFICATION section
                flagged = await self._get_flagged_items()
                flagged_section = self._format_flagged_items(flagged)
                if flagged_section:
                    sections.append(flagged_section)

                # 📊 THIS WEEK section
                upcoming_tasks = await self._get_tasks_this_week(today_end, week_end)
                week_section = self._format_this_week(upcoming_tasks, now)
                if week_section:
                    sections.append(week_section)

            except Exception as e:
                sections.append(f"*Could not fetch data from Notion: {str(e)}*\n")
            finally:
                if self.notion:
                    await self.notion.close()
        else:
            sections.append("*Notion not configured*\n")

        sections.append("Reply /debrief anytime to review together.")

        return "\n".join(sections)

    async def _generate_calendar_section(self) -> str | None:
        """Generate calendar section with today's events from Google Calendar.

        Returns:
            Formatted calendar section or None if not available or no events.
        """
        if not self.calendar or not self.calendar.is_authenticated():
            logger.debug("Google Calendar not authenticated - skipping calendar section")
            return None

        try:
            # Get today's events
            now = datetime.now(self.timezone)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

            events = await self.calendar.list_events(
                start_time=today_start,
                end_time=today_end,
                timezone=settings.user_timezone,
            )

            if not events:
                return None

            return self._format_calendar_events(events)

        except Exception as e:
            logger.exception(f"Failed to fetch calendar events: {e}")
            return None

    def _format_calendar_events(self, events: list[CalendarEvent]) -> str | None:
        """Format calendar events for the briefing.

        Args:
            events: List of CalendarEvent objects from Google Calendar

        Returns:
            Formatted calendar section string or None if no events
        """
        if not events:
            return None

        lines = ["📅 **TODAY**"]

        for event in events[:10]:  # Limit to 10 events
            # Format start time in user's timezone
            start_time = event.start_time
            if start_time.tzinfo is not None:
                # Convert to user's timezone for display
                try:
                    start_time = start_time.astimezone(self.timezone)
                except Exception:
                    pass

            # Check if this is an all-day event (starts at midnight with no time component)
            is_all_day = (
                start_time.hour == 0
                and start_time.minute == 0
                and event.end_time.hour == 0
                and event.end_time.minute == 0
            )

            if is_all_day:
                time_str = "All day"
            else:
                time_str = start_time.strftime("%H:%M")

            # Build event line
            line = f"• {time_str} - {event.title}"

            # Add location if present
            if event.location:
                # Truncate location if too long
                loc = event.location[:30] + "..." if len(event.location) > 30 else event.location
                line += f" ({loc})"

            lines.append(line)

        if len(events) > 10:
            lines.append(f"  _...and {len(events) - 10} more events_")

        lines.append("")
        return "\n".join(lines)

    async def _generate_email_section(self) -> str | None:
        """Generate email section.

        Returns:
            Formatted email section or None if not available.
            Currently returns None as Gmail integration (T-120) is pending.
        """
        # TODO: Implement when Gmail integration is complete (T-120)
        # This will query Gmail for emails needing attention
        return None

    async def _get_tasks_due_today(
        self,
        today_start: datetime,
        today_end: datetime,
    ) -> list[dict[str, Any]]:
        """Get tasks due today that are not completed or cancelled.

        Args:
            today_start: Start of today (midnight)
            today_end: End of today (23:59:59)

        Returns:
            List of task results from Notion
        """
        if not self.notion:
            return []

        return await self.notion.query_tasks(
            due_after=today_start,
            due_before=today_end,
            exclude_statuses=["done", "cancelled", "deleted"],
            limit=10,
        )

    async def _get_tasks_this_week(
        self,
        after_today: datetime,
        week_end: datetime,
    ) -> list[dict[str, Any]]:
        """Get tasks due this week (excluding today).

        Args:
            after_today: Start of tomorrow
            week_end: End of the 7-day period

        Returns:
            List of task results from Notion
        """
        if not self.notion:
            return []

        return await self.notion.query_tasks(
            due_after=after_today,
            due_before=week_end,
            exclude_statuses=["done", "cancelled", "deleted"],
            limit=10,
        )

    async def _get_flagged_items(self) -> list[dict[str, Any]]:
        """Get inbox items flagged for clarification.

        Returns:
            List of inbox items needing clarification
        """
        if not self.notion:
            return []

        return await self.notion.query_inbox(
            needs_clarification=True,
            processed=False,
            limit=10,
        )

    def _format_tasks_due_today(self, tasks: list[dict[str, Any]]) -> str | None:
        """Format tasks due today section.

        Args:
            tasks: List of task results from Notion

        Returns:
            Formatted section string or None if no tasks
        """
        if not tasks:
            return None

        lines = ["✅ **DUE TODAY**"]
        for task in tasks[:5]:
            title = self._extract_title(task)
            priority = self._extract_select(task, "priority")
            status = self._extract_select(task, "status")

            # Add priority indicator
            priority_icon = self._get_priority_icon(priority)
            status_suffix = f" [{status}]" if status and status not in ("todo", "inbox") else ""

            lines.append(f"• {priority_icon}{title}{status_suffix}")

        if len(tasks) > 5:
            lines.append(f"  _...and {len(tasks) - 5} more_")

        lines.append("")
        return "\n".join(lines)

    def _format_flagged_items(self, items: list[dict[str, Any]]) -> str | None:
        """Format flagged items section.

        Args:
            items: List of inbox items needing clarification

        Returns:
            Formatted section string or None if no flagged items
        """
        if not items:
            return None

        lines = [f"⚠️ **NEEDS CLARIFICATION** ({len(items)} item{'s' if len(items) != 1 else ''})"]
        for item in items[:3]:
            text = self._extract_text(item, "raw_input")
            interpretation = self._extract_text(item, "interpretation")

            # Show truncated raw input
            preview = text[:50] + "..." if len(text) > 50 else text
            lines.append(f"• \"{preview}\"")

            # If we have an interpretation, show it
            if interpretation:
                interp_preview = interpretation[:40] + "..." if len(interpretation) > 40 else interpretation
                lines.append(f"  _→ {interp_preview}_")

        if len(items) > 3:
            lines.append(f"  _...and {len(items) - 3} more_")

        lines.append("")
        return "\n".join(lines)

    def _format_this_week(
        self,
        tasks: list[dict[str, Any]],
        now: datetime,
    ) -> str | None:
        """Format this week's upcoming tasks section.

        Args:
            tasks: List of task results due this week
            now: Current datetime for calculating relative days

        Returns:
            Formatted section string or None if no upcoming tasks
        """
        if not tasks:
            return None

        lines = [f"📊 **THIS WEEK** ({len(tasks)} upcoming)"]

        # Group by day
        tasks_by_day: dict[str, list[tuple[str, str | None]]] = {}

        for task in tasks[:10]:
            title = self._extract_title(task)
            priority = self._extract_select(task, "priority")
            due_date = self._extract_date(task, "due_date")

            if due_date:
                # Format as weekday name
                day_label = self._format_relative_day(due_date, now)
                if day_label not in tasks_by_day:
                    tasks_by_day[day_label] = []
                tasks_by_day[day_label].append((title, priority))
            else:
                # No due date - shouldn't happen based on query but handle gracefully
                if "Undated" not in tasks_by_day:
                    tasks_by_day["Undated"] = []
                tasks_by_day["Undated"].append((title, priority))

        for day, day_tasks in tasks_by_day.items():
            lines.append(f"• **{day}:**")
            for title, priority in day_tasks[:3]:
                priority_icon = self._get_priority_icon(priority)
                lines.append(f"  - {priority_icon}{title}")
            if len(day_tasks) > 3:
                lines.append(f"  _...and {len(day_tasks) - 3} more_")

        lines.append("")
        return "\n".join(lines)

    def _extract_title(self, page: dict[str, Any]) -> str:
        """Extract title from a Notion page.

        Args:
            page: Notion page response

        Returns:
            Title string or "Untitled"
        """
        props = page.get("properties", {})
        title_prop = props.get("title", {})
        title_list = title_prop.get("title", [])
        if title_list:
            return title_list[0].get("text", {}).get("content", "Untitled")
        return "Untitled"

    def _extract_text(self, page: dict[str, Any], field: str) -> str:
        """Extract text from a rich_text property.

        Args:
            page: Notion page response
            field: Property name

        Returns:
            Text content or empty string
        """
        props = page.get("properties", {})
        field_prop = props.get(field, {})
        text_list = field_prop.get("rich_text", [])
        if text_list:
            return text_list[0].get("text", {}).get("content", "")
        return ""

    def _extract_select(self, page: dict[str, Any], field: str) -> str | None:
        """Extract value from a select property.

        Args:
            page: Notion page response
            field: Property name

        Returns:
            Selected option name or None
        """
        props = page.get("properties", {})
        field_prop = props.get(field, {})
        select_value = field_prop.get("select")
        if select_value:
            return select_value.get("name")
        return None

    def _extract_date(self, page: dict[str, Any], field: str) -> datetime | None:
        """Extract date from a date property.

        Args:
            page: Notion page response
            field: Property name

        Returns:
            Datetime object or None
        """
        props = page.get("properties", {})
        field_prop = props.get(field, {})
        date_value = field_prop.get("date")
        if date_value:
            start = date_value.get("start")
            if start:
                try:
                    # Handle both date and datetime formats
                    if "T" in start:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    else:
                        dt = datetime.strptime(start, "%Y-%m-%d")
                        dt = self.timezone.localize(dt)
                    return dt
                except (ValueError, TypeError):
                    pass
        return None

    def _get_priority_icon(self, priority: str | None) -> str:
        """Get priority indicator icon.

        Args:
            priority: Priority value (urgent, high, medium, low, someday)

        Returns:
            Icon string with trailing space, or empty string
        """
        icons = {
            "urgent": "🔴 ",
            "high": "🟠 ",
            "medium": "",
            "low": "",
            "someday": "💭 ",
        }
        return icons.get(priority or "", "")

    def _format_relative_day(self, date: datetime, now: datetime) -> str:
        """Format date as relative day name.

        Args:
            date: Target date
            now: Current datetime

        Returns:
            Formatted string like "Tomorrow", "Friday", "In 5 days"
        """
        today = now.date()
        target = date.date() if isinstance(date, datetime) else date

        delta = (target - today).days

        if delta == 0:
            return "Today"
        elif delta == 1:
            return "Tomorrow"
        elif delta < 7:
            return date.strftime("%A")  # e.g., "Friday"
        else:
            return f"In {delta} days"


async def generate_briefing() -> str:
    """Convenience function to generate a morning briefing.

    Returns:
        Formatted briefing string
    """
    generator = BriefingGenerator()
    return await generator.generate_morning_briefing()
