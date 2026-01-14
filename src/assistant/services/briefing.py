"""Morning briefing generator for Second Brain.

Generates a comprehensive morning briefing including:
- Today's calendar events (from Google Calendar) with travel times
- Emails needing attention (requires Gmail integration)
- Tasks due today with departure time suggestions
- Items needing clarification
- This week's upcoming tasks and deadlines
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytz
from assistant.config import settings
from assistant.google.calendar import CalendarClient, CalendarEvent, get_calendar_client
from assistant.google.gmail import EmailMessage, GmailClient, get_gmail_client
from assistant.google.maps import MapsClient, TravelTime
from assistant.notion import NotionClient

logger = logging.getLogger(__name__)


@dataclass
class TravelInfo:
    """Travel time information for a task or event."""

    leave_by: datetime
    travel_time: TravelTime
    from_location: str
    to_location: str

    def format_departure(self, timezone: Any) -> str:
        """Format departure time as 'Leave by HH:MM (X min)'."""
        leave_local = self.leave_by.astimezone(timezone)
        duration = self.travel_time.format_duration(include_traffic=True)
        return f"Leave by {leave_local.strftime('%H:%M')} ({duration})"


class BriefingGenerator:
    """Generates morning briefings from Notion data.

    The briefing format follows PRD Section 5.2:
    - 📅 TODAY - Calendar events with travel time estimates
    - 📧 EMAIL - Emails needing attention
    - ✅ DUE TODAY - Tasks due today with departure suggestions
    - ⚠️ NEEDS CLARIFICATION - Flagged inbox items
    - 📊 THIS WEEK - Upcoming tasks and deadlines
    """

    def __init__(
        self,
        notion_client: NotionClient | None = None,
        calendar_client: CalendarClient | None = None,
        gmail_client: GmailClient | None = None,
        maps_client: MapsClient | None = None,
    ):
        """Initialize briefing generator.

        Args:
            notion_client: Optional NotionClient instance. If not provided,
                           creates one if Notion is configured.
            calendar_client: Optional CalendarClient instance. If not provided,
                             uses the global singleton if Google OAuth is configured.
            gmail_client: Optional GmailClient instance. If not provided,
                          uses the global singleton if Google OAuth is configured.
            maps_client: Optional MapsClient instance for travel time calculations.
                         If not provided, creates one if Maps API is configured.
        """
        self.notion = (
            notion_client
            if notion_client is not None
            else (NotionClient() if settings.has_notion else None)
        )
        self.calendar = calendar_client if calendar_client is not None else get_calendar_client()
        self.gmail = gmail_client if gmail_client is not None else get_gmail_client()
        self.maps = (
            maps_client
            if maps_client is not None
            else (MapsClient() if settings.google_maps_api_key else None)
        )
        self.timezone = pytz.timezone(settings.user_timezone)
        self.home_address = settings.user_home_address

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

                # 📧 EMAIL section (from Gmail - needs response)
                email_section = await self._generate_email_section()
                if email_section:
                    sections.append(email_section)

                # 🎯 FLAGGED EMAIL section (from Notion - LLM-analyzed important emails)
                analyzed_email_section = await self._generate_analyzed_email_section()
                if analyzed_email_section:
                    sections.append(analyzed_email_section)

                # ✅ DUE TODAY section (with travel times for tasks with places)
                tasks_today = await self._get_tasks_due_today(today_start, today_end)
                task_travel_info: dict[str, TravelInfo] = {}
                if self.maps and self.home_address and tasks_today:
                    task_travel_info = await self._calculate_travel_times_for_tasks(tasks_today)
                tasks_section = self._format_tasks_due_today(tasks_today, task_travel_info)
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

                # 🧠 TODAY I LEARNED section (patterns learned in last 24 hours)
                til_section = await self._generate_til_section(today_start)
                if til_section:
                    sections.append(til_section)

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

        Includes travel time estimates for events with locations per PRD 5.2:
        'Leave by X' suggestions based on Distance Matrix API.

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

            # Calculate travel times for events with locations
            travel_info: dict[str, TravelInfo] = {}
            if self.maps and self.home_address:
                travel_info = await self._calculate_travel_times_for_events(events)

            return self._format_calendar_events(events, travel_info)

        except Exception as e:
            logger.exception(f"Failed to fetch calendar events: {e}")
            return None

    async def _calculate_travel_times_for_events(
        self,
        events: list[CalendarEvent],
    ) -> dict[str, TravelInfo]:
        """Calculate travel times for events with locations.

        For the first event with a location, calculates from home.
        For subsequent events, calculates from the previous event's location.

        Args:
            events: List of calendar events to analyze

        Returns:
            Dict mapping event_id to TravelInfo
        """
        if not self.maps or not self.home_address:
            return {}

        travel_info: dict[str, TravelInfo] = {}
        previous_location = self.home_address

        for event in events:
            if not event.location or not event.event_id:
                continue

            # Skip all-day events
            start_time = event.start_time
            if start_time.tzinfo is not None:
                try:
                    start_time = start_time.astimezone(self.timezone)
                except Exception:
                    pass

            is_all_day = (
                start_time.hour == 0
                and start_time.minute == 0
                and event.end_time.hour == 0
                and event.end_time.minute == 0
            )
            if is_all_day:
                continue

            try:
                travel_time = await self.maps.get_travel_time(
                    origin=previous_location,
                    destination=event.location,
                    mode="driving",
                )

                if travel_time:
                    # Use traffic-aware duration if available
                    duration_seconds = (
                        travel_time.duration_in_traffic_seconds
                        if travel_time.duration_in_traffic_seconds
                        else travel_time.duration_seconds
                    )
                    # Calculate when to leave (event time - travel time)
                    leave_by = event.start_time - timedelta(seconds=duration_seconds)

                    travel_info[event.event_id] = TravelInfo(
                        leave_by=leave_by,
                        travel_time=travel_time,
                        from_location=previous_location,
                        to_location=event.location,
                    )

                    # Update previous location for chained travel calculations
                    previous_location = event.location

            except Exception as e:
                logger.debug(f"Failed to get travel time for event {event.title}: {e}")

        return travel_info

    async def _calculate_travel_times_for_tasks(
        self,
        tasks: list[dict[str, Any]],
    ) -> dict[str, TravelInfo]:
        """Calculate travel times for tasks with places and specific due times.

        Per AT-122: Tasks like 'Dentist at 2pm' with a place should show
        'Leave by X' departure time calculated from home.

        Args:
            tasks: List of task results from Notion

        Returns:
            Dict mapping task page ID to TravelInfo
        """
        if not self.maps or not self.home_address or not self.notion:
            return {}

        travel_info: dict[str, TravelInfo] = {}

        for task in tasks:
            task_id = task.get("id")
            if not task_id:
                continue

            # Get the due date with time
            due_date = self._extract_date(task, "due_date")
            if not due_date:
                continue

            # Skip tasks without a specific time (midnight = no time specified)
            if due_date.hour == 0 and due_date.minute == 0:
                continue

            # Get place_ids from the task (relation property or rich_text)
            place_ids = self._extract_place_ids(task)
            if not place_ids:
                continue

            # Get the first place's address
            try:
                place = await self.notion.get_place(place_ids[0])
                if not place:
                    continue

                # Extract address from place
                address = self._extract_text(place, "address")
                if not address:
                    # Try to use the place name as address
                    address = self._extract_title(place)

                if not address:
                    continue

                # Calculate travel time from home to place
                travel_time = await self.maps.get_travel_time(
                    origin=self.home_address,
                    destination=address,
                    mode="driving",
                )

                if travel_time:
                    # Use traffic-aware duration if available
                    duration_seconds = (
                        travel_time.duration_in_traffic_seconds
                        if travel_time.duration_in_traffic_seconds
                        else travel_time.duration_seconds
                    )
                    # Calculate when to leave (task time - travel time)
                    leave_by = due_date - timedelta(seconds=duration_seconds)

                    travel_info[task_id] = TravelInfo(
                        leave_by=leave_by,
                        travel_time=travel_time,
                        from_location=self.home_address,
                        to_location=address,
                    )

            except Exception as e:
                title = self._extract_title(task)
                logger.debug(f"Failed to get travel time for task '{title}': {e}")

        return travel_info

    def _extract_place_ids(self, task: dict[str, Any]) -> list[str]:
        """Extract place IDs from a task.

        Handles both relation properties (list of page IDs) and
        rich_text storage of place IDs.

        Args:
            task: Task page from Notion

        Returns:
            List of place page IDs
        """
        props = task.get("properties", {})

        # Try relation property first
        place_relation = props.get("places", {}).get("relation", [])
        if place_relation:
            return [p.get("id") for p in place_relation if p.get("id")]

        # Try place_ids as multi_select (IDs stored as names)
        place_ids_prop = props.get("place_ids", {})
        multi_select = place_ids_prop.get("multi_select", [])
        if multi_select:
            return [p.get("name") for p in multi_select if p.get("name")]

        # Try place_ids as rich_text (comma-separated IDs)
        rich_text = place_ids_prop.get("rich_text", [])
        if rich_text:
            text = rich_text[0].get("text", {}).get("content", "")
            if text:
                return [pid.strip() for pid in text.split(",") if pid.strip()]

        return []

    def _format_calendar_events(
        self,
        events: list[CalendarEvent],
        travel_info: dict[str, TravelInfo] | None = None,
    ) -> str | None:
        """Format calendar events for the briefing.

        Args:
            events: List of CalendarEvent objects from Google Calendar
            travel_info: Optional dict mapping event_id to TravelInfo

        Returns:
            Formatted calendar section string or None if no events
        """
        if not events:
            return None

        travel_info = travel_info or {}
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

            # Add travel time info if available (per PRD 5.2)
            if event.event_id and event.event_id in travel_info:
                info = travel_info[event.event_id]
                departure_str = info.format_departure(self.timezone)
                lines.append(f"  └─ {departure_str}")

        if len(events) > 10:
            lines.append(f"  _...and {len(events) - 10} more events_")

        lines.append("")
        return "\n".join(lines)

    async def _generate_email_section(self) -> str | None:
        """Generate email section with emails needing attention.

        Per PRD Section 4.5 and 5.2:
        - Shows emails needing attention (unread, action-needed)
        - Format: sender, subject, time ago, action indicator

        Returns:
            Formatted email section or None if not available or no emails.
        """
        if not self.gmail or not self.gmail.is_authenticated():
            logger.debug("Gmail not authenticated - skipping email section")
            return None

        try:
            # Get emails needing response from last 48 hours
            result = await self.gmail.list_needing_response(max_results=5, since_hours=48)

            if not result.success:
                logger.warning(f"Failed to fetch emails: {result.error}")
                return None

            if not result.emails:
                return None

            return self._format_email_section(result.emails)

        except Exception as e:
            logger.exception(f"Failed to fetch emails for briefing: {e}")
            return None

    def _format_email_section(self, emails: list[EmailMessage]) -> str | None:
        """Format emails for the briefing.

        Args:
            emails: List of EmailMessage objects needing attention

        Returns:
            Formatted email section string or None if no emails
        """
        if not emails:
            return None

        lines = [f"📧 **EMAIL** ({len(emails)} need attention)"]

        now = datetime.now(self.timezone)

        for email in emails[:5]:  # Limit to 5 emails
            # Format time ago
            time_ago = self._format_time_ago(email.received_at, now)

            # Build email line
            # Format: sender (context) - "subject snippet" - time ago
            subject_preview = (
                email.subject[:40] + "..." if len(email.subject) > 40 else email.subject
            )

            # Priority indicator
            priority_marker = ""
            if email.priority == "high":
                priority_marker = " (urgent)"
            elif email.needs_response:
                priority_marker = " - needs response"

            line = f'• {email.sender_name}{priority_marker} - "{subject_preview}" - {time_ago}'
            lines.append(line)

        lines.append("")
        return "\n".join(lines)

    async def _generate_analyzed_email_section(self) -> str | None:
        """Generate section with LLM-analyzed important emails from Notion.

        Shows high-importance emails that were flagged by the email scanner,
        with their urgency, action items, and response status.

        Returns:
            Formatted section or None if not available or no important emails.
        """
        if not self.notion or not settings.notion_emails_db_id:
            return None

        try:
            # Get important emails from last 24 hours
            yesterday = datetime.now(self.timezone) - timedelta(hours=24)
            emails = await self.notion.get_important_emails(
                min_score=settings.email_importance_threshold,
                received_after=yesterday,
                limit=5,
            )

            if not emails:
                return None

            return self._format_analyzed_emails(emails)

        except Exception as e:
            logger.exception(f"Failed to fetch analyzed emails: {e}")
            return None

    def _format_analyzed_emails(self, emails: list[dict[str, Any]]) -> str | None:
        """Format LLM-analyzed emails for the briefing.

        Args:
            emails: List of email results from Notion

        Returns:
            Formatted section or None if no emails
        """
        if not emails:
            return None

        lines = ["🎯 **FLAGGED BY AI** (high importance)"]

        for email in emails[:5]:
            props = email.get("properties", {})

            # Extract values
            subject_prop = props.get("subject", {}).get("title", [])
            subject = subject_prop[0]["text"]["content"] if subject_prop else "No subject"

            from_prop = props.get("from_address", {}).get("rich_text", [])
            from_addr = from_prop[0]["text"]["content"] if from_prop else "Unknown"

            urgency_prop = props.get("urgency", {}).get("select", {})
            urgency = urgency_prop.get("name", "normal") if urgency_prop else "normal"

            needs_response = props.get("needs_response", {}).get("checkbox", False)

            # Build line with indicators
            urgency_icon = {"urgent": "🔴", "high": "🟠", "normal": "", "low": ""}.get(urgency, "")
            response_tag = " ⚡needs reply" if needs_response else ""

            subject_preview = subject[:35] + "..." if len(subject) > 35 else subject
            from_name = from_addr.split("@")[0][:15]  # Just the name part

            line = f"• {urgency_icon}{from_name}: {subject_preview}{response_tag}"
            lines.append(line)

            # Show action items if any
            action_items = props.get("action_items", {}).get("multi_select", [])
            if action_items:
                first_action = action_items[0].get("name", "")[:40]
                lines.append(f"  └─ Action: {first_action}")

        lines.append("")
        return "\n".join(lines)

    def _format_time_ago(self, timestamp: datetime, now: datetime) -> str:
        """Format a timestamp as relative time (e.g., '2 hours ago').

        Args:
            timestamp: The past timestamp
            now: Current time

        Returns:
            Human-readable relative time string
        """
        # Ensure both are timezone-aware for comparison
        if timestamp.tzinfo is None:
            timestamp = self.timezone.localize(timestamp)
        if now.tzinfo is None:
            now = self.timezone.localize(now)

        delta = now - timestamp

        if delta.days > 0:
            if delta.days == 1:
                return "1 day ago"
            return f"{delta.days} days ago"

        hours = delta.seconds // 3600
        if hours > 0:
            if hours == 1:
                return "1 hour ago"
            return f"{hours} hours ago"

        minutes = delta.seconds // 60
        if minutes > 0:
            if minutes == 1:
                return "1 minute ago"
            return f"{minutes} minutes ago"

        return "just now"

    async def _generate_til_section(
        self,
        since: datetime,
    ) -> str | None:
        """Generate 'Today I Learned' section with recently learned patterns.

        Per PRD: Include learned patterns in daily briefing.

        Args:
            since: Only show patterns learned after this time (typically last 24 hours)

        Returns:
            Formatted TIL section or None if no recent patterns
        """
        if not self.notion:
            return None

        try:
            # Query patterns learned since yesterday
            patterns = await self.notion.query_patterns(
                min_confidence=70,  # Only show patterns we're confident about
                created_after=since - timedelta(days=1),  # Last 24 hours
                limit=5,
            )

            if not patterns:
                return None

            return self._format_til_section(patterns)

        except Exception as e:
            logger.exception(f"Failed to fetch recent patterns for TIL: {e}")
            return None

    def _format_til_section(self, patterns: list[dict[str, Any]]) -> str | None:
        """Format learned patterns for the TIL section.

        Args:
            patterns: List of pattern results from Notion

        Returns:
            Formatted TIL section string or None if no patterns
        """
        if not patterns:
            return None

        lines = ["🧠 **TODAY I LEARNED**"]

        for pattern in patterns[:5]:
            trigger = self._extract_text(pattern, "trigger") or self._extract_title(pattern)
            meaning = self._extract_text(pattern, "meaning")
            pattern_type = self._extract_select(pattern, "type")
            _confidence = self._extract_number(pattern, "confidence")  # noqa: F841

            if not trigger or not meaning:
                continue

            # Format: "When you say 'trigger' → you mean 'meaning'"
            # Truncate if too long
            trigger_display = trigger[:30] + "..." if len(trigger) > 30 else trigger
            meaning_display = meaning[:30] + "..." if len(meaning) > 30 else meaning

            line = f'• "{trigger_display}" → "{meaning_display}"'

            # Add pattern type indicator if available
            type_icons = {
                "person_alias": "👤",
                "place_alias": "📍",
                "project_alias": "📁",
                "preference": "⚙️",
            }
            if pattern_type and pattern_type in type_icons:
                line = f"{type_icons[pattern_type]} {line}"

            lines.append(line)

        if len(patterns) > 5:
            lines.append(f"  _...and {len(patterns) - 5} more patterns_")

        lines.append("")
        return "\n".join(lines)

    def _extract_number(self, page: dict[str, Any], field: str) -> int | None:
        """Extract number from a number property.

        Args:
            page: Notion page response
            field: Property name

        Returns:
            Number value or None
        """
        props = page.get("properties", {})
        field_prop = props.get(field, {})
        return field_prop.get("number")

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

    def _format_tasks_due_today(
        self,
        tasks: list[dict[str, Any]],
        travel_info: dict[str, TravelInfo] | None = None,
    ) -> str | None:
        """Format tasks due today section.

        Args:
            tasks: List of task results from Notion
            travel_info: Optional dict mapping task ID to TravelInfo for departure times

        Returns:
            Formatted section string or None if no tasks
        """
        if not tasks:
            return None

        travel_info = travel_info or {}
        lines = ["✅ **DUE TODAY**"]
        for task in tasks[:5]:
            task_id = task.get("id")
            title = self._extract_title(task)
            priority = self._extract_select(task, "priority")
            status = self._extract_select(task, "status")
            due_date = self._extract_date(task, "due_date")

            # Add priority indicator
            priority_icon = self._get_priority_icon(priority)
            status_suffix = f" [{status}]" if status and status not in ("todo", "inbox") else ""

            # Add time if specific time is set
            time_str = ""
            if due_date and not (due_date.hour == 0 and due_date.minute == 0):
                due_local = due_date.astimezone(self.timezone) if due_date.tzinfo else due_date
                time_str = f" at {due_local.strftime('%H:%M')}"

            lines.append(f"• {priority_icon}{title}{time_str}{status_suffix}")

            # Add travel time info if available (per AT-122)
            if task_id and task_id in travel_info:
                info = travel_info[task_id]
                departure_str = info.format_departure(self.timezone)
                lines.append(f"  └─ {departure_str}")

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
            lines.append(f'• "{preview}"')

            # If we have an interpretation, show it
            if interpretation:
                interp_preview = (
                    interpretation[:40] + "..." if len(interpretation) > 40 else interpretation
                )
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
            text_dict: dict[str, Any] = title_list[0].get("text", {})
            return str(text_dict.get("content", "Untitled"))
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
            text_dict: dict[str, Any] = text_list[0].get("text", {})
            return str(text_dict.get("content", ""))
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
        select_value: dict[str, Any] | None = field_prop.get("select")
        if select_value:
            name = select_value.get("name")
            return str(name) if name is not None else None
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
