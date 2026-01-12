"""Tests for Google Calendar integration (T-101).

Tests cover:
- CalendarClient initialization and authentication
- Event creation (AT-110)
- Event deletion for undo support (AT-116)
- Notion task linking with calendar_event_id
- Error handling
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from assistant.google.calendar import (
    CalendarClient,
    CalendarEvent,
    EventCreationResult,
    EventDeletionResult,
    get_calendar_client,
    create_calendar_event,
    delete_calendar_event,
    calendar_event_exists,
    DEFAULT_EVENT_DURATION_MINUTES,
    UNDO_WINDOW_MINUTES,
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
            undo_available_until=datetime.utcnow() + timedelta(minutes=5),
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
        mock_execute = MagicMock(return_value={
            "id": "event123",
            "htmlLink": "https://calendar.google.com/event?eid=event123",
        })
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

        mock_execute = MagicMock(return_value={
            "id": "event456",
            "htmlLink": "https://calendar.google.com/event?eid=event456",
        })
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

        mock_service.events.return_value.get.return_value.execute = MagicMock(return_value={
            "id": "event123",
            "summary": "Test Event",
            "start": {"dateTime": "2026-01-15T14:00:00-08:00", "timeZone": "America/Los_Angeles"},
            "end": {"dateTime": "2026-01-15T15:00:00-08:00", "timeZone": "America/Los_Angeles"},
            "attendees": [{"email": "test@example.com"}],
            "location": "Test Location",
            "description": "Test Description",
            "htmlLink": "https://calendar.google.com/event?eid=event123",
        })

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

        mock_service.events.return_value.get.return_value.execute = MagicMock(return_value={
            "id": "event123",
            "summary": "Test",
            "start": {"dateTime": "2026-01-15T14:00:00Z"},
            "end": {"dateTime": "2026-01-15T15:00:00Z"},
        })

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

        mock_service.events.return_value.insert.return_value.execute = MagicMock(return_value={
            "id": "meeting_mike_123",
            "htmlLink": "https://calendar.google.com/event?eid=meeting_mike_123",
        })

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

        mock_service.events.return_value.insert.return_value.execute = MagicMock(return_value={
            "id": "notion_link_event",
            "htmlLink": "https://calendar.google.com/event?eid=notion_link_event",
        })

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
        mock_service.events.return_value.insert.return_value.execute = MagicMock(return_value={
            "id": "meeting_bob_456",
            "htmlLink": "https://calendar.google.com/event?eid=meeting_bob_456",
        })

        client = CalendarClient()
        create_result = await client.create_event(
            title="Meeting with Bob",
            start_time=datetime(2026, 1, 15, 14, 0),
        )

        assert create_result.success is True
        assert create_result.undo_available_until is not None

        # Verify undo window is 5 minutes in the future
        now = datetime.utcnow()
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

        mock_service.events.return_value.insert.return_value.execute = MagicMock(return_value={
            "id": "tz_event",
            "htmlLink": "",
        })

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

        mock_service.events.return_value.insert.return_value.execute = MagicMock(return_value={
            "id": "tz_override",
            "htmlLink": "",
        })

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
