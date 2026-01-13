"""Tests for schedule conflict detection service.

Tests AT-123 (Unrealistic Schedule Detection):
- Given: User has meeting in San Francisco at 10am
- When: User sends "Meeting in Los Angeles at 11am"
- Then: Warning shown: "Travel time ~6 hours - schedule conflict detected"
- And: Task created but flagged for review
- Pass condition: Task exists AND warning logged AND needs_clarification=true
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from assistant.google.calendar import CalendarEvent
from assistant.google.maps import TravelTime
from assistant.services.schedule_conflict import (
    BUFFER_MINUTES,
    ConflictCheckResult,
    ScheduleConflict,
    ScheduleConflictDetector,
    check_schedule_conflicts,
    get_conflict_detector,
    is_schedule_conflict_impossible,
)


# --- Test Fixtures ---


@pytest.fixture
def sample_tz():
    """Sample timezone for tests."""
    return ZoneInfo("America/Los_Angeles")


@pytest.fixture
def sf_event(sample_tz) -> CalendarEvent:
    """A calendar event in San Francisco at 10am."""
    base_date = datetime.now(sample_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return CalendarEvent(
        event_id="event-sf-10am",
        title="SF Meeting",
        start_time=base_date + timedelta(hours=10),
        end_time=base_date + timedelta(hours=11),
        timezone="America/Los_Angeles",
        attendees=[],
        location="San Francisco, CA",
    )


@pytest.fixture
def la_event(sample_tz) -> CalendarEvent:
    """A calendar event in Los Angeles at 2pm."""
    base_date = datetime.now(sample_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return CalendarEvent(
        event_id="event-la-2pm",
        title="LA Meeting",
        start_time=base_date + timedelta(hours=14),
        end_time=base_date + timedelta(hours=15),
        timezone="America/Los_Angeles",
        attendees=[],
        location="Los Angeles, CA",
    )


@pytest.fixture
def sf_to_la_travel() -> TravelTime:
    """Travel time from SF to LA (~6 hours in traffic)."""
    return TravelTime(
        origin="San Francisco, CA",
        destination="Los Angeles, CA",
        distance_meters=615000,  # ~615 km
        duration_seconds=21600,  # 6 hours base
        duration_in_traffic_seconds=25200,  # 7 hours with traffic
    )


@pytest.fixture
def short_travel() -> TravelTime:
    """Short travel time (~30 minutes)."""
    return TravelTime(
        origin="Downtown SF",
        destination="Midtown SF",
        distance_meters=5000,
        duration_seconds=1800,  # 30 minutes
        duration_in_traffic_seconds=2100,  # 35 minutes with traffic
    )


# --- ScheduleConflict Tests ---


class TestScheduleConflict:
    """Tests for ScheduleConflict dataclass."""

    def test_is_impossible_when_travel_exceeds_available(self, sf_event, sf_to_la_travel):
        """Conflict is impossible when travel time exceeds available time."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time + timedelta(hours=1),  # 11am
            new_event_location="Los Angeles, CA",
            travel_time=sf_to_la_travel,
            travel_duration_minutes=420,  # 7 hours
            required_departure_time=sf_event.start_time - timedelta(hours=7),
            available_time_minutes=0,  # No time between events
        )

        assert conflict.is_impossible is True

    def test_not_impossible_when_travel_fits(self, sf_event, short_travel):
        """Conflict is not impossible when travel time fits."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time - timedelta(hours=2),  # 8am
            new_event_location="Downtown SF",
            travel_time=short_travel,
            travel_duration_minutes=50,  # 35 min + 15 buffer
            required_departure_time=sf_event.start_time - timedelta(minutes=50),
            available_time_minutes=60,  # 1 hour between
        )

        assert conflict.is_impossible is False

    def test_warning_message_for_impossible(self, sf_event, sf_to_la_travel):
        """Warning message for impossible schedule."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time + timedelta(hours=1),
            new_event_location="Los Angeles, CA",
            travel_time=sf_to_la_travel,
            travel_duration_minutes=420,
            required_departure_time=sf_event.start_time - timedelta(hours=7),
            available_time_minutes=0,
        )

        msg = conflict.warning_message
        assert "schedule conflict detected" in msg
        # "7 hours" is formatted as "7 hours" by _format_duration
        assert "7 hour" in msg or "420 min" in msg or "6 hr" in msg

    def test_warning_message_for_tight_schedule(self, sf_event, short_travel):
        """Warning message for tight but possible schedule."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time - timedelta(minutes=60),  # 9am
            new_event_location="Downtown SF",
            travel_time=short_travel,
            travel_duration_minutes=50,
            required_departure_time=sf_event.start_time - timedelta(minutes=50),
            available_time_minutes=60,
        )

        msg = conflict.warning_message
        assert "Tight schedule" in msg
        assert "10 min buffer" in msg

    def test_format_duration_minutes(self, sf_event):
        """Format duration under 1 hour."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time,
            new_event_location="Test",
            travel_time=None,
            travel_duration_minutes=45,
            required_departure_time=sf_event.start_time,
            available_time_minutes=0,
        )

        assert conflict._format_duration(45) == "45 min"

    def test_format_duration_hours(self, sf_event):
        """Format duration over 1 hour."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time,
            new_event_location="Test",
            travel_time=None,
            travel_duration_minutes=120,
            required_departure_time=sf_event.start_time,
            available_time_minutes=0,
        )

        assert conflict._format_duration(120) == "2 hours"
        assert conflict._format_duration(60) == "1 hour"

    def test_format_duration_hours_and_minutes(self, sf_event):
        """Format duration with hours and minutes."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time,
            new_event_location="Test",
            travel_time=None,
            travel_duration_minutes=90,
            required_departure_time=sf_event.start_time,
            available_time_minutes=0,
        )

        assert conflict._format_duration(90) == "1 hr 30 min"
        assert conflict._format_duration(150) == "2 hr 30 min"


# --- ConflictCheckResult Tests ---


class TestConflictCheckResult:
    """Tests for ConflictCheckResult dataclass."""

    def test_needs_clarification_with_impossible_conflict(self, sf_event):
        """needs_clarification is True when any conflict is impossible."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time,
            new_event_location="LA",
            travel_time=None,
            travel_duration_minutes=360,
            required_departure_time=sf_event.start_time,
            available_time_minutes=60,  # Only 1 hour for 6 hour trip
        )

        result = ConflictCheckResult(
            has_conflict=True,
            conflicts=[conflict],
            new_event_location="LA",
            new_event_time=sf_event.start_time,
        )

        assert result.needs_clarification is True

    def test_needs_clarification_false_when_possible(self, sf_event):
        """needs_clarification is False when conflicts are tight but possible."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time,
            new_event_location="Downtown",
            travel_time=None,
            travel_duration_minutes=30,
            required_departure_time=sf_event.start_time,
            available_time_minutes=60,  # 1 hour for 30 min trip - possible
        )

        result = ConflictCheckResult(
            has_conflict=True,
            conflicts=[conflict],
            new_event_location="Downtown",
            new_event_time=sf_event.start_time,
        )

        assert result.needs_clarification is False

    def test_primary_conflict_returns_most_severe(self, sf_event, la_event):
        """primary_conflict returns the most severe conflict."""
        conflict1 = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time,
            new_event_location="LA",
            travel_time=None,
            travel_duration_minutes=300,
            required_departure_time=sf_event.start_time,
            available_time_minutes=60,  # 240 min gap
        )
        conflict2 = ScheduleConflict(
            existing_event=la_event,
            new_event_time=la_event.start_time,
            new_event_location="LA",
            travel_time=None,
            travel_duration_minutes=400,
            required_departure_time=la_event.start_time,
            available_time_minutes=60,  # 340 min gap - more severe
        )

        result = ConflictCheckResult(
            has_conflict=True,
            conflicts=[conflict1, conflict2],
            new_event_location="LA",
            new_event_time=sf_event.start_time,
        )

        assert result.primary_conflict == conflict2

    def test_warning_message_from_primary(self, sf_event):
        """warning_message comes from primary conflict."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time,
            new_event_location="LA",
            travel_time=None,
            travel_duration_minutes=360,
            required_departure_time=sf_event.start_time,
            available_time_minutes=60,
        )

        result = ConflictCheckResult(
            has_conflict=True,
            conflicts=[conflict],
            new_event_location="LA",
            new_event_time=sf_event.start_time,
        )

        assert result.warning_message is not None
        assert "conflict" in result.warning_message.lower() or "schedule" in result.warning_message.lower()

    def test_no_conflicts(self, sample_tz):
        """Result with no conflicts."""
        result = ConflictCheckResult(
            has_conflict=False,
            conflicts=[],
            new_event_location="LA",
            new_event_time=datetime.now(sample_tz),
        )

        assert result.needs_clarification is False
        assert result.primary_conflict is None
        assert result.warning_message is None


# --- ScheduleConflictDetector Tests ---


class TestScheduleConflictDetector:
    """Tests for ScheduleConflictDetector class."""

    @pytest.mark.asyncio
    async def test_no_conflict_without_location_on_existing(self, sample_tz):
        """No conflict detected when existing event has no location."""
        detector = ScheduleConflictDetector()
        base_date = datetime.now(sample_tz).replace(hour=0, minute=0, second=0, microsecond=0)

        event_without_location = CalendarEvent(
            event_id="no-loc",
            title="Call",
            start_time=base_date + timedelta(hours=10),
            end_time=base_date + timedelta(hours=11),
            timezone="America/Los_Angeles",
            attendees=[],
            location=None,  # No location
        )

        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=base_date + timedelta(hours=11),
            existing_events=[event_without_location],
        )

        assert result.has_conflict is False

    @pytest.mark.asyncio
    async def test_no_conflict_same_location(self, sf_event, sample_tz):
        """No conflict when new event is at same location."""
        detector = ScheduleConflictDetector()

        result = await detector.check_for_conflicts(
            new_event_location="San Francisco, CA",  # Same as sf_event
            new_event_time=sf_event.start_time + timedelta(hours=1),
            existing_events=[sf_event],
        )

        assert result.has_conflict is False

    @pytest.mark.asyncio
    async def test_no_conflict_plenty_of_time(self, sf_event, sample_tz):
        """No conflict when there's plenty of time (>4 hours)."""
        detector = ScheduleConflictDetector()

        # New event 6 hours after sf_event
        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=sf_event.end_time + timedelta(hours=6),
            existing_events=[sf_event],
        )

        assert result.has_conflict is False

    @pytest.mark.asyncio
    async def test_conflict_detected_sf_to_la(self, sf_event, sf_to_la_travel, sample_tz):
        """Conflict detected for SF at 10am, LA at 11am."""
        mock_maps = MagicMock()
        mock_maps.get_travel_time = AsyncMock(return_value=sf_to_la_travel)

        detector = ScheduleConflictDetector(maps_client=mock_maps)

        # New event in LA at 11am (1 hour after SF meeting starts)
        new_time = sf_event.start_time + timedelta(hours=1)

        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=new_time,
            existing_events=[sf_event],
        )

        assert result.has_conflict is True
        assert result.needs_clarification is True
        assert len(result.conflicts) == 1

    @pytest.mark.asyncio
    async def test_conflict_message_includes_travel_time(self, sf_event, sf_to_la_travel, sample_tz):
        """Conflict warning message includes travel time estimate."""
        mock_maps = MagicMock()
        mock_maps.get_travel_time = AsyncMock(return_value=sf_to_la_travel)

        detector = ScheduleConflictDetector(maps_client=mock_maps)

        new_time = sf_event.start_time + timedelta(hours=1)

        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=new_time,
            existing_events=[sf_event],
        )

        assert result.warning_message is not None
        # Should mention travel time (~7 hours with traffic + buffer)
        assert "hr" in result.warning_message or "hour" in result.warning_message

    @pytest.mark.asyncio
    async def test_direct_time_overlap_conflict(self, sf_event, sample_tz):
        """Conflict detected when events directly overlap in time."""
        detector = ScheduleConflictDetector()

        # New event starts during sf_event
        overlapping_time = sf_event.start_time + timedelta(minutes=30)

        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=overlapping_time,
            existing_events=[sf_event],
        )

        # Direct overlap should be detected
        assert result.has_conflict is True
        assert len(result.conflicts) == 1
        assert result.conflicts[0].available_time_minutes == 0

    @pytest.mark.asyncio
    async def test_handles_maps_api_failure(self, sf_event, sample_tz):
        """Gracefully handles Maps API failures."""
        mock_maps = MagicMock()
        mock_maps.get_travel_time = AsyncMock(return_value=None)

        detector = ScheduleConflictDetector(maps_client=mock_maps)

        new_time = sf_event.start_time + timedelta(hours=2)

        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=new_time,
            existing_events=[sf_event],
        )

        # Should not crash, just not detect conflict
        assert result.has_conflict is False

    @pytest.mark.asyncio
    async def test_fetches_calendar_when_events_not_provided(self, sample_tz):
        """Fetches calendar events when not provided."""
        detector = ScheduleConflictDetector()

        base_date = datetime.now(sample_tz).replace(hour=0, minute=0, second=0, microsecond=0)

        with patch(
            "assistant.services.schedule_conflict.list_calendar_events",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = []

            result = await detector.check_for_conflicts(
                new_event_location="LA",
                new_event_time=base_date + timedelta(hours=10),
                existing_events=None,  # Will fetch
            )

            mock_list.assert_called_once()
            assert result.has_conflict is False


class TestLocationMatching:
    """Tests for location matching logic."""

    def test_exact_match(self):
        """Exact location match detected."""
        detector = ScheduleConflictDetector()
        assert detector._locations_match("San Francisco", "San Francisco") is True

    def test_case_insensitive(self):
        """Case-insensitive matching."""
        detector = ScheduleConflictDetector()
        assert detector._locations_match("san francisco", "San Francisco") is True
        assert detector._locations_match("SAN FRANCISCO", "san francisco") is True

    def test_partial_match_contains(self):
        """Partial match when one contains the other."""
        detector = ScheduleConflictDetector()
        assert detector._locations_match("San Francisco", "San Francisco, CA") is True
        assert detector._locations_match("SF Office", "Our SF Office Building") is True

    def test_different_locations(self):
        """Different locations don't match."""
        detector = ScheduleConflictDetector()
        assert detector._locations_match("San Francisco", "Los Angeles") is False
        assert detector._locations_match("NYC", "LA") is False


# --- Module-Level Function Tests ---


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_conflict_detector_singleton(self):
        """get_conflict_detector returns singleton."""
        detector1 = get_conflict_detector()
        detector2 = get_conflict_detector()
        assert detector1 is detector2

    @pytest.mark.asyncio
    async def test_check_schedule_conflicts_convenience(self, sample_tz):
        """check_schedule_conflicts convenience function works."""
        base_date = datetime.now(sample_tz).replace(hour=0, minute=0, second=0, microsecond=0)

        result = await check_schedule_conflicts(
            location="LA",
            event_time=base_date + timedelta(hours=10),
            existing_events=[],
        )

        assert isinstance(result, ConflictCheckResult)
        assert result.has_conflict is False

    def test_is_schedule_conflict_impossible(self, sf_event):
        """is_schedule_conflict_impossible helper function."""
        conflict = ScheduleConflict(
            existing_event=sf_event,
            new_event_time=sf_event.start_time,
            new_event_location="LA",
            travel_time=None,
            travel_duration_minutes=360,
            required_departure_time=sf_event.start_time,
            available_time_minutes=60,
        )

        result = ConflictCheckResult(
            has_conflict=True,
            conflicts=[conflict],
            new_event_location="LA",
            new_event_time=sf_event.start_time,
        )

        assert is_schedule_conflict_impossible(result) is True


# --- AT-123 Acceptance Tests ---


class TestAT123UnrealisticScheduleDetection:
    """Acceptance tests for AT-123.

    AT-123 — Unrealistic Schedule Detection
    - Given: User has meeting in San Francisco at 10am
    - When: User sends "Meeting in Los Angeles at 11am"
    - Then: Warning shown: "Travel time ~6 hours - schedule conflict detected"
    - And: Task created but flagged for review
    - Pass condition: Task exists AND warning logged AND needs_clarification=true
    """

    @pytest.mark.asyncio
    async def test_at123_sf_to_la_conflict_detected(self, sf_event, sf_to_la_travel, sample_tz):
        """AT-123: SF 10am to LA 11am detected as conflict."""
        mock_maps = MagicMock()
        mock_maps.get_travel_time = AsyncMock(return_value=sf_to_la_travel)

        detector = ScheduleConflictDetector(maps_client=mock_maps)

        # Given: meeting in SF at 10am (sf_event fixture)
        # When: "Meeting in Los Angeles at 11am"
        la_meeting_time = sf_event.start_time + timedelta(hours=1)

        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=la_meeting_time,
            existing_events=[sf_event],
        )

        # Then: Warning shown with travel time
        assert result.has_conflict is True
        assert "travel" in result.warning_message.lower() or "conflict" in result.warning_message.lower()

        # And: Task flagged for review
        assert result.needs_clarification is True

    @pytest.mark.asyncio
    async def test_at123_warning_includes_approximate_time(self, sf_event, sf_to_la_travel, sample_tz):
        """AT-123: Warning includes approximate travel time."""
        mock_maps = MagicMock()
        mock_maps.get_travel_time = AsyncMock(return_value=sf_to_la_travel)

        detector = ScheduleConflictDetector(maps_client=mock_maps)

        la_meeting_time = sf_event.start_time + timedelta(hours=1)

        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=la_meeting_time,
            existing_events=[sf_event],
        )

        # Warning should mention hours
        warning = result.warning_message
        assert warning is not None
        assert "hr" in warning or "hour" in warning

    @pytest.mark.asyncio
    async def test_at123_needs_clarification_flag(self, sf_event, sf_to_la_travel, sample_tz):
        """AT-123: needs_clarification is True for impossible schedule."""
        mock_maps = MagicMock()
        mock_maps.get_travel_time = AsyncMock(return_value=sf_to_la_travel)

        detector = ScheduleConflictDetector(maps_client=mock_maps)

        la_meeting_time = sf_event.start_time + timedelta(hours=1)

        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=la_meeting_time,
            existing_events=[sf_event],
        )

        # Pass condition: needs_clarification=true
        assert result.needs_clarification is True

    @pytest.mark.asyncio
    async def test_at123_full_flow_integration(self, sf_event, sf_to_la_travel, sample_tz):
        """AT-123: Full integration test for unrealistic schedule."""
        # Setup mocked Maps client
        mock_maps = MagicMock()
        mock_maps.get_travel_time = AsyncMock(return_value=sf_to_la_travel)

        detector = ScheduleConflictDetector(maps_client=mock_maps)

        # Scenario: User has SF meeting at 10am, wants LA meeting at 11am
        la_meeting_time = sf_event.start_time + timedelta(hours=1)

        result = await detector.check_for_conflicts(
            new_event_location="Los Angeles, CA",
            new_event_time=la_meeting_time,
            existing_events=[sf_event],
        )

        # Verify all AT-123 pass conditions:
        # 1. Conflict detected (task would be created)
        assert result.has_conflict is True

        # 2. Warning logged
        assert result.warning_message is not None
        assert len(result.warning_message) > 0

        # 3. needs_clarification=true
        assert result.needs_clarification is True

        # 4. Conflict shows travel time info
        assert result.primary_conflict is not None
        assert result.primary_conflict.travel_duration_minutes > 0


class TestPRDSection44Compliance:
    """Tests for PRD Section 4.4 travel time detection compliance."""

    @pytest.mark.asyncio
    async def test_buffer_time_included(self, sf_event, short_travel, sample_tz):
        """Travel time includes buffer for parking/walking."""
        mock_maps = MagicMock()
        mock_maps.get_travel_time = AsyncMock(return_value=short_travel)

        detector = ScheduleConflictDetector(maps_client=mock_maps)

        # Event 45 min after SF meeting (35 min travel + 15 min buffer = 50 min)
        tight_time = sf_event.end_time + timedelta(minutes=45)

        result = await detector.check_for_conflicts(
            new_event_location="Downtown SF",
            new_event_time=tight_time,
            existing_events=[sf_event],
        )

        # 45 min available, 50 min needed (35 + 15 buffer) = conflict
        assert result.has_conflict is True

    @pytest.mark.asyncio
    async def test_uses_traffic_time_when_available(self, sf_event, sample_tz):
        """Uses duration_in_traffic when available."""
        travel = TravelTime(
            origin="A",
            destination="B",
            distance_meters=50000,
            duration_seconds=3600,  # 60 min base
            duration_in_traffic_seconds=5400,  # 90 min with traffic
        )

        mock_maps = MagicMock()
        mock_maps.get_travel_time = AsyncMock(return_value=travel)

        detector = ScheduleConflictDetector(maps_client=mock_maps)

        # 80 min between events (not enough for 90 min + buffer)
        event_time = sf_event.end_time + timedelta(minutes=80)

        result = await detector.check_for_conflicts(
            new_event_location="Location B",
            new_event_time=event_time,
            existing_events=[sf_event],
        )

        # Should use 90 min (traffic) + 15 buffer = 105 min needed, 80 available = conflict
        assert result.has_conflict is True
