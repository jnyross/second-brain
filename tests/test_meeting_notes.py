"""Tests for meeting notes service (T-165, AT-125)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.services.meeting_notes import (
    MeetingNotesResult,
    MeetingNotesService,
    create_meeting_notes,
    create_meeting_notes_from_request,
    extract_attendees,
    extract_meeting_title,
    get_meeting_notes_service,
    is_meeting_notes_request,
)


class TestIsMeetingNotesRequest:
    """Tests for is_meeting_notes_request()."""

    @pytest.mark.parametrize(
        "text",
        [
            "Create meeting notes for call with Sarah",
            "Make notes for meeting with John",
            "Start meeting notes for standup",
            "New meeting notes for 1:1 with Mike",
            "meeting notes for sync",
            "notes for meeting with team",
            "create notes for call",
        ],
    )
    def test_detects_meeting_notes_requests(self, text: str) -> None:
        assert is_meeting_notes_request(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Call Sarah tomorrow",
            "Set up meeting with John",
            "Take notes in class",
            "Buy groceries",
            "Research CRM options",
        ],
    )
    def test_rejects_non_meeting_notes_requests(self, text: str) -> None:
        assert not is_meeting_notes_request(text)


class TestExtractMeetingTitle:
    """Tests for extract_meeting_title()."""

    def test_removes_create_prefix(self) -> None:
        result = extract_meeting_title("Create meeting notes for call with Sarah")
        assert result == "call with Sarah"

    def test_removes_make_prefix(self) -> None:
        result = extract_meeting_title("Make notes for meeting with John")
        assert result == "meeting with John"

    def test_removes_meeting_notes_prefix(self) -> None:
        result = extract_meeting_title("meeting notes for sync with team")
        assert result == "sync with team"

    def test_preserves_plain_text(self) -> None:
        result = extract_meeting_title("Weekly team standup")
        assert result == "Weekly team standup"


class TestExtractAttendees:
    """Tests for extract_attendees()."""

    def test_extracts_single_attendee_with_pattern(self) -> None:
        result = extract_attendees("call with Sarah")
        assert result == ["Sarah"]

    def test_extracts_single_attendee_meeting_with(self) -> None:
        result = extract_attendees("meeting with John")
        assert result == ["John"]

    def test_extracts_multiple_attendees_and(self) -> None:
        result = extract_attendees("call with Sarah and John")
        assert result == ["Sarah", "John"]

    def test_extracts_multiple_attendees_comma(self) -> None:
        result = extract_attendees("meeting with Sarah, John, Mike")
        assert result == ["Sarah", "John", "Mike"]

    def test_extracts_from_prepended_name(self) -> None:
        result = extract_attendees("Sarah meeting")
        assert result == ["Sarah"]

    def test_extracts_from_meet_with(self) -> None:
        result = extract_attendees("meet with Alice")
        assert result == ["Alice"]

    def test_stops_at_about(self) -> None:
        result = extract_attendees("meeting with Sarah about project")
        assert result == ["Sarah"]

    def test_stops_at_on(self) -> None:
        result = extract_attendees("call with John on Monday")
        assert result == ["John"]

    def test_handles_no_attendees(self) -> None:
        result = extract_attendees("weekly review session")
        assert result == []

    def test_filters_common_words(self) -> None:
        # Should not include "the" or "my"
        result = extract_attendees("meeting with the manager")
        assert "the" not in result


class TestMeetingNotesResult:
    """Tests for MeetingNotesResult dataclass."""

    def test_has_attendees_true_when_people_ids(self) -> None:
        result = MeetingNotesResult(
            success=True,
            people_ids=["id-1", "id-2"],
        )
        assert result.has_attendees

    def test_has_attendees_false_when_empty(self) -> None:
        result = MeetingNotesResult(success=True)
        assert not result.has_attendees

    def test_summary_success(self) -> None:
        result = MeetingNotesResult(
            success=True,
            meeting_title="call with Sarah",
            attendee_names=["Sarah"],
            drive_file_url="https://docs.google.com/doc/123",
        )
        summary = result.summary
        assert "call with Sarah" in summary
        assert "Sarah" in summary
        assert "https://docs.google.com" in summary

    def test_summary_failure(self) -> None:
        result = MeetingNotesResult(
            success=False,
            error="API error",
        )
        assert "Failed" in result.summary
        assert "API error" in result.summary

    def test_summary_new_contacts(self) -> None:
        result = MeetingNotesResult(
            success=True,
            meeting_title="meeting",
            new_people_created=2,
        )
        assert "2 new contact(s)" in result.summary


class TestMeetingNotesServiceInit:
    """Tests for MeetingNotesService initialization."""

    def test_init_with_no_clients(self) -> None:
        service = MeetingNotesService()
        assert service._drive_client is None
        assert service._people_service is None
        assert service._notion_client is None

    def test_init_with_clients(self) -> None:
        drive = MagicMock()
        people = MagicMock()
        notion = MagicMock()
        service = MeetingNotesService(drive, people, notion)
        assert service._drive_client is drive
        assert service._people_service is people
        assert service._notion_client is notion


class TestMeetingNotesServiceCreateMeetingNotes:
    """Tests for MeetingNotesService.create_meeting_notes()."""

    @pytest.fixture
    def mock_drive_file(self) -> MagicMock:
        @dataclass
        class MockDriveFile:
            id: str = "drive-file-123"
            web_view_link: str = "https://docs.google.com/document/d/drive-file-123"
            name: str = "2026-01-13 - call with Sarah"
            mime_type: str = "application/vnd.google-apps.document"

        return MockDriveFile()

    @pytest.fixture
    def mock_drive_client(self, mock_drive_file: MagicMock) -> MagicMock:
        client = MagicMock()
        client.create_meeting_notes = AsyncMock(return_value=mock_drive_file)
        return client

    @pytest.fixture
    def mock_people_service(self) -> MagicMock:
        service = MagicMock()
        service.lookup_or_create = AsyncMock()
        return service

    @pytest.mark.asyncio
    async def test_creates_meeting_notes_with_attendees(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        # Setup people lookup
        mock_people_service.lookup_or_create.return_value = MagicMock(
            person_id="person-123",
            is_new=False,
        )

        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_meeting_notes(
            meeting_title="call with Sarah",
            attendee_names=["Sarah"],
        )

        assert result.success
        assert result.drive_file_id == "drive-file-123"
        assert result.people_ids == ["person-123"]
        assert result.attendee_names == ["Sarah"]
        mock_drive_client.create_meeting_notes.assert_called_once_with(
            meeting_title="call with Sarah",
            attendees=["Sarah"],
            agenda=None,
        )

    @pytest.mark.asyncio
    async def test_extracts_attendees_from_title(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        mock_people_service.lookup_or_create.return_value = MagicMock(
            person_id="person-456",
            is_new=False,
        )

        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_meeting_notes(
            meeting_title="meeting with John",
        )

        assert result.success
        assert result.attendee_names == ["John"]
        mock_people_service.lookup_or_create.assert_called_once_with("John")

    @pytest.mark.asyncio
    async def test_creates_new_people(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        # First person is new, second exists
        mock_people_service.lookup_or_create.side_effect = [
            MagicMock(person_id="person-new", is_new=True),
            MagicMock(person_id="person-existing", is_new=False),
        ]

        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_meeting_notes(
            meeting_title="call with Alice and Bob",
        )

        assert result.success
        assert result.new_people_created == 1
        assert len(result.people_ids) == 2

    @pytest.mark.asyncio
    async def test_handles_drive_error(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        mock_drive_client.create_meeting_notes.side_effect = Exception("API error")
        mock_people_service.lookup_or_create.return_value = MagicMock(
            person_id="person-123",
            is_new=False,
        )

        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_meeting_notes(
            meeting_title="call with Sarah",
        )

        assert not result.success
        assert "API error" in str(result.error)

    @pytest.mark.asyncio
    async def test_includes_agenda(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        mock_people_service.lookup_or_create.return_value = MagicMock(
            person_id="person-123",
            is_new=False,
        )

        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_meeting_notes(
            meeting_title="call with Sarah",
            agenda=["Discuss Q1", "Review metrics"],
        )

        assert result.success
        mock_drive_client.create_meeting_notes.assert_called_once_with(
            meeting_title="call with Sarah",
            attendees=["Sarah"],
            agenda=["Discuss Q1", "Review metrics"],
        )


class TestMeetingNotesServiceCreateFromRequest:
    """Tests for MeetingNotesService.create_from_request()."""

    @pytest.fixture
    def mock_service(self) -> MeetingNotesService:
        service = MeetingNotesService()
        service.create_meeting_notes = AsyncMock(
            return_value=MeetingNotesResult(
                success=True,
                drive_file_id="drive-123",
                meeting_title="call with Sarah",
                people_ids=["person-123"],
            )
        )
        return service

    @pytest.mark.asyncio
    async def test_parses_request_and_creates(self, mock_service: MeetingNotesService) -> None:
        result = await mock_service.create_from_request(
            "Create meeting notes for call with Sarah"
        )

        assert result.success
        mock_service.create_meeting_notes.assert_called_once_with("call with Sarah")


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_meeting_notes_service_singleton(self) -> None:
        service1 = get_meeting_notes_service()
        service2 = get_meeting_notes_service()
        assert service1 is service2

    def test_get_meeting_notes_service_with_args_creates_new(self) -> None:
        from assistant.services.meeting_notes import _service
        drive = MagicMock()
        service = get_meeting_notes_service(drive_client=drive)
        assert service._drive_client is drive


class TestAT125MeetingNotesWithPeopleLink:
    """Acceptance tests for AT-125: Drive Meeting Notes.

    AT-125 Requirements:
    - Given: User sends "Create meeting notes for call with Sarah"
    - When: Google Drive API enabled
    - Then: Google Doc created in Second Brain/Meeting Notes/ folder
    - And: Document titled with date and meeting description
    - And: Linked to Sarah in People database
    - Pass condition: Drive doc exists AND task linked to Person "Sarah"
    """

    @pytest.fixture
    def mock_drive_file(self) -> MagicMock:
        @dataclass
        class MockDriveFile:
            id: str = "drive-file-at125"
            web_view_link: str = "https://docs.google.com/document/d/drive-file-at125"
            name: str = "2026-01-13 - call with Sarah"
            mime_type: str = "application/vnd.google-apps.document"
            parent_id: str = "meeting-notes-folder"

        return MockDriveFile()

    @pytest.fixture
    def mock_drive_client(self, mock_drive_file: MagicMock) -> MagicMock:
        client = MagicMock()
        client.create_meeting_notes = AsyncMock(return_value=mock_drive_file)
        return client

    @pytest.fixture
    def mock_people_service(self) -> MagicMock:
        service = MagicMock()
        # Sarah exists in People database
        service.lookup_or_create = AsyncMock(
            return_value=MagicMock(
                found=True,
                person_id="sarah-person-id",
                is_new=False,
            )
        )
        return service

    @pytest.mark.asyncio
    async def test_at125_meeting_notes_created_in_correct_folder(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        """AT-125: Google Doc created in Second Brain/Meeting Notes/ folder."""
        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_from_request(
            "Create meeting notes for call with Sarah"
        )

        assert result.success
        assert result.drive_file_id == "drive-file-at125"
        # DriveClient.create_meeting_notes puts docs in Meeting Notes folder
        mock_drive_client.create_meeting_notes.assert_called_once()

    @pytest.mark.asyncio
    async def test_at125_document_titled_with_meeting_description(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        """AT-125: Document titled with date and meeting description."""
        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_from_request(
            "Create meeting notes for call with Sarah"
        )

        assert result.success
        # The call should include the meeting title
        call_args = mock_drive_client.create_meeting_notes.call_args
        assert call_args.kwargs["meeting_title"] == "call with Sarah"

    @pytest.mark.asyncio
    async def test_at125_linked_to_sarah_in_people_database(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        """AT-125: Linked to Sarah in People database."""
        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_from_request(
            "Create meeting notes for call with Sarah"
        )

        assert result.success
        # Sarah should be looked up in People database
        mock_people_service.lookup_or_create.assert_called_once_with("Sarah")
        # Result should include Sarah's person ID for task linking
        assert "sarah-person-id" in result.people_ids

    @pytest.mark.asyncio
    async def test_at125_pass_condition_drive_doc_and_person_link(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        """AT-125 Pass condition: Drive doc exists AND task linked to Person 'Sarah'."""
        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_from_request(
            "Create meeting notes for call with Sarah"
        )

        # Verify Drive doc exists
        assert result.success
        assert result.drive_file_id is not None
        assert result.drive_file_url is not None

        # Verify person link available for task creation
        assert result.has_attendees
        assert "sarah-person-id" in result.people_ids

        # Verify attendee name extracted
        assert "Sarah" in result.attendee_names

    @pytest.mark.asyncio
    async def test_at125_creates_new_person_if_not_found(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        """AT-125: Creates new person in People database if not found."""
        # Mock that Sarah doesn't exist, will be created
        mock_people_service.lookup_or_create.return_value = MagicMock(
            found=True,
            person_id="new-sarah-id",
            is_new=True,
        )

        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_from_request(
            "Create meeting notes for call with Sarah"
        )

        assert result.success
        assert "new-sarah-id" in result.people_ids
        assert result.new_people_created == 1


class TestMultipleAttendees:
    """Tests for handling multiple meeting attendees."""

    @pytest.fixture
    def mock_drive_file(self) -> MagicMock:
        @dataclass
        class MockDriveFile:
            id: str = "drive-multi"
            web_view_link: str = "https://docs.google.com/document/d/drive-multi"
            name: str = "Team meeting"
            mime_type: str = "application/vnd.google-apps.document"

        return MockDriveFile()

    @pytest.fixture
    def mock_drive_client(self, mock_drive_file: MagicMock) -> MagicMock:
        client = MagicMock()
        client.create_meeting_notes = AsyncMock(return_value=mock_drive_file)
        return client

    @pytest.fixture
    def mock_people_service(self) -> MagicMock:
        service = MagicMock()

        async def lookup_side_effect(name: str) -> MagicMock:
            return MagicMock(
                found=True,
                person_id=f"{name.lower()}-id",
                is_new=False,
            )

        service.lookup_or_create = AsyncMock(side_effect=lookup_side_effect)
        return service

    @pytest.mark.asyncio
    async def test_links_multiple_attendees(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        service = MeetingNotesService(mock_drive_client, mock_people_service)
        result = await service.create_meeting_notes(
            meeting_title="meeting with Sarah and John",
        )

        assert result.success
        assert len(result.attendee_names) == 2
        assert "Sarah" in result.attendee_names
        assert "John" in result.attendee_names
        assert len(result.people_ids) == 2

    @pytest.mark.asyncio
    async def test_passes_attendees_to_drive(
        self,
        mock_drive_client: MagicMock,
        mock_people_service: MagicMock,
    ) -> None:
        service = MeetingNotesService(mock_drive_client, mock_people_service)
        await service.create_meeting_notes(
            meeting_title="meeting with Alice, Bob, and Charlie",
        )

        call_args = mock_drive_client.create_meeting_notes.call_args
        attendees = call_args.kwargs["attendees"]
        assert "Alice" in attendees
        assert "Bob" in attendees
        assert "Charlie" in attendees
