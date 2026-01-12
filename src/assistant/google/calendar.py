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
