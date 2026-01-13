"""Schedule conflict detection for unrealistic schedules.

Detects when a user schedules events that are physically impossible to attend
due to travel time constraints (e.g., meeting in SF at 10am, LA at 11am).

Per PRD Section 4.4 and AT-123:
- Check travel time between consecutive events
- Warn if arrival time exceeds event start time
- Flag tasks for review when conflict detected
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from assistant.google.calendar import CalendarEvent, list_calendar_events
from assistant.google.maps import MapsClient, TravelTime

logger = logging.getLogger(__name__)

# Buffer time in minutes to add to travel estimate
BUFFER_MINUTES = 15

# How far ahead to check for conflicts (hours)
CONFLICT_CHECK_WINDOW_HOURS = 24


@dataclass
class ScheduleConflict:
    """Represents a detected schedule conflict."""

    existing_event: CalendarEvent
    new_event_time: datetime
    new_event_location: str
    travel_time: TravelTime | None
    travel_duration_minutes: int
    required_departure_time: datetime
    available_time_minutes: int

    @property
    def is_impossible(self) -> bool:
        """Check if the schedule is physically impossible.

        Returns True if travel time exceeds available time.
        """
        return self.travel_duration_minutes > self.available_time_minutes

    @property
    def warning_message(self) -> str:
        """Generate a human-readable warning message."""
        travel_formatted = self._format_duration(self.travel_duration_minutes)

        if self.is_impossible:
            return (
                f"Travel time ~{travel_formatted} - schedule conflict detected. "
                f"You have a meeting at {self.existing_event.location or 'another location'} "
                f"at {self.existing_event.start_time.strftime('%I:%M %p').lstrip('0')}."
            )
        else:
            # Tight but possible
            buffer_minutes = self.available_time_minutes - self.travel_duration_minutes
            return (
                f"Tight schedule: ~{travel_formatted} travel time, "
                f"only {buffer_minutes} min buffer before {self.existing_event.title}."
            )

    def _format_duration(self, minutes: int) -> str:
        """Format minutes as human-readable duration."""
        if minutes < 60:
            return f"{minutes} min"
        hours = minutes // 60
        remaining = minutes % 60
        if remaining == 0:
            return f"{hours} hour{'s' if hours > 1 else ''}"
        return f"{hours} hr {remaining} min"


@dataclass
class ConflictCheckResult:
    """Result of checking for schedule conflicts."""

    has_conflict: bool
    conflicts: list[ScheduleConflict]
    new_event_location: str
    new_event_time: datetime

    @property
    def needs_clarification(self) -> bool:
        """Whether the task should be flagged for clarification."""
        return any(c.is_impossible for c in self.conflicts)

    @property
    def primary_conflict(self) -> ScheduleConflict | None:
        """Get the most severe conflict (largest travel time gap)."""
        impossible = [c for c in self.conflicts if c.is_impossible]
        if impossible:

            def travel_gap(c: ScheduleConflict) -> int:
                return c.travel_duration_minutes - c.available_time_minutes

            return max(impossible, key=travel_gap)
        return self.conflicts[0] if self.conflicts else None

    @property
    def warning_message(self) -> str | None:
        """Get warning message from primary conflict."""
        if self.primary_conflict:
            return self.primary_conflict.warning_message
        return None


class ScheduleConflictDetector:
    """Detects unrealistic schedules based on travel time.

    Provides:
    - Check new event against existing calendar
    - Calculate travel time between locations
    - Generate conflict warnings
    - Support for flagging tasks that need review
    """

    def __init__(self, maps_client: MapsClient | None = None) -> None:
        """Initialize the conflict detector.

        Args:
            maps_client: MapsClient instance (default: create new)
        """
        self._maps_client = maps_client

    @property
    def maps_client(self) -> MapsClient:
        """Get or create the Maps client."""
        if self._maps_client is None:
            self._maps_client = MapsClient()
        return self._maps_client

    async def check_for_conflicts(
        self,
        new_event_location: str,
        new_event_time: datetime,
        existing_events: list[CalendarEvent] | None = None,
        timezone: str | None = None,
    ) -> ConflictCheckResult:
        """Check if a new event conflicts with existing calendar events.

        Args:
            new_event_location: Location of the new event (address or place name)
            new_event_time: Start time of the new event
            existing_events: Optional list of events to check against
                           (default: fetches from calendar)
            timezone: Timezone for queries (default: user timezone)

        Returns:
            ConflictCheckResult with any detected conflicts
        """
        conflicts: list[ScheduleConflict] = []

        # Get existing events if not provided
        if existing_events is None:
            # Check events in a window around the new event time
            window_start = new_event_time - timedelta(hours=CONFLICT_CHECK_WINDOW_HOURS)
            window_end = new_event_time + timedelta(hours=CONFLICT_CHECK_WINDOW_HOURS)

            try:
                existing_events = await list_calendar_events(
                    start_time=window_start,
                    end_time=window_end,
                    timezone=timezone,
                )
            except Exception as e:
                logger.warning(f"Failed to fetch calendar events: {e}")
                existing_events = []

        # Check each event that could conflict
        for event in existing_events:
            conflict = await self._check_single_event(
                new_event_location=new_event_location,
                new_event_time=new_event_time,
                existing_event=event,
            )
            if conflict:
                conflicts.append(conflict)

        return ConflictCheckResult(
            has_conflict=len(conflicts) > 0,
            conflicts=conflicts,
            new_event_location=new_event_location,
            new_event_time=new_event_time,
        )

    async def _check_single_event(
        self,
        new_event_location: str,
        new_event_time: datetime,
        existing_event: CalendarEvent,
    ) -> ScheduleConflict | None:
        """Check if a single existing event conflicts with the new event.

        Scenarios:
        1. New event is BEFORE existing event: need travel time to get there
        2. New event is AFTER existing event (or starts when it ends): need travel time from there

        Args:
            new_event_location: Where the new event is
            new_event_time: When the new event starts
            existing_event: An existing calendar event

        Returns:
            ScheduleConflict if conflict detected, None otherwise
        """
        # Skip events without locations
        if not existing_event.location:
            return None

        # Skip if same location (no travel needed)
        if self._locations_match(new_event_location, existing_event.location):
            return None

        # Determine which direction we're traveling
        # New event is "before" if it starts before the existing event starts
        new_is_before = new_event_time < existing_event.start_time
        # New event is "after" if it starts at or after the existing event ends
        new_is_after = new_event_time >= existing_event.end_time
        # They overlap if new_event starts during existing event (but before it ends)
        events_overlap = existing_event.start_time <= new_event_time < existing_event.end_time

        if new_is_before:
            # New event is before existing - check if we can get from new to existing
            # Available time = existing_event.start_time - new_event_time (assuming 1hr new event)
            assumed_new_event_end = new_event_time + timedelta(hours=1)
            available_time = existing_event.start_time - assumed_new_event_end
            origin = new_event_location
            destination = existing_event.location
        elif new_is_after:
            # New event is after existing (or starts exactly when it ends)
            # Check if we can get from existing location to new location in time
            available_time = new_event_time - existing_event.end_time
            origin = existing_event.location
            destination = new_event_location
        elif events_overlap:
            # Events overlap in time - this is a direct time conflict, not travel
            # The new event starts during the existing event
            return ScheduleConflict(
                existing_event=existing_event,
                new_event_time=new_event_time,
                new_event_location=new_event_location,
                travel_time=None,
                travel_duration_minutes=0,
                required_departure_time=new_event_time,
                available_time_minutes=0,  # No time available - direct overlap
            )
        else:
            # Should not reach here
            return None

        available_minutes = int(available_time.total_seconds() // 60)

        # If plenty of time available (>4 hours), skip detailed check
        if available_minutes > 240:
            return None

        # Get travel time
        try:
            travel_time = await self.maps_client.get_travel_time(
                origin=origin,
                destination=destination,
            )
        except Exception as e:
            logger.warning(f"Failed to get travel time: {e}")
            return None

        if travel_time is None:
            return None

        # Use duration with traffic if available, else base duration
        travel_minutes = travel_time.duration_with_traffic_minutes or travel_time.duration_minutes

        # Add buffer time for parking, walking, etc.
        total_travel_minutes = travel_minutes + BUFFER_MINUTES

        # Check if there's a conflict (travel time > available time)
        if total_travel_minutes > available_minutes:
            # Calculate required departure time
            travel_delta = timedelta(minutes=total_travel_minutes)
            if new_is_before:
                required_departure = existing_event.start_time - travel_delta
            else:
                required_departure = new_event_time - travel_delta

            return ScheduleConflict(
                existing_event=existing_event,
                new_event_time=new_event_time,
                new_event_location=new_event_location,
                travel_time=travel_time,
                travel_duration_minutes=total_travel_minutes,
                required_departure_time=required_departure,
                available_time_minutes=available_minutes,
            )

        return None

    def _locations_match(self, loc1: str, loc2: str) -> bool:
        """Check if two locations are approximately the same.

        Simple string matching - could be enhanced with geocoding comparison.
        """
        loc1_clean = loc1.lower().strip()
        loc2_clean = loc2.lower().strip()

        # Exact match
        if loc1_clean == loc2_clean:
            return True

        # One contains the other
        if loc1_clean in loc2_clean or loc2_clean in loc1_clean:
            return True

        return False


# Module-level singleton
_conflict_detector: ScheduleConflictDetector | None = None


def get_conflict_detector() -> ScheduleConflictDetector:
    """Get or create the global ScheduleConflictDetector instance."""
    global _conflict_detector
    if _conflict_detector is None:
        _conflict_detector = ScheduleConflictDetector()
    return _conflict_detector


async def check_schedule_conflicts(
    location: str,
    event_time: datetime,
    existing_events: list[CalendarEvent] | None = None,
) -> ConflictCheckResult:
    """Check for schedule conflicts with an event.

    Convenience function using the global detector.

    Args:
        location: Location of the new event
        event_time: Start time of the new event
        existing_events: Optional events to check against

    Returns:
        ConflictCheckResult with any detected conflicts
    """
    return await get_conflict_detector().check_for_conflicts(
        new_event_location=location,
        new_event_time=event_time,
        existing_events=existing_events,
    )


def is_schedule_conflict_impossible(result: ConflictCheckResult) -> bool:
    """Check if a conflict result indicates an impossible schedule.

    Convenience function for handlers.
    """
    return result.needs_clarification
