"""Google Calendar integration for Second Brain.

Creates and manages calendar events from tasks, with undo support.

Per PRD Section 4.4 and AT-110/AT-116:
- Create events with title, time, attendees
- Link Notion task to calendar_event_id
- Support undo within 5 minutes (delete calendar event)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Any
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from assistant.google.auth import google_auth
from assistant.config import settings

logger = logging.getLogger(__name__)

# Default event duration if not specified
DEFAULT_EVENT_DURATION_MINUTES = 60

# Undo window in minutes (per PRD Section 6.2)
UNDO_WINDOW_MINUTES = 5


@dataclass
class CalendarEvent:
    """Represents a Google Calendar event."""

    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
    timezone: str
    attendees: list[str]  # email addresses
    location: Optional[str] = None
    description: Optional[str] = None
    html_link: Optional[str] = None


@dataclass
class EventCreationResult:
    """Result of creating a calendar event."""

    success: bool
    event_id: Optional[str] = None
    event: Optional[CalendarEvent] = None
    html_link: Optional[str] = None
    error: Optional[str] = None
    undo_available_until: Optional[datetime] = None


@dataclass
class EventDeletionResult:
    """Result of deleting a calendar event."""

    success: bool
    event_id: Optional[str] = None
    error: Optional[str] = None


class CalendarClient:
    """Google Calendar client for creating and managing events.

    Provides:
    - Event creation with title, time, optional attendees
    - Event deletion for undo support
    - Event lookup by ID
    - Calendar availability check (future)
    """

    def __init__(self):
        """Initialize the calendar client."""
        self._service = None

    @property
    def service(self):
        """Get or create the Calendar API service.

        Returns:
            Calendar API service object, or None if not authenticated.
        """
        if self._service is None:
            creds = google_auth.credentials
            if creds is None:
                # Try loading saved credentials
                if google_auth.load_saved_credentials():
                    creds = google_auth.credentials

            if creds is not None:
                self._service = build("calendar", "v3", credentials=creds)

        return self._service

    def is_authenticated(self) -> bool:
        """Check if we have valid Google Calendar credentials."""
        return self.service is not None

    async def create_event(
        self,
        title: str,
        start_time: datetime,
        duration_minutes: int = DEFAULT_EVENT_DURATION_MINUTES,
        timezone: Optional[str] = None,
        attendees: Optional[list[str]] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        calendar_id: str = "primary",
    ) -> EventCreationResult:
        """Create a calendar event.

        Args:
            title: Event title/summary
            start_time: When the event starts
            duration_minutes: Event duration in minutes (default: 60)
            timezone: Timezone for the event (default: user timezone from settings)
            attendees: List of attendee email addresses
            location: Event location
            description: Event description/notes
            calendar_id: Which calendar to add to (default: primary)

        Returns:
            EventCreationResult with success status and event details
        """
        if not self.is_authenticated():
            return EventCreationResult(
                success=False,
                error="Google Calendar not authenticated. Please run OAuth flow first.",
            )

        # Use configured timezone or UTC
        tz_str = timezone or settings.user_timezone
        try:
            tz = ZoneInfo(tz_str)
        except Exception:
            tz = ZoneInfo("UTC")
            tz_str = "UTC"

        # Ensure start_time has timezone info
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=tz)

        # Calculate end time
        end_time = start_time + timedelta(minutes=duration_minutes)

        # Build event body
        event_body: dict[str, Any] = {
            "summary": title,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": tz_str,
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": tz_str,
            },
        }

        if location:
            event_body["location"] = location

        if description:
            event_body["description"] = description

        if attendees:
            event_body["attendees"] = [{"email": email} for email in attendees]

        try:
            # Use synchronous API call (wrapped for async context)
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.service.events()
                .insert(calendarId=calendar_id, body=event_body)
                .execute(),
            )

            event_id = result.get("id", "")
            html_link = result.get("htmlLink", "")

            event = CalendarEvent(
                event_id=event_id,
                title=title,
                start_time=start_time,
                end_time=end_time,
                timezone=tz_str,
                attendees=attendees or [],
                location=location,
                description=description,
                html_link=html_link,
            )

            undo_until = datetime.utcnow() + timedelta(minutes=UNDO_WINDOW_MINUTES)

            logger.info(f"Created calendar event: {event_id} - {title}")

            return EventCreationResult(
                success=True,
                event_id=event_id,
                event=event,
                html_link=html_link,
                undo_available_until=undo_until,
            )

        except HttpError as e:
            logger.exception(f"Google Calendar API error: {e}")
            return EventCreationResult(
                success=False,
                error=f"Calendar API error: {e.reason if hasattr(e, 'reason') else str(e)}",
            )
        except Exception as e:
            logger.exception(f"Failed to create calendar event: {e}")
            return EventCreationResult(
                success=False,
                error=f"Failed to create event: {str(e)}",
            )

    async def delete_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
    ) -> EventDeletionResult:
        """Delete a calendar event (for undo support).

        Args:
            event_id: The Google Calendar event ID
            calendar_id: Which calendar (default: primary)

        Returns:
            EventDeletionResult with success status
        """
        if not self.is_authenticated():
            return EventDeletionResult(
                success=False,
                error="Google Calendar not authenticated.",
            )

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.service.events()
                .delete(calendarId=calendar_id, eventId=event_id)
                .execute(),
            )

            logger.info(f"Deleted calendar event: {event_id}")

            return EventDeletionResult(
                success=True,
                event_id=event_id,
            )

        except HttpError as e:
            # 404 means already deleted - treat as success
            if e.resp.status == 404:
                return EventDeletionResult(
                    success=True,
                    event_id=event_id,
                )

            logger.exception(f"Google Calendar API error: {e}")
            return EventDeletionResult(
                success=False,
                event_id=event_id,
                error=f"Calendar API error: {e.reason if hasattr(e, 'reason') else str(e)}",
            )
        except Exception as e:
            logger.exception(f"Failed to delete calendar event: {e}")
            return EventDeletionResult(
                success=False,
                event_id=event_id,
                error=f"Failed to delete event: {str(e)}",
            )

    async def get_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
    ) -> Optional[CalendarEvent]:
        """Get a calendar event by ID.

        Args:
            event_id: The Google Calendar event ID
            calendar_id: Which calendar (default: primary)

        Returns:
            CalendarEvent if found, None otherwise
        """
        if not self.is_authenticated():
            return None

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute(),
            )

            # Parse start/end times
            start_info = result.get("start", {})
            end_info = result.get("end", {})

            # Handle dateTime or date formats
            if "dateTime" in start_info:
                start_time = datetime.fromisoformat(
                    start_info["dateTime"].replace("Z", "+00:00")
                )
            else:
                start_time = datetime.fromisoformat(start_info.get("date", ""))

            if "dateTime" in end_info:
                end_time = datetime.fromisoformat(
                    end_info["dateTime"].replace("Z", "+00:00")
                )
            else:
                end_time = datetime.fromisoformat(end_info.get("date", ""))

            timezone = start_info.get("timeZone", "UTC")

            # Extract attendees
            attendees = [
                a.get("email", "")
                for a in result.get("attendees", [])
                if a.get("email")
            ]

            return CalendarEvent(
                event_id=result.get("id", ""),
                title=result.get("summary", ""),
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
                attendees=attendees,
                location=result.get("location"),
                description=result.get("description"),
                html_link=result.get("htmlLink"),
            )

        except HttpError as e:
            if e.resp.status == 404:
                return None
            logger.exception(f"Google Calendar API error: {e}")
            return None
        except Exception as e:
            logger.exception(f"Failed to get calendar event: {e}")
            return None

    async def event_exists(
        self,
        event_id: str,
        calendar_id: str = "primary",
    ) -> bool:
        """Check if a calendar event exists.

        Args:
            event_id: The Google Calendar event ID
            calendar_id: Which calendar (default: primary)

        Returns:
            True if event exists, False otherwise
        """
        event = await self.get_event(event_id, calendar_id)
        return event is not None

    async def list_events(
        self,
        start_time: datetime,
        end_time: datetime,
        timezone: Optional[str] = None,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[CalendarEvent]:
        """List calendar events in a time range.

        Args:
            start_time: Start of time range (inclusive)
            end_time: End of time range (exclusive)
            timezone: Timezone for the query (default: user timezone from settings)
            calendar_id: Which calendar to query (default: primary)
            max_results: Maximum number of events to return (default: 50)

        Returns:
            List of CalendarEvent objects, sorted by start time
        """
        if not self.is_authenticated():
            logger.warning("Calendar not authenticated - cannot list events")
            return []

        # Use configured timezone or UTC
        tz_str = timezone or settings.user_timezone
        try:
            tz = ZoneInfo(tz_str)
        except Exception:
            tz = ZoneInfo("UTC")
            tz_str = "UTC"

        # Ensure times have timezone info
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=tz)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=tz)

        try:
            import asyncio
            loop = asyncio.get_event_loop()

            # Build the request
            def do_list():
                return (
                    self.service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=start_time.isoformat(),
                        timeMax=end_time.isoformat(),
                        maxResults=max_results,
                        singleEvents=True,  # Expand recurring events
                        orderBy="startTime",
                    )
                    .execute()
                )

            result = await loop.run_in_executor(None, do_list)

            events = []
            for item in result.get("items", []):
                event = self._parse_event_response(item, tz_str)
                if event:
                    events.append(event)

            logger.info(
                f"Listed {len(events)} calendar events from {start_time} to {end_time}"
            )
            return events

        except HttpError as e:
            logger.exception(f"Google Calendar API error listing events: {e}")
            return []
        except Exception as e:
            logger.exception(f"Failed to list calendar events: {e}")
            return []

    def _parse_event_response(
        self,
        item: dict[str, Any],
        default_timezone: str,
    ) -> Optional[CalendarEvent]:
        """Parse a Google Calendar event response into a CalendarEvent.

        Args:
            item: Raw event dict from Google API
            default_timezone: Default timezone to use if not specified in event

        Returns:
            CalendarEvent or None if parsing fails
        """
        try:
            start_info = item.get("start", {})
            end_info = item.get("end", {})

            # Handle dateTime (timed events) or date (all-day events)
            if "dateTime" in start_info:
                start_time = datetime.fromisoformat(
                    start_info["dateTime"].replace("Z", "+00:00")
                )
                is_all_day = False
            elif "date" in start_info:
                # All-day event: date string like "2026-01-12"
                start_time = datetime.strptime(start_info["date"], "%Y-%m-%d")
                try:
                    start_time = start_time.replace(tzinfo=ZoneInfo(default_timezone))
                except Exception:
                    start_time = start_time.replace(tzinfo=ZoneInfo("UTC"))
                is_all_day = True
            else:
                return None

            if "dateTime" in end_info:
                end_time = datetime.fromisoformat(
                    end_info["dateTime"].replace("Z", "+00:00")
                )
            elif "date" in end_info:
                end_time = datetime.strptime(end_info["date"], "%Y-%m-%d")
                try:
                    end_time = end_time.replace(tzinfo=ZoneInfo(default_timezone))
                except Exception:
                    end_time = end_time.replace(tzinfo=ZoneInfo("UTC"))
            else:
                end_time = start_time + timedelta(hours=1)

            timezone = start_info.get("timeZone", default_timezone)

            # Extract attendees
            attendees = [
                a.get("email", "")
                for a in item.get("attendees", [])
                if a.get("email")
            ]

            return CalendarEvent(
                event_id=item.get("id", ""),
                title=item.get("summary", "Untitled"),
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
                attendees=attendees,
                location=item.get("location"),
                description=item.get("description"),
                html_link=item.get("htmlLink"),
            )

        except Exception as e:
            logger.warning(f"Failed to parse calendar event: {e}")
            return None


# Module-level singleton instance
_calendar_client: Optional[CalendarClient] = None


def get_calendar_client() -> CalendarClient:
    """Get or create the global CalendarClient instance."""
    global _calendar_client
    if _calendar_client is None:
        _calendar_client = CalendarClient()
    return _calendar_client


async def create_calendar_event(
    title: str,
    start_time: datetime,
    duration_minutes: int = DEFAULT_EVENT_DURATION_MINUTES,
    timezone: Optional[str] = None,
    attendees: Optional[list[str]] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
) -> EventCreationResult:
    """Create a calendar event.

    Convenience function using the global client.
    """
    return await get_calendar_client().create_event(
        title=title,
        start_time=start_time,
        duration_minutes=duration_minutes,
        timezone=timezone,
        attendees=attendees,
        location=location,
        description=description,
    )


async def delete_calendar_event(event_id: str) -> EventDeletionResult:
    """Delete a calendar event.

    Convenience function using the global client.
    """
    return await get_calendar_client().delete_event(event_id)


async def calendar_event_exists(event_id: str) -> bool:
    """Check if a calendar event exists.

    Convenience function using the global client.
    """
    return await get_calendar_client().event_exists(event_id)


async def list_calendar_events(
    start_time: datetime,
    end_time: datetime,
    timezone: Optional[str] = None,
    max_results: int = 50,
) -> list[CalendarEvent]:
    """List calendar events in a time range.

    Convenience function using the global client.

    Args:
        start_time: Start of time range
        end_time: End of time range
        timezone: Optional timezone override
        max_results: Maximum events to return

    Returns:
        List of CalendarEvent objects sorted by start time
    """
    return await get_calendar_client().list_events(
        start_time=start_time,
        end_time=end_time,
        timezone=timezone,
        max_results=max_results,
    )


async def list_todays_events(timezone: Optional[str] = None) -> list[CalendarEvent]:
    """List today's calendar events.

    Convenience function for briefings - gets events from midnight to midnight.

    Args:
        timezone: Optional timezone override (default: user timezone from settings)

    Returns:
        List of CalendarEvent objects for today, sorted by start time
    """
    tz_str = timezone or settings.user_timezone
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    return await list_calendar_events(
        start_time=today_start,
        end_time=today_end,
        timezone=tz_str,
    )
