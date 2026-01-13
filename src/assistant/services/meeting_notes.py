"""Meeting notes service for creating Drive docs linked to People database.

This service handles AT-125: Create meeting notes with attendee linking.

Features:
- Extracts attendee names from meeting description
- Looks up attendees in People database (creates if not found)
- Creates Google Doc in Second Brain/Meeting Notes/ folder
- Returns linked people IDs for Notion task creation
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from assistant.google.drive import DriveClient, DriveFile
    from assistant.notion.client import NotionClient
    from assistant.services.people import PeopleService


# Patterns to extract attendee names from meeting descriptions
MEETING_PATTERNS = [
    # "meeting with Sarah" / "call with John"
    re.compile(
        r"(?:meeting|call|chat|sync|1:1|one-on-one|standup|check-in)\s+with\s+(.+?)(?:\s+(?:about|on|for|to|at)|$)",
        re.IGNORECASE,
    ),
    # "Sarah meeting" / "John call"
    re.compile(
        r"^(.+?)\s+(?:meeting|call|chat|sync|1:1|one-on-one|standup|check-in)(?:\s+|$)",
        re.IGNORECASE,
    ),
    # "meet with Sarah and John"
    re.compile(
        r"meet\s+(?:with\s+)?(.+?)(?:\s+(?:about|on|for|to|at)|$)",
        re.IGNORECASE,
    ),
]

# Pattern to detect meeting notes requests
MEETING_REQUEST_PATTERNS = [
    re.compile(
        r"(?:create|make|start|new)\s+(?:meeting\s+)?notes?\s+(?:for\s+)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"meeting\s+notes?\s+(?:for\s+)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"notes?\s+(?:for\s+)?(?:meeting|call|chat|sync|1:1)",
        re.IGNORECASE,
    ),
]


@dataclass
class MeetingNotesResult:
    """Result of creating meeting notes."""

    success: bool
    drive_file: DriveFile | None = None
    drive_file_id: str | None = None
    drive_file_url: str | None = None
    meeting_title: str = ""
    attendee_names: list[str] = field(default_factory=list)
    people_ids: list[str] = field(default_factory=list)
    new_people_created: int = 0
    error: str | None = None

    @property
    def has_attendees(self) -> bool:
        """Check if meeting has linked attendees."""
        return len(self.people_ids) > 0

    @property
    def summary(self) -> str:
        """Human-readable summary of the result."""
        if not self.success:
            return f"Failed to create meeting notes: {self.error}"

        parts = [f"Created meeting notes: {self.meeting_title}"]

        if self.attendee_names:
            names = ", ".join(self.attendee_names)
            parts.append(f"Attendees: {names}")

        if self.new_people_created > 0:
            parts.append(f"({self.new_people_created} new contact(s) created)")

        if self.drive_file_url:
            parts.append(f"📄 {self.drive_file_url}")

        return "\n".join(parts)


def is_meeting_notes_request(text: str) -> bool:
    """Check if text is a request for meeting notes.

    Args:
        text: User input text

    Returns:
        True if this is a meeting notes request
    """
    return any(pattern.search(text) for pattern in MEETING_REQUEST_PATTERNS)


def extract_meeting_title(text: str) -> str:
    """Extract meeting title from request text.

    Args:
        text: User input text

    Returns:
        Meeting title or cleaned text
    """
    # Remove common prefixes
    cleaned = text
    for pattern in MEETING_REQUEST_PATTERNS:
        cleaned = pattern.sub("", cleaned).strip()

    return cleaned or text


def extract_attendees(text: str) -> list[str]:
    """Extract attendee names from meeting description.

    Args:
        text: Meeting description or title

    Returns:
        List of extracted attendee names
    """
    attendees = []

    for pattern in MEETING_PATTERNS:
        match = pattern.search(text)
        if match:
            names_str = match.group(1).strip()
            # Split by "and", ",", "&" (handle oxford comma: "A, B, and C")
            names = re.split(r",?\s+and\s+|,\s*|&\s*", names_str, flags=re.IGNORECASE)
            for name in names:
                name = name.strip()
                # Filter out common non-name words
                if name and name.lower() not in {"the", "a", "an", "my", "our"}:
                    attendees.append(name)
            if attendees:
                break  # Use first matching pattern

    return attendees


class MeetingNotesService:
    """Service for creating meeting notes with People database linking."""

    def __init__(
        self,
        drive_client: DriveClient | None = None,
        people_service: PeopleService | None = None,
        notion_client: NotionClient | None = None,
    ):
        self._drive_client = drive_client
        self._people_service = people_service
        self._notion_client = notion_client

    @property
    def drive_client(self) -> DriveClient:
        """Get or create DriveClient."""
        if self._drive_client is None:
            from assistant.google.drive import DriveClient

            self._drive_client = DriveClient()
        return self._drive_client

    @property
    def people_service(self) -> PeopleService:
        """Get or create PeopleService."""
        if self._people_service is None:
            from assistant.services.people import PeopleService

            self._people_service = PeopleService(self._notion_client)
        return self._people_service

    async def create_meeting_notes(
        self,
        meeting_title: str,
        attendee_names: list[str] | None = None,
        agenda: list[str] | None = None,
    ) -> MeetingNotesResult:
        """Create meeting notes with People database linking.

        Args:
            meeting_title: Title/description of the meeting
            attendee_names: Optional explicit attendee names (extracted if not provided)
            agenda: Optional list of agenda items

        Returns:
            MeetingNotesResult with drive file and linked people IDs
        """
        try:
            # Extract attendees if not provided
            if attendee_names is None:
                attendee_names = extract_attendees(meeting_title)

            # Look up or create people in database
            people_ids: list[str] = []
            new_people_count = 0

            for name in attendee_names:
                result = await self.people_service.lookup_or_create(name)
                if result.person_id:
                    people_ids.append(result.person_id)
                    if result.is_new:
                        new_people_count += 1

            # Create the Drive document
            drive_file = await self.drive_client.create_meeting_notes(
                meeting_title=meeting_title,
                attendees=attendee_names,
                agenda=agenda,
            )

            return MeetingNotesResult(
                success=True,
                drive_file=drive_file,
                drive_file_id=drive_file.id,
                drive_file_url=drive_file.web_view_link,
                meeting_title=meeting_title,
                attendee_names=attendee_names,
                people_ids=people_ids,
                new_people_created=new_people_count,
            )

        except Exception as e:
            return MeetingNotesResult(
                success=False,
                meeting_title=meeting_title,
                attendee_names=attendee_names or [],
                error=str(e),
            )

    async def create_from_request(self, request_text: str) -> MeetingNotesResult:
        """Create meeting notes from a natural language request.

        Args:
            request_text: User's request text (e.g., "Create meeting notes for call with Sarah")

        Returns:
            MeetingNotesResult with drive file and linked people IDs
        """
        meeting_title = extract_meeting_title(request_text)
        return await self.create_meeting_notes(meeting_title)


# Module-level singleton and convenience functions
_service: MeetingNotesService | None = None


def get_meeting_notes_service(
    drive_client: DriveClient | None = None,
    people_service: PeopleService | None = None,
    notion_client: NotionClient | None = None,
) -> MeetingNotesService:
    """Get or create MeetingNotesService instance."""
    global _service
    if _service is None or any([drive_client, people_service, notion_client]):
        _service = MeetingNotesService(drive_client, people_service, notion_client)
    return _service


async def create_meeting_notes(
    meeting_title: str,
    attendee_names: list[str] | None = None,
    agenda: list[str] | None = None,
) -> MeetingNotesResult:
    """Create meeting notes with People database linking."""
    return await get_meeting_notes_service().create_meeting_notes(
        meeting_title, attendee_names, agenda
    )


async def create_meeting_notes_from_request(request_text: str) -> MeetingNotesResult:
    """Create meeting notes from a natural language request."""
    return await get_meeting_notes_service().create_from_request(request_text)
