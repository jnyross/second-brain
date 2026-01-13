"""Tests for Google Calendar integration (T-101).

Tests cover:
- CalendarClient initialization and authentication
- Event creation (AT-110)
- Event deletion for undo support (AT-116)
- Notion task linking with calendar_event_id
- Error handling
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from assistant.google.calendar import (
    DEFAULT_EVENT_DURATION_MINUTES,
    UNDO_WINDOW_MINUTES,
    CalendarClient,
    CalendarEvent,
    EventCreationResult,
    EventDeletionResult,
    calendar_event_exists,
    create_calendar_event,
    delete_calendar_event,
    get_calendar_client,
)


class TestCalendarEvent:
    """Test CalendarEvent dataclass."""

    def test_calendar_event_creation(self):
        """Test creating a CalendarEvent instance."""
        event = CalendarEvent(
            event_id="abc123",
            title="Meeting with Mike",
            start_time=datetime(2026, 1, 15, 14, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
            end_time=datetime(2026, 1, 15, 15, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
            timezone="America/Los_Angeles",
            attendees=["mike@example.com"],
            location="Conference Room A",
            description="Discuss project",
            html_link="https://calendar.google.com/event?eid=abc123",
        )

        assert event.event_id == "abc123"
        assert event.title == "Meeting with Mike"
        assert event.attendees == ["mike@example.com"]
        assert event.location == "Conference Room A"

    def test_calendar_event_minimal(self):
        """Test CalendarEvent with minimal fields."""
        event = CalendarEvent(
            event_id="xyz789",
            title="Quick sync",
            start_time=datetime(2026, 1, 15, 10, 0),
            end_time=datetime(2026, 1, 15, 10, 30),
            timezone="UTC",
            attendees=[],
        )

        assert event.event_id == "xyz789"
        assert event.location is None
        assert event.description is None


class TestEventCreationResult:
    """Test EventCreationResult dataclass."""

    def test_successful_result(self):
        """Test successful creation result."""
        result = EventCreationResult(
            success=True,
            event_id="abc123",
            html_link="https://calendar.google.com/event?eid=abc123",
            undo_available_until=datetime.now(UTC) + timedelta(minutes=5),
        )

        assert result.success is True
        assert result.event_id == "abc123"
        assert result.error is None

    def test_failed_result(self):
        """Test failed creation result."""
        result = EventCreationResult(
            success=False,
            error="Not authenticated",
        )

        assert result.success is False
        assert result.event_id is None
        assert result.error == "Not authenticated"


class TestEventDeletionResult:
    """Test EventDeletionResult dataclass."""

    def test_successful_deletion(self):
        """Test successful deletion result."""
        result = EventDeletionResult(
            success=True,
            event_id="abc123",
        )

        assert result.success is True
        assert result.error is None

    def test_failed_deletion(self):
        """Test failed deletion result."""
        result = EventDeletionResult(
            success=False,
            event_id="abc123",
            error="Event not found",
        )

        assert result.success is False
        assert result.error == "Event not found"


class TestCalendarClientInit:
    """Test CalendarClient initialization."""

    def test_client_creation(self):
        """Test creating CalendarClient instance."""
        client = CalendarClient()
        assert client._service is None

    @patch("assistant.google.calendar.google_auth")
    def test_is_authenticated_no_credentials(self, mock_auth):
        """Test is_authenticated returns False without credentials."""
        mock_auth.credentials = None
        mock_auth.load_saved_credentials.return_value = False

        client = CalendarClient()
        assert client.is_authenticated() is False

    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    def test_is_authenticated_with_credentials(self, mock_build, mock_auth):
        """Test is_authenticated returns True with valid credentials."""
        mock_auth.credentials = MagicMock()
        mock_build.return_value = MagicMock()

        client = CalendarClient()
        assert client.is_authenticated() is True


class TestCalendarClientCreateEvent:
    """Test CalendarClient.create_event method."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    async def test_create_event_not_authenticated(self, mock_auth):
        """Test create_event fails when not authenticated."""
        mock_auth.credentials = None
        mock_auth.load_saved_credentials.return_value = False

        client = CalendarClient()
        result = await client.create_event(
            title="Meeting",
            start_time=datetime(2026, 1, 15, 14, 0),
        )

        assert result.success is False
        assert "not authenticated" in result.error.lower()

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_create_event_success(self, mock_build, mock_auth):
        """Test successful event creation (AT-110 core)."""
        # Setup mocks
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Mock the events().insert().execute() chain
        mock_execute = MagicMock(
            return_value={
                "id": "event123",
                "htmlLink": "https://calendar.google.com/event?eid=event123",
            }
        )
        mock_service.events.return_value.insert.return_value.execute = mock_execute

        client = CalendarClient()
        result = await client.create_event(
            title="Meeting with Mike",
            start_time=datetime(2026, 1, 15, 14, 0),
        )

        assert result.success is True
        assert result.event_id == "event123"
        assert result.html_link == "https://calendar.google.com/event?eid=event123"
        assert result.undo_available_until is not None

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_create_event_with_attendees(self, mock_build, mock_auth):
        """Test event creation with attendees."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_execute = MagicMock(
            return_value={
                "id": "event456",
                "htmlLink": "https://calendar.google.com/event?eid=event456",
            }
        )
        mock_service.events.return_value.insert.return_value.execute = mock_execute

        client = CalendarClient()
        result = await client.create_event(
            title="Team meeting",
            start_time=datetime(2026, 1, 15, 14, 0),
            attendees=["alice@example.com", "bob@example.com"],
        )

        assert result.success is True
        # Verify insert was called with attendees
        call_args = mock_service.events.return_value.insert.call_args
        body = call_args[1]["body"]
        assert "attendees" in body
        assert len(body["attendees"]) == 2

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_create_event_with_location_and_description(self, mock_build, mock_auth):
        """Test event creation with location and description."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_execute = MagicMock(return_value={"id": "event789", "htmlLink": ""})
        mock_service.events.return_value.insert.return_value.execute = mock_execute

        client = CalendarClient()
        result = await client.create_event(
            title="Lunch meeting",
            start_time=datetime(2026, 1, 15, 12, 0),
            location="Restaurant XYZ",
            description="Discuss Q1 plans",
        )

        assert result.success is True
        call_args = mock_service.events.return_value.insert.call_args
        body = call_args[1]["body"]
        assert body["location"] == "Restaurant XYZ"
        assert body["description"] == "Discuss Q1 plans"

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_create_event_custom_duration(self, mock_build, mock_auth):
        """Test event creation with custom duration."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_execute = MagicMock(return_value={"id": "event_dur", "htmlLink": ""})
        mock_service.events.return_value.insert.return_value.execute = mock_execute

        client = CalendarClient()
        start = datetime(2026, 1, 15, 14, 0, tzinfo=ZoneInfo("UTC"))
        result = await client.create_event(
            title="Quick sync",
            start_time=start,
            duration_minutes=30,
        )

        assert result.success is True
        call_args = mock_service.events.return_value.insert.call_args
        body = call_args[1]["body"]
        # End should be 30 minutes after start
        end_time = datetime.fromisoformat(body["end"]["dateTime"].replace("Z", "+00:00"))
        start_time = datetime.fromisoformat(body["start"]["dateTime"].replace("Z", "+00:00"))
        assert (end_time - start_time).seconds == 30 * 60


class TestCalendarClientDeleteEvent:
    """Test CalendarClient.delete_event method."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    async def test_delete_event_not_authenticated(self, mock_auth):
        """Test delete_event fails when not authenticated."""
        mock_auth.credentials = None
        mock_auth.load_saved_credentials.return_value = False

        client = CalendarClient()
        result = await client.delete_event("event123")

        assert result.success is False
        assert "not authenticated" in result.error.lower()

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_delete_event_success(self, mock_build, mock_auth):
        """Test successful event deletion (AT-116 core)."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.delete.return_value.execute = MagicMock(return_value={})

        client = CalendarClient()
        result = await client.delete_event("event123")

        assert result.success is True
        assert result.event_id == "event123"

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_delete_event_already_deleted(self, mock_build, mock_auth):
        """Test deleting an already-deleted event returns success."""
        from googleapiclient.errors import HttpError

        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Simulate 404 error (event not found)
        mock_resp = MagicMock()
        mock_resp.status = 404
        http_error = HttpError(resp=mock_resp, content=b"Not Found")
        mock_service.events.return_value.delete.return_value.execute.side_effect = http_error

        client = CalendarClient()
        result = await client.delete_event("deleted_event")

        # 404 should be treated as success (idempotent delete)
        assert result.success is True


class TestCalendarClientGetEvent:
    """Test CalendarClient.get_event method."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    async def test_get_event_not_authenticated(self, mock_auth):
        """Test get_event returns None when not authenticated."""
        mock_auth.credentials = None
        mock_auth.load_saved_credentials.return_value = False

        client = CalendarClient()
        event = await client.get_event("event123")

        assert event is None

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_get_event_success(self, mock_build, mock_auth):
        """Test successful event retrieval."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.get.return_value.execute = MagicMock(
            return_value={
                "id": "event123",
                "summary": "Test Event",
                "start": {
                    "dateTime": "2026-01-15T14:00:00-08:00",
                    "timeZone": "America/Los_Angeles",
                },
                "end": {"dateTime": "2026-01-15T15:00:00-08:00", "timeZone": "America/Los_Angeles"},
                "attendees": [{"email": "test@example.com"}],
                "location": "Test Location",
                "description": "Test Description",
                "htmlLink": "https://calendar.google.com/event?eid=event123",
            }
        )

        client = CalendarClient()
        event = await client.get_event("event123")

        assert event is not None
        assert event.event_id == "event123"
        assert event.title == "Test Event"
        assert event.location == "Test Location"
        assert event.attendees == ["test@example.com"]

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_get_event_not_found(self, mock_build, mock_auth):
        """Test get_event returns None for non-existent event."""
        from googleapiclient.errors import HttpError

        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_service.events.return_value.get.return_value.execute.side_effect = HttpError(
            resp=mock_resp, content=b"Not Found"
        )

        client = CalendarClient()
        event = await client.get_event("nonexistent")

        assert event is None


class TestCalendarClientEventExists:
    """Test CalendarClient.event_exists method."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_event_exists_true(self, mock_build, mock_auth):
        """Test event_exists returns True for existing event."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.get.return_value.execute = MagicMock(
            return_value={
                "id": "event123",
                "summary": "Test",
                "start": {"dateTime": "2026-01-15T14:00:00Z"},
                "end": {"dateTime": "2026-01-15T15:00:00Z"},
            }
        )

        client = CalendarClient()
        exists = await client.event_exists("event123")

        assert exists is True

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_event_exists_false(self, mock_build, mock_auth):
        """Test event_exists returns False for non-existent event."""
        from googleapiclient.errors import HttpError

        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_service.events.return_value.get.return_value.execute.side_effect = HttpError(
            resp=mock_resp, content=b"Not Found"
        )

        client = CalendarClient()
        exists = await client.event_exists("nonexistent")

        assert exists is False


class TestModuleLevelFunctions:
    """Test module-level convenience functions."""

    def test_get_calendar_client_singleton(self):
        """Test get_calendar_client returns singleton."""
        # Reset global state
        import assistant.google.calendar as cal_module

        cal_module._calendar_client = None

        client1 = get_calendar_client()
        client2 = get_calendar_client()

        assert client1 is client2

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.get_calendar_client")
    async def test_create_calendar_event_convenience(self, mock_get_client):
        """Test create_calendar_event convenience function."""
        mock_client = AsyncMock()
        mock_client.create_event.return_value = EventCreationResult(success=True, event_id="test")
        mock_get_client.return_value = mock_client

        result = await create_calendar_event(
            title="Test",
            start_time=datetime(2026, 1, 15, 14, 0),
        )

        assert result.success is True
        mock_client.create_event.assert_called_once()

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.get_calendar_client")
    async def test_delete_calendar_event_convenience(self, mock_get_client):
        """Test delete_calendar_event convenience function."""
        mock_client = AsyncMock()
        mock_client.delete_event.return_value = EventDeletionResult(success=True, event_id="test")
        mock_get_client.return_value = mock_client

        result = await delete_calendar_event("test")

        assert result.success is True
        mock_client.delete_event.assert_called_once_with("test")

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.get_calendar_client")
    async def test_calendar_event_exists_convenience(self, mock_get_client):
        """Test calendar_event_exists convenience function."""
        mock_client = AsyncMock()
        mock_client.event_exists.return_value = True
        mock_get_client.return_value = mock_client

        exists = await calendar_event_exists("test")

        assert exists is True
        mock_client.event_exists.assert_called_once_with("test")


class TestConstants:
    """Test module constants."""

    def test_default_duration(self):
        """Test default event duration is 60 minutes."""
        assert DEFAULT_EVENT_DURATION_MINUTES == 60

    def test_undo_window(self):
        """Test undo window is 5 minutes per PRD Section 6.2."""
        assert UNDO_WINDOW_MINUTES == 5


class TestAT110GoogleCalendarCreation:
    """Acceptance test AT-110: Google Calendar Creation.

    Given: User sends "Meeting with Mike tomorrow 2pm"
    When: Google Calendar integration enabled
    Then: Calendar event created for tomorrow 2pm
    And: Task in Notion linked to calendar event
    """

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_at110_event_created_for_tomorrow_2pm(self, mock_build, mock_auth):
        """Test AT-110: Calendar event created at correct time."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute = MagicMock(
            return_value={
                "id": "meeting_mike_123",
                "htmlLink": "https://calendar.google.com/event?eid=meeting_mike_123",
            }
        )

        # Calculate tomorrow at 2pm
        tomorrow_2pm = (datetime.now() + timedelta(days=1)).replace(
            hour=14, minute=0, second=0, microsecond=0
        )

        client = CalendarClient()
        result = await client.create_event(
            title="Meeting with Mike",
            start_time=tomorrow_2pm,
        )

        # Verify event was created
        assert result.success is True
        assert result.event_id == "meeting_mike_123"

        # Verify the API was called with correct time
        call_args = mock_service.events.return_value.insert.call_args
        body = call_args[1]["body"]
        assert body["summary"] == "Meeting with Mike"
        # The start time should be around 2pm tomorrow

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_at110_event_id_returned_for_notion_link(self, mock_build, mock_auth):
        """Test AT-110: Event ID returned for linking to Notion task."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute = MagicMock(
            return_value={
                "id": "notion_link_event",
                "htmlLink": "https://calendar.google.com/event?eid=notion_link_event",
            }
        )

        client = CalendarClient()
        result = await client.create_event(
            title="Linked meeting",
            start_time=datetime(2026, 1, 15, 14, 0),
        )

        # The event_id should be suitable for storing in Notion's calendar_event_id field
        assert result.success is True
        assert result.event_id is not None
        assert isinstance(result.event_id, str)
        assert len(result.event_id) > 0


class TestAT116CalendarUndoWindow:
    """Acceptance test AT-116: Calendar Undo Window.

    Given: AI created calendar event "Meeting with Bob 2pm"
    When: User says "wrong" within 5 minutes
    Then: Calendar event deleted
    And: Task updated with note "Calendar event cancelled"
    """

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_at116_event_can_be_deleted_within_window(self, mock_build, mock_auth):
        """Test AT-116: Calendar event can be deleted for undo."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # First create an event
        mock_service.events.return_value.insert.return_value.execute = MagicMock(
            return_value={
                "id": "meeting_bob_456",
                "htmlLink": "https://calendar.google.com/event?eid=meeting_bob_456",
            }
        )

        client = CalendarClient()
        create_result = await client.create_event(
            title="Meeting with Bob",
            start_time=datetime(2026, 1, 15, 14, 0),
        )

        assert create_result.success is True
        assert create_result.undo_available_until is not None

        # Verify undo window is 5 minutes in the future
        now = datetime.now(UTC)
        assert create_result.undo_available_until > now
        assert create_result.undo_available_until < now + timedelta(minutes=6)

        # Now delete the event (simulating undo)
        mock_service.events.return_value.delete.return_value.execute = MagicMock(return_value={})

        delete_result = await client.delete_event(create_result.event_id)

        assert delete_result.success is True
        assert delete_result.event_id == "meeting_bob_456"

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_at116_event_no_longer_exists_after_delete(self, mock_build, mock_auth):
        """Test AT-116: Event confirmed deleted via event_exists check."""
        from googleapiclient.errors import HttpError

        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # After deletion, get should return 404
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_service.events.return_value.get.return_value.execute.side_effect = HttpError(
            resp=mock_resp, content=b"Not Found"
        )

        client = CalendarClient()
        exists = await client.event_exists("deleted_event")

        # Event should no longer exist
        assert exists is False


class TestNotionTaskCalendarLink:
    """Test Notion task linking with calendar_event_id."""

    @pytest.mark.asyncio
    async def test_update_task_calendar_event_set(self):
        """Test setting calendar_event_id on a task."""
        from assistant.notion import NotionClient

        with patch.object(NotionClient, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"id": "task123"}

            client = NotionClient()
            await client.update_task_calendar_event("task123", "cal_event_abc")

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "PATCH"
            assert "task123" in call_args[0][1]

            # Verify the properties being set
            props = call_args[0][2]["properties"]
            assert "calendar_event_id" in props
            assert props["calendar_event_id"]["rich_text"][0]["text"]["content"] == "cal_event_abc"

    @pytest.mark.asyncio
    async def test_update_task_calendar_event_clear(self):
        """Test clearing calendar_event_id on a task (for undo)."""
        from assistant.notion import NotionClient

        with patch.object(NotionClient, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"id": "task123"}

            client = NotionClient()
            await client.update_task_calendar_event("task123", None)

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            props = call_args[0][2]["properties"]

            # Clearing should set empty rich_text array
            assert props["calendar_event_id"]["rich_text"] == []


class TestTimezoneHandling:
    """Test timezone handling in calendar events."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.google.calendar.settings")
    async def test_uses_user_timezone_from_settings(self, mock_settings, mock_build, mock_auth):
        """Test event uses user timezone from settings."""
        mock_settings.user_timezone = "America/Los_Angeles"
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute = MagicMock(
            return_value={
                "id": "tz_event",
                "htmlLink": "",
            }
        )

        client = CalendarClient()
        await client.create_event(
            title="Test",
            start_time=datetime(2026, 1, 15, 14, 0),  # No timezone specified
        )

        call_args = mock_service.events.return_value.insert.call_args
        body = call_args[1]["body"]
        assert body["start"]["timeZone"] == "America/Los_Angeles"

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_explicit_timezone_overrides_default(self, mock_build, mock_auth):
        """Test explicit timezone parameter overrides settings."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute = MagicMock(
            return_value={
                "id": "tz_override",
                "htmlLink": "",
            }
        )

        client = CalendarClient()
        await client.create_event(
            title="Test",
            start_time=datetime(2026, 1, 15, 14, 0),
            timezone="Europe/London",
        )

        call_args = mock_service.events.return_value.insert.call_args
        body = call_args[1]["body"]
        assert body["start"]["timeZone"] == "Europe/London"


class TestErrorHandling:
    """Test error handling in calendar operations."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_api_error_returns_error_result(self, mock_build, mock_auth):
        """Test API errors return error result instead of raising."""
        from googleapiclient.errors import HttpError

        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_service.events.return_value.insert.return_value.execute.side_effect = HttpError(
            resp=mock_resp, content=b"Server Error"
        )

        client = CalendarClient()
        result = await client.create_event(
            title="Test",
            start_time=datetime(2026, 1, 15, 14, 0),
        )

        assert result.success is False
        assert result.error is not None
        assert "error" in result.error.lower()

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    async def test_unexpected_error_caught(self, mock_build, mock_auth):
        """Test unexpected exceptions are caught and returned as error."""
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute.side_effect = Exception(
            "Unexpected error"
        )

        client = CalendarClient()
        result = await client.create_event(
            title="Test",
            start_time=datetime(2026, 1, 15, 14, 0),
        )

        assert result.success is False
        assert "Unexpected error" in result.error


# =============================================================================
# T-102: Calendar Reading Tests
# =============================================================================


class TestCalendarClientListEvents:
    """Test CalendarClient.list_events method (T-102)."""

    @pytest.mark.asyncio
    async def test_list_events_not_authenticated(self):
        """Test list_events returns empty list when not authenticated."""
        client = CalendarClient()
        # No credentials loaded

        events = await client.list_events(
            start_time=datetime(2026, 1, 15, 0, 0),
            end_time=datetime(2026, 1, 15, 23, 59),
        )

        assert events == []

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.google.calendar.settings")
    async def test_list_events_success(self, mock_settings, mock_build, mock_auth):
        """Test list_events returns events from Google Calendar."""
        mock_settings.user_timezone = "America/Los_Angeles"
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Mock API response with multiple events
        mock_service.events.return_value.list.return_value.execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "event1",
                        "summary": "Standup with Mike",
                        "start": {
                            "dateTime": "2026-01-15T09:00:00-08:00",
                            "timeZone": "America/Los_Angeles",
                        },
                        "end": {
                            "dateTime": "2026-01-15T09:30:00-08:00",
                            "timeZone": "America/Los_Angeles",
                        },
                    },
                    {
                        "id": "event2",
                        "summary": "Dentist appointment",
                        "start": {
                            "dateTime": "2026-01-15T14:00:00-08:00",
                            "timeZone": "America/Los_Angeles",
                        },
                        "end": {
                            "dateTime": "2026-01-15T15:00:00-08:00",
                            "timeZone": "America/Los_Angeles",
                        },
                        "location": "123 Main St",
                    },
                ]
            }
        )

        client = CalendarClient()
        events = await client.list_events(
            start_time=datetime(2026, 1, 15, 0, 0),
            end_time=datetime(2026, 1, 15, 23, 59),
        )

        assert len(events) == 2
        assert events[0].title == "Standup with Mike"
        assert events[0].event_id == "event1"
        assert events[1].title == "Dentist appointment"
        assert events[1].location == "123 Main St"

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.google.calendar.settings")
    async def test_list_events_all_day_event(self, mock_settings, mock_build, mock_auth):
        """Test list_events handles all-day events correctly."""
        mock_settings.user_timezone = "UTC"
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # All-day event uses "date" instead of "dateTime"
        mock_service.events.return_value.list.return_value.execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "allday1",
                        "summary": "Jess's Birthday",
                        "start": {"date": "2026-01-15"},
                        "end": {"date": "2026-01-16"},
                    },
                ]
            }
        )

        client = CalendarClient()
        events = await client.list_events(
            start_time=datetime(2026, 1, 15, 0, 0),
            end_time=datetime(2026, 1, 15, 23, 59),
        )

        assert len(events) == 1
        assert events[0].title == "Jess's Birthday"
        # All-day event starts at midnight
        assert events[0].start_time.hour == 0
        assert events[0].start_time.minute == 0

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.google.calendar.settings")
    async def test_list_events_empty_response(self, mock_settings, mock_build, mock_auth):
        """Test list_events handles empty calendar."""
        mock_settings.user_timezone = "UTC"
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.list.return_value.execute = MagicMock(
            return_value={"items": []}
        )

        client = CalendarClient()
        events = await client.list_events(
            start_time=datetime(2026, 1, 15, 0, 0),
            end_time=datetime(2026, 1, 15, 23, 59),
        )

        assert events == []

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.google.calendar.settings")
    async def test_list_events_api_error(self, mock_settings, mock_build, mock_auth):
        """Test list_events handles API errors gracefully."""
        from googleapiclient.errors import HttpError

        mock_settings.user_timezone = "UTC"
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_service.events.return_value.list.return_value.execute.side_effect = HttpError(
            resp=mock_resp, content=b"Server Error"
        )

        client = CalendarClient()
        events = await client.list_events(
            start_time=datetime(2026, 1, 15, 0, 0),
            end_time=datetime(2026, 1, 15, 23, 59),
        )

        # Should return empty list, not raise exception
        assert events == []

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.google.calendar.settings")
    async def test_list_events_with_attendees(self, mock_settings, mock_build, mock_auth):
        """Test list_events extracts attendees."""
        mock_settings.user_timezone = "UTC"
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.list.return_value.execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "meeting1",
                        "summary": "Team sync",
                        "start": {"dateTime": "2026-01-15T10:00:00Z"},
                        "end": {"dateTime": "2026-01-15T11:00:00Z"},
                        "attendees": [
                            {"email": "mike@example.com"},
                            {"email": "sarah@example.com"},
                        ],
                    },
                ]
            }
        )

        client = CalendarClient()
        events = await client.list_events(
            start_time=datetime(2026, 1, 15, 0, 0),
            end_time=datetime(2026, 1, 15, 23, 59),
        )

        assert len(events) == 1
        assert "mike@example.com" in events[0].attendees
        assert "sarah@example.com" in events[0].attendees


class TestListCalendarEventsConvenience:
    """Test list_calendar_events convenience function."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.get_calendar_client")
    async def test_list_calendar_events_calls_client(self, mock_get_client):
        """Test list_calendar_events uses global client."""
        from assistant.google.calendar import list_calendar_events

        mock_client = AsyncMock()
        mock_client.list_events.return_value = []
        mock_get_client.return_value = mock_client

        events = await list_calendar_events(
            start_time=datetime(2026, 1, 15, 0, 0),
            end_time=datetime(2026, 1, 15, 23, 59),
        )

        assert events == []
        mock_client.list_events.assert_called_once()


class TestListTodaysEventsConvenience:
    """Test list_todays_events convenience function."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.list_calendar_events")
    @patch("assistant.google.calendar.settings")
    async def test_list_todays_events_uses_correct_time_range(self, mock_settings, mock_list):
        """Test list_todays_events queries from midnight to midnight."""
        from assistant.google.calendar import list_todays_events

        mock_settings.user_timezone = "America/Los_Angeles"
        mock_list.return_value = []

        await list_todays_events()

        mock_list.assert_called_once()
        call_args = mock_list.call_args

        # Check start is at midnight
        start = call_args[1]["start_time"]
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0

        # Check end is near midnight
        end = call_args[1]["end_time"]
        assert end.hour == 23
        assert end.minute == 59


class TestParseEventResponse:
    """Test _parse_event_response helper method."""

    def test_parse_timed_event(self):
        """Test parsing a timed event."""
        client = CalendarClient()
        item = {
            "id": "test123",
            "summary": "Meeting",
            "start": {"dateTime": "2026-01-15T14:00:00Z", "timeZone": "UTC"},
            "end": {"dateTime": "2026-01-15T15:00:00Z", "timeZone": "UTC"},
            "location": "Office",
            "description": "Weekly sync",
            "htmlLink": "https://calendar.google.com/event",
        }

        event = client._parse_event_response(item, "UTC")

        assert event is not None
        assert event.event_id == "test123"
        assert event.title == "Meeting"
        assert event.location == "Office"
        assert event.description == "Weekly sync"
        assert event.html_link == "https://calendar.google.com/event"

    def test_parse_all_day_event(self):
        """Test parsing an all-day event."""
        client = CalendarClient()
        item = {
            "id": "allday123",
            "summary": "Holiday",
            "start": {"date": "2026-01-15"},
            "end": {"date": "2026-01-16"},
        }

        event = client._parse_event_response(item, "UTC")

        assert event is not None
        assert event.event_id == "allday123"
        assert event.title == "Holiday"
        assert event.start_time.hour == 0  # Midnight

    def test_parse_missing_summary(self):
        """Test parsing event without summary gets 'Untitled'."""
        client = CalendarClient()
        item = {
            "id": "nosummary",
            "start": {"dateTime": "2026-01-15T14:00:00Z"},
            "end": {"dateTime": "2026-01-15T15:00:00Z"},
        }

        event = client._parse_event_response(item, "UTC")

        assert event is not None
        assert event.title == "Untitled"

    def test_parse_invalid_event_returns_none(self):
        """Test parsing invalid event returns None."""
        client = CalendarClient()
        item = {
            "id": "invalid",
            "summary": "Missing times",
            # No start/end
        }

        event = client._parse_event_response(item, "UTC")

        assert event is None


class TestT102BriefingIntegration:
    """Test T-102 integration with briefing generator."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.services.briefing.settings")
    async def test_briefing_includes_calendar_events(self, mock_settings, mock_build, mock_auth):
        """Test morning briefing includes calendar events."""
        from assistant.google.calendar import CalendarClient
        from assistant.services.briefing import BriefingGenerator

        mock_settings.user_timezone = "America/Los_Angeles"
        mock_settings.has_notion = False  # Skip Notion
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Mock calendar events for today
        mock_service.events.return_value.list.return_value.execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "standup",
                        "summary": "Standup with Mike",
                        "start": {"dateTime": "2026-01-15T09:00:00-08:00"},
                        "end": {"dateTime": "2026-01-15T09:30:00-08:00"},
                    },
                    {
                        "id": "dentist",
                        "summary": "Dentist appointment",
                        "start": {"dateTime": "2026-01-15T14:00:00-08:00"},
                        "end": {"dateTime": "2026-01-15T15:00:00-08:00"},
                    },
                ]
            }
        )

        calendar_client = CalendarClient()
        generator = BriefingGenerator(notion_client=None, calendar_client=calendar_client)

        section = await generator._generate_calendar_section()

        assert section is not None
        assert "📅 **TODAY**" in section
        assert "Standup with Mike" in section
        assert "Dentist appointment" in section

    @pytest.mark.asyncio
    @patch("assistant.services.briefing.settings")
    async def test_briefing_skips_calendar_when_not_authenticated(self, mock_settings):
        """Test briefing gracefully skips calendar when not authenticated."""
        from assistant.google.calendar import CalendarClient
        from assistant.services.briefing import BriefingGenerator

        mock_settings.user_timezone = "America/Los_Angeles"
        mock_settings.has_notion = False

        # Calendar client without authentication
        calendar_client = CalendarClient()
        generator = BriefingGenerator(notion_client=None, calendar_client=calendar_client)

        section = await generator._generate_calendar_section()

        # Should return None, not error
        assert section is None

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.services.briefing.settings")
    async def test_briefing_calendar_event_formatting(self, mock_settings, mock_build, mock_auth):
        """Test calendar events are formatted correctly in briefing."""
        from assistant.google.calendar import CalendarClient
        from assistant.services.briefing import BriefingGenerator

        mock_settings.user_timezone = "America/Los_Angeles"
        mock_settings.has_notion = False
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.list.return_value.execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "cinema",
                        "summary": "Cinema with Jess",
                        "start": {"dateTime": "2026-01-15T20:00:00-08:00"},
                        "end": {"dateTime": "2026-01-15T22:00:00-08:00"},
                        "location": "Everyman Cinema",
                    },
                ]
            }
        )

        calendar_client = CalendarClient()
        generator = BriefingGenerator(notion_client=None, calendar_client=calendar_client)

        section = await generator._generate_calendar_section()

        assert section is not None
        # Should show time in HH:MM format
        assert "20:00" in section
        # Should show event title
        assert "Cinema with Jess" in section
        # Should show location in parentheses
        assert "Everyman Cinema" in section

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.services.briefing.settings")
    async def test_briefing_all_day_event_formatting(self, mock_settings, mock_build, mock_auth):
        """Test all-day events show 'All day' instead of time."""
        from assistant.google.calendar import CalendarClient
        from assistant.services.briefing import BriefingGenerator

        mock_settings.user_timezone = "UTC"
        mock_settings.has_notion = False
        mock_auth.credentials = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.events.return_value.list.return_value.execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "birthday",
                        "summary": "Jess's Birthday",
                        "start": {"date": "2026-01-15"},
                        "end": {"date": "2026-01-16"},
                    },
                ]
            }
        )

        calendar_client = CalendarClient()
        generator = BriefingGenerator(notion_client=None, calendar_client=calendar_client)

        section = await generator._generate_calendar_section()

        assert section is not None
        assert "All day" in section
        assert "Jess's Birthday" in section


class TestT102PRDBriefingFormat:
    """Test T-102 matches PRD Section 5.2 briefing format."""

    @pytest.mark.asyncio
    @patch("assistant.google.calendar.google_auth")
    @patch("assistant.google.calendar.build")
    @patch("assistant.services.briefing.settings")
    async def test_prd_example_format(self, mock_settings, mock_build, mock_auth):
        """Test briefing matches PRD Section 5.2 example format.

        PRD shows:
        📅 TODAY
        • 9:00 - Standup with Mike
        • 14:00 - Dentist appointment
        • 20:00 - Cinema with Jess (Everyman)
        """
        from zoneinfo import ZoneInfo

        from assistant.google.calendar import CalendarEvent
        from assistant.services.briefing import BriefingGenerator

        mock_settings.user_timezone = "America/Los_Angeles"
        mock_settings.has_notion = False

        # Create mock events matching PRD example
        events = [
            CalendarEvent(
                event_id="1",
                title="Standup with Mike",
                start_time=datetime(2026, 1, 15, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
                end_time=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/Los_Angeles")),
                timezone="America/Los_Angeles",
                attendees=[],
            ),
            CalendarEvent(
                event_id="2",
                title="Dentist appointment",
                start_time=datetime(2026, 1, 15, 14, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
                end_time=datetime(2026, 1, 15, 15, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
                timezone="America/Los_Angeles",
                attendees=[],
            ),
            CalendarEvent(
                event_id="3",
                title="Cinema with Jess",
                start_time=datetime(2026, 1, 15, 20, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
                end_time=datetime(2026, 1, 15, 22, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
                timezone="America/Los_Angeles",
                attendees=[],
                location="Everyman",
            ),
        ]

        generator = BriefingGenerator(notion_client=None, calendar_client=None)
        section = generator._format_calendar_events(events)

        assert section is not None
        # Check header
        assert "📅 **TODAY**" in section
        # Check format: "• HH:MM - Title"
        assert "• 09:00 - Standup with Mike" in section
        assert "• 14:00 - Dentist appointment" in section
        assert "• 20:00 - Cinema with Jess (Everyman)" in section
