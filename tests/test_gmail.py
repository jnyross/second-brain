"""Tests for Gmail integration.

Tests T-120 acceptance criteria:
- Gmail client authenticates via Google OAuth
- Can list recent emails
- Can detect emails needing response
- Integrates with morning briefing

Tests T-121 acceptance criteria (Gmail draft creation):
- Can create drafts with preview
- Can retrieve draft details
- Can send drafts with confirmation
- Can delete cancelled drafts
- Draft flow: create → preview → send (with user confirmation)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from assistant.google.gmail import (
    GmailClient,
    EmailMessage,
    EmailListResult,
    DraftResult,
    SendResult,
    get_gmail_client,
    list_emails,
    list_unread_emails,
    list_emails_needing_response,
    get_email_by_id,
    create_draft,
    get_draft,
    send_draft,
    delete_draft,
    send_email,
    DEFAULT_EMAIL_LIMIT,
    SKIP_LABELS,
    ACTION_PATTERNS,
)


class TestEmailMessage:
    """Test EmailMessage dataclass."""

    def test_email_message_creation(self):
        """Test creating an EmailMessage."""
        now = datetime.now(ZoneInfo("UTC"))
        email = EmailMessage(
            message_id="msg123",
            thread_id="thread456",
            subject="Test Subject",
            sender_name="John Doe",
            sender_email="john@example.com",
            snippet="This is a test email...",
            received_at=now,
            is_read=False,
            labels=["INBOX", "UNREAD"],
            needs_response=True,
            priority="high",
            has_attachments=True,
        )

        assert email.message_id == "msg123"
        assert email.thread_id == "thread456"
        assert email.subject == "Test Subject"
        assert email.sender_name == "John Doe"
        assert email.sender_email == "john@example.com"
        assert email.snippet == "This is a test email..."
        assert email.received_at == now
        assert email.is_read is False
        assert email.labels == ["INBOX", "UNREAD"]
        assert email.needs_response is True
        assert email.priority == "high"
        assert email.has_attachments is True

    def test_email_message_defaults(self):
        """Test EmailMessage default values."""
        now = datetime.now(ZoneInfo("UTC"))
        email = EmailMessage(
            message_id="msg123",
            thread_id="thread456",
            subject="Test",
            sender_name="John",
            sender_email="john@example.com",
            snippet="Preview",
            received_at=now,
            is_read=True,
        )

        assert email.labels == []
        assert email.needs_response is False
        assert email.priority == "normal"
        assert email.has_attachments is False


class TestEmailListResult:
    """Test EmailListResult dataclass."""

    def test_success_result(self):
        """Test successful result."""
        result = EmailListResult(
            success=True,
            emails=[],
            total_count=0,
        )
        assert result.success is True
        assert result.error is None

    def test_error_result(self):
        """Test error result."""
        result = EmailListResult(
            success=False,
            error="API error",
        )
        assert result.success is False
        assert result.error == "API error"
        assert result.emails == []


class TestGmailClient:
    """Test GmailClient class."""

    def test_client_initialization(self):
        """Test client initializes correctly."""
        client = GmailClient()
        assert client._service is None

    def test_is_authenticated_no_service(self):
        """Test is_authenticated returns False when no service."""
        client = GmailClient()
        client._service = None
        # Mock google_auth to prevent real OAuth attempt
        with patch("assistant.google.gmail.google_auth") as mock_auth:
            mock_auth.credentials = None
            mock_auth.load_saved_credentials.return_value = False
            assert client.is_authenticated() is False

    def test_is_authenticated_with_service(self):
        """Test is_authenticated returns True when service exists."""
        client = GmailClient()
        client._service = MagicMock()
        assert client.is_authenticated() is True

    def test_needs_response_detection_question(self):
        """Test detection of questions needing response."""
        client = GmailClient()

        # Questions should trigger needs_response
        assert client._needs_response("", "Can you send me the report?") is True
        assert client._needs_response("Meeting request?", "") is True
        assert client._needs_response("", "Could you please review this?") is True

    def test_needs_response_detection_action_words(self):
        """Test detection of action-oriented emails."""
        client = GmailClient()

        # Action words should trigger
        assert client._needs_response("", "Please send the Q4 numbers") is True
        assert client._needs_response("URGENT: Action required", "") is True
        assert client._needs_response("", "Waiting for your response") is True
        assert client._needs_response("", "I need your input on this") is True

    def test_needs_response_detection_normal_email(self):
        """Test that normal emails don't trigger needs_response."""
        client = GmailClient()

        # Normal emails without questions/actions
        assert client._needs_response("Newsletter", "This week's updates...") is False
        assert client._needs_response("FYI: Meeting notes", "Here are the notes from today") is False

    def test_determine_priority_high(self):
        """Test high priority detection."""
        client = GmailClient()

        # Important label
        assert client._determine_priority("", "", ["IMPORTANT"]) == "high"

        # Urgent keywords
        assert client._determine_priority("URGENT: Review needed", "", []) == "high"
        assert client._determine_priority("", "This is time-sensitive", []) == "high"
        assert client._determine_priority("ASAP", "", []) == "high"

    def test_determine_priority_low(self):
        """Test low priority detection."""
        client = GmailClient()

        # Promotional/social labels
        assert client._determine_priority("", "", ["CATEGORY_PROMOTIONS"]) == "low"
        assert client._determine_priority("", "", ["CATEGORY_SOCIAL"]) == "low"
        assert client._determine_priority("", "", ["CATEGORY_UPDATES"]) == "low"

    def test_determine_priority_normal(self):
        """Test normal priority (default)."""
        client = GmailClient()

        assert client._determine_priority("Regular email", "Regular content", ["INBOX"]) == "normal"

    def test_parse_date_valid(self):
        """Test parsing valid email date."""
        client = GmailClient()

        # Standard email date format
        date_str = "Mon, 10 Jan 2026 14:30:00 +0000"
        result = client._parse_date(date_str)

        assert result.year == 2026
        assert result.month == 1
        assert result.day == 10

    def test_parse_date_invalid(self):
        """Test parsing invalid date falls back to now."""
        client = GmailClient()

        result = client._parse_date("invalid date")
        now = datetime.now(ZoneInfo("UTC"))

        # Should be close to now
        assert (now - result).total_seconds() < 60

    def test_has_attachments_true(self):
        """Test attachment detection when present."""
        client = GmailClient()

        payload = {
            "parts": [
                {"filename": "document.pdf"},
            ]
        }
        assert client._has_attachments(payload) is True

    def test_has_attachments_false(self):
        """Test attachment detection when not present."""
        client = GmailClient()

        payload = {"parts": [{"body": {"data": "text"}}]}
        assert client._has_attachments(payload) is False

        # Empty payload
        assert client._has_attachments({}) is False

    def test_parse_message(self):
        """Test parsing a Gmail API message response."""
        client = GmailClient()

        msg = {
            "id": "msg123",
            "threadId": "thread456",
            "snippet": "Can you send me the report?",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Project Update"},
                    {"name": "From", "value": "John Doe <john@example.com>"},
                    {"name": "Date", "value": "Mon, 10 Jan 2026 14:30:00 +0000"},
                ],
                "parts": [],
            },
        }

        email = client._parse_message(msg)

        assert email is not None
        assert email.message_id == "msg123"
        assert email.thread_id == "thread456"
        assert email.subject == "Project Update"
        assert email.sender_name == "John Doe"
        assert email.sender_email == "john@example.com"
        assert email.is_read is False  # UNREAD label present
        assert email.needs_response is True  # Contains "?"
        assert email.priority == "normal"


class TestGmailClientAsync:
    """Test async GmailClient methods."""

    @pytest.mark.asyncio
    async def test_list_emails_not_authenticated(self):
        """Test list_emails when not authenticated."""
        client = GmailClient()

        with patch("assistant.google.gmail.google_auth") as mock_auth:
            mock_auth.credentials = None
            mock_auth.load_saved_credentials.return_value = False

            result = await client.list_emails()

            assert result.success is False
            assert "not authenticated" in result.error.lower()

    @pytest.mark.asyncio
    async def test_list_emails_success(self):
        """Test successful email listing."""
        client = GmailClient()

        # Mock the service
        mock_service = MagicMock()
        client._service = mock_service

        # Mock list response
        list_response = {
            "messages": [
                {"id": "msg1"},
                {"id": "msg2"},
            ],
            "resultSizeEstimate": 2,
        }

        # Mock get response for each message
        get_responses = [
            {
                "id": "msg1",
                "threadId": "t1",
                "snippet": "Test email 1",
                "labelIds": ["INBOX"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Subject 1"},
                        {"name": "From", "value": "sender1@example.com"},
                        {"name": "Date", "value": "Mon, 10 Jan 2026 14:00:00 +0000"},
                    ],
                    "parts": [],
                },
            },
            {
                "id": "msg2",
                "threadId": "t2",
                "snippet": "Test email 2",
                "labelIds": ["INBOX"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Subject 2"},
                        {"name": "From", "value": "sender2@example.com"},
                        {"name": "Date", "value": "Mon, 10 Jan 2026 15:00:00 +0000"},
                    ],
                    "parts": [],
                },
            },
        ]

        # Set up mock chain
        mock_users = MagicMock()
        mock_messages = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages

        mock_list = MagicMock()
        mock_list.execute.return_value = list_response
        mock_messages.list.return_value = mock_list

        # Track which message ID is being requested
        get_call_count = [0]

        def mock_get_execute():
            idx = get_call_count[0]
            get_call_count[0] += 1
            return get_responses[idx]

        mock_get = MagicMock()
        mock_get.execute.side_effect = mock_get_execute
        mock_messages.get.return_value = mock_get

        result = await client.list_emails(max_results=10)

        assert result.success is True
        assert len(result.emails) == 2
        assert result.emails[0].message_id == "msg2"  # Sorted by date, newest first
        assert result.emails[1].message_id == "msg1"

    @pytest.mark.asyncio
    async def test_list_emails_filters_promotional(self):
        """Test that promotional emails are filtered out."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        # Mock list response with promotional email
        list_response = {
            "messages": [{"id": "msg1"}],
            "resultSizeEstimate": 1,
        }

        get_response = {
            "id": "msg1",
            "threadId": "t1",
            "snippet": "Sale!",
            "labelIds": ["INBOX", "CATEGORY_PROMOTIONS"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Big Sale!"},
                    {"name": "From", "value": "promo@store.com"},
                    {"name": "Date", "value": "Mon, 10 Jan 2026 14:00:00 +0000"},
                ],
                "parts": [],
            },
        }

        mock_users = MagicMock()
        mock_messages = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages

        mock_list = MagicMock()
        mock_list.execute.return_value = list_response
        mock_messages.list.return_value = mock_list

        mock_get = MagicMock()
        mock_get.execute.return_value = get_response
        mock_messages.get.return_value = mock_get

        result = await client.list_emails()

        assert result.success is True
        assert len(result.emails) == 0  # Filtered out

    @pytest.mark.asyncio
    async def test_list_unread(self):
        """Test listing unread emails."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        # Mock empty response
        mock_users = MagicMock()
        mock_messages = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages

        mock_list = MagicMock()
        mock_list.execute.return_value = {"messages": []}
        mock_messages.list.return_value = mock_list

        result = await client.list_unread(max_results=10, since_hours=24)

        assert result.success is True
        # Verify query included "is:unread"
        call_args = mock_messages.list.call_args
        assert "is:unread" in call_args.kwargs.get("q", "")

    @pytest.mark.asyncio
    async def test_list_needing_response(self):
        """Test listing emails needing response."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        # Mock response with emails
        list_response = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}],
        }

        # One needs response, one doesn't
        get_responses = [
            {
                "id": "msg1",
                "threadId": "t1",
                "snippet": "Can you send me the report?",  # Has question
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Question"},
                        {"name": "From", "value": "asker@example.com"},
                        {"name": "Date", "value": "Mon, 10 Jan 2026 14:00:00 +0000"},
                    ],
                    "parts": [],
                },
            },
            {
                "id": "msg2",
                "threadId": "t2",
                "snippet": "FYI - meeting notes attached",  # No action needed
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "FYI"},
                        {"name": "From", "value": "info@example.com"},
                        {"name": "Date", "value": "Mon, 10 Jan 2026 15:00:00 +0000"},
                    ],
                    "parts": [],
                },
            },
        ]

        mock_users = MagicMock()
        mock_messages = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages

        mock_list = MagicMock()
        mock_list.execute.return_value = list_response
        mock_messages.list.return_value = mock_list

        get_call_count = [0]

        def mock_get_execute():
            idx = get_call_count[0]
            get_call_count[0] += 1
            return get_responses[idx]

        mock_get = MagicMock()
        mock_get.execute.side_effect = mock_get_execute
        mock_messages.get.return_value = mock_get

        result = await client.list_needing_response(max_results=10)

        assert result.success is True
        assert len(result.emails) == 1  # Only one needs response
        assert result.emails[0].message_id == "msg1"
        assert result.emails[0].needs_response is True

    @pytest.mark.asyncio
    async def test_get_email(self):
        """Test getting a single email."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        get_response = {
            "id": "msg123",
            "threadId": "t1",
            "snippet": "Test email",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test"},
                    {"name": "From", "value": "test@example.com"},
                    {"name": "Date", "value": "Mon, 10 Jan 2026 14:00:00 +0000"},
                ],
                "parts": [],
            },
        }

        mock_users = MagicMock()
        mock_messages = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages

        mock_get = MagicMock()
        mock_get.execute.return_value = get_response
        mock_messages.get.return_value = mock_get

        email = await client.get_email("msg123")

        assert email is not None
        assert email.message_id == "msg123"
        assert email.subject == "Test"


class TestGmailModuleFunctions:
    """Test module-level convenience functions."""

    def test_get_gmail_client_singleton(self):
        """Test that get_gmail_client returns singleton."""
        # Clear any existing client
        import assistant.google.gmail as gmail_module
        gmail_module._gmail_client = None

        client1 = get_gmail_client()
        client2 = get_gmail_client()

        assert client1 is client2

    @pytest.mark.asyncio
    async def test_list_emails_convenience(self):
        """Test list_emails convenience function."""
        with patch("assistant.google.gmail.get_gmail_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.list_emails.return_value = EmailListResult(success=True)
            mock_get.return_value = mock_client

            result = await list_emails(max_results=10)

            mock_client.list_emails.assert_called_once_with(max_results=10, query=None)

    @pytest.mark.asyncio
    async def test_list_unread_convenience(self):
        """Test list_unread_emails convenience function."""
        with patch("assistant.google.gmail.get_gmail_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.list_unread.return_value = EmailListResult(success=True)
            mock_get.return_value = mock_client

            result = await list_unread_emails(max_results=5, since_hours=12)

            mock_client.list_unread.assert_called_once_with(max_results=5, since_hours=12)

    @pytest.mark.asyncio
    async def test_list_needing_response_convenience(self):
        """Test list_emails_needing_response convenience function."""
        with patch("assistant.google.gmail.get_gmail_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.list_needing_response.return_value = EmailListResult(success=True)
            mock_get.return_value = mock_client

            result = await list_emails_needing_response(max_results=5)

            mock_client.list_needing_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_email_by_id_convenience(self):
        """Test get_email_by_id convenience function."""
        with patch("assistant.google.gmail.get_gmail_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.get_email.return_value = None
            mock_get.return_value = mock_client

            result = await get_email_by_id("msg123")

            mock_client.get_email.assert_called_once_with("msg123")


class TestBriefingEmailIntegration:
    """Test Gmail integration with BriefingGenerator."""

    @pytest.mark.asyncio
    async def test_briefing_email_section_no_gmail(self):
        """Test email section when Gmail not authenticated."""
        from assistant.services.briefing import BriefingGenerator

        mock_gmail = MagicMock()
        mock_gmail.is_authenticated.return_value = False

        generator = BriefingGenerator(
            notion_client=None,
            calendar_client=None,
            gmail_client=mock_gmail,
        )

        section = await generator._generate_email_section()
        assert section is None

    @pytest.mark.asyncio
    async def test_briefing_email_section_no_emails(self):
        """Test email section when no emails need attention."""
        from assistant.services.briefing import BriefingGenerator

        mock_gmail = MagicMock()
        mock_gmail.is_authenticated.return_value = True
        mock_gmail.list_needing_response = AsyncMock(
            return_value=EmailListResult(success=True, emails=[])
        )

        generator = BriefingGenerator(
            notion_client=None,
            calendar_client=None,
            gmail_client=mock_gmail,
        )

        section = await generator._generate_email_section()
        assert section is None

    @pytest.mark.asyncio
    async def test_briefing_email_section_with_emails(self):
        """Test email section with emails needing attention."""
        from assistant.services.briefing import BriefingGenerator

        mock_gmail = MagicMock()
        mock_gmail.is_authenticated.return_value = True

        now = datetime.now(ZoneInfo("UTC"))
        emails = [
            EmailMessage(
                message_id="msg1",
                thread_id="t1",
                subject="Can you review this?",
                sender_name="Mike",
                sender_email="mike@example.com",
                snippet="Please review the attached...",
                received_at=now - timedelta(hours=2),
                is_read=False,
                needs_response=True,
                priority="normal",
            ),
            EmailMessage(
                message_id="msg2",
                thread_id="t2",
                subject="URGENT: Client meeting",
                sender_name="Sarah",
                sender_email="sarah@example.com",
                snippet="The client meeting has been moved...",
                received_at=now - timedelta(hours=5),
                is_read=False,
                needs_response=True,
                priority="high",
            ),
        ]

        mock_gmail.list_needing_response = AsyncMock(
            return_value=EmailListResult(success=True, emails=emails)
        )

        generator = BriefingGenerator(
            notion_client=None,
            calendar_client=None,
            gmail_client=mock_gmail,
        )

        section = await generator._generate_email_section()

        assert section is not None
        assert "EMAIL" in section
        assert "2 need attention" in section
        assert "Mike" in section
        assert "Sarah" in section
        assert "(urgent)" in section  # High priority marker

    @pytest.mark.asyncio
    async def test_format_time_ago(self):
        """Test time ago formatting."""
        from assistant.services.briefing import BriefingGenerator

        generator = BriefingGenerator(notion_client=None)
        now = datetime.now(generator.timezone)

        # Test various deltas
        assert generator._format_time_ago(now, now) == "just now"
        assert generator._format_time_ago(now - timedelta(minutes=1), now) == "1 minute ago"
        assert generator._format_time_ago(now - timedelta(minutes=30), now) == "30 minutes ago"
        assert generator._format_time_ago(now - timedelta(hours=1), now) == "1 hour ago"
        assert generator._format_time_ago(now - timedelta(hours=5), now) == "5 hours ago"
        assert generator._format_time_ago(now - timedelta(days=1), now) == "1 day ago"
        assert generator._format_time_ago(now - timedelta(days=3), now) == "3 days ago"


# =============================================================================
# T-121: Gmail Draft Creation Tests
# =============================================================================


class TestDraftResult:
    """Test DraftResult dataclass."""

    def test_draft_result_success(self):
        """Test successful draft result."""
        result = DraftResult(
            success=True,
            draft_id="draft123",
            message_id="msg456",
            thread_id="thread789",
            subject="Test Subject",
            to=["test@example.com"],
            cc=["cc@example.com"],
            body="Hello, this is a test email.",
            html_link="https://mail.google.com/mail/u/0/#drafts?compose=draft123",
        )

        assert result.success is True
        assert result.draft_id == "draft123"
        assert result.message_id == "msg456"
        assert result.subject == "Test Subject"
        assert result.to == ["test@example.com"]
        assert result.cc == ["cc@example.com"]
        assert result.html_link is not None

    def test_draft_result_error(self):
        """Test error draft result."""
        result = DraftResult(
            success=False,
            error="API error occurred",
        )

        assert result.success is False
        assert result.error == "API error occurred"
        assert result.draft_id is None

    def test_draft_preview_generation(self):
        """Test draft preview generation for user confirmation."""
        result = DraftResult(
            success=True,
            draft_id="draft123",
            subject="Re: Project Update",
            to=["mike@example.com"],
            cc=["team@example.com"],
            body="Hi Mike,\n\nI'll send the Q4 numbers today.\n\nJohn",
        )

        preview = result.preview

        assert "mike@example.com" in preview
        assert "team@example.com" in preview
        assert "Re: Project Update" in preview
        assert "I'll send the Q4 numbers today" in preview

    def test_draft_preview_error(self):
        """Test draft preview when failed."""
        result = DraftResult(
            success=False,
            error="Not authenticated",
        )

        preview = result.preview

        assert "Draft failed" in preview
        assert "Not authenticated" in preview

    def test_draft_preview_truncation(self):
        """Test long body truncation in preview."""
        long_body = "A" * 600  # Exceeds 500 char limit
        result = DraftResult(
            success=True,
            draft_id="draft123",
            subject="Test",
            to=["test@example.com"],
            body=long_body,
        )

        preview = result.preview

        assert len(preview) < len(long_body) + 100  # Should be truncated
        assert "..." in preview


class TestSendResult:
    """Test SendResult dataclass."""

    def test_send_result_success(self):
        """Test successful send result."""
        result = SendResult(
            success=True,
            message_id="msg123",
            thread_id="thread456",
        )

        assert result.success is True
        assert result.message_id == "msg123"
        assert result.thread_id == "thread456"
        assert result.error is None

    def test_send_result_error(self):
        """Test error send result."""
        result = SendResult(
            success=False,
            error="Failed to send",
        )

        assert result.success is False
        assert result.error == "Failed to send"


class TestGmailClientDrafts:
    """Test GmailClient draft methods (T-121)."""

    @pytest.mark.asyncio
    async def test_create_draft_not_authenticated(self):
        """Test create_draft when not authenticated."""
        client = GmailClient()

        with patch("assistant.google.gmail.google_auth") as mock_auth:
            mock_auth.credentials = None
            mock_auth.load_saved_credentials.return_value = False

            result = await client.create_draft(
                to=["test@example.com"],
                subject="Test",
                body="Hello",
            )

            assert result.success is False
            assert "not authenticated" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_draft_no_recipients(self):
        """Test create_draft with empty recipient list."""
        client = GmailClient()
        client._service = MagicMock()

        result = await client.create_draft(
            to=[],
            subject="Test",
            body="Hello",
        )

        assert result.success is False
        assert "recipient" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_draft_success(self):
        """Test successful draft creation."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        # Mock the drafts().create() chain
        create_response = {
            "id": "draft123",
            "message": {
                "id": "msg456",
                "threadId": "thread789",
            }
        }

        mock_users = MagicMock()
        mock_drafts = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.drafts.return_value = mock_drafts

        mock_create = MagicMock()
        mock_create.execute.return_value = create_response
        mock_drafts.create.return_value = mock_create

        result = await client.create_draft(
            to=["mike@example.com"],
            subject="Q4 Numbers",
            body="Hi Mike, here are the Q4 numbers.",
            cc=["team@example.com"],
        )

        assert result.success is True
        assert result.draft_id == "draft123"
        assert result.message_id == "msg456"
        assert result.subject == "Q4 Numbers"
        assert result.to == ["mike@example.com"]
        assert result.cc == ["team@example.com"]
        assert "drafts" in result.html_link

    @pytest.mark.asyncio
    async def test_create_draft_with_reply(self):
        """Test draft creation as reply to thread."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        create_response = {
            "id": "draft123",
            "message": {
                "id": "msg456",
                "threadId": "existing_thread",
            }
        }

        mock_users = MagicMock()
        mock_drafts = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.drafts.return_value = mock_drafts

        mock_create = MagicMock()
        mock_create.execute.return_value = create_response
        mock_drafts.create.return_value = mock_create

        result = await client.create_draft(
            to=["mike@example.com"],
            subject="Re: Q4 Numbers",
            body="Thanks for the reminder, sending now.",
            thread_id="existing_thread",
            in_reply_to="original_msg_id",
        )

        assert result.success is True
        assert result.thread_id == "existing_thread"

        # Verify the API was called with thread ID
        call_kwargs = mock_drafts.create.call_args
        assert "body" in call_kwargs.kwargs
        assert call_kwargs.kwargs["body"]["message"]["threadId"] == "existing_thread"

    @pytest.mark.asyncio
    async def test_get_draft_success(self):
        """Test retrieving a draft."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        get_response = {
            "id": "draft123",
            "message": {
                "id": "msg456",
                "threadId": "thread789",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Test Subject"},
                        {"name": "To", "value": "test@example.com"},
                        {"name": "CC", "value": "cc@example.com"},
                    ],
                    "body": {
                        "data": "SGVsbG8gV29ybGQ=",  # "Hello World" base64
                    },
                },
            },
        }

        mock_users = MagicMock()
        mock_drafts = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.drafts.return_value = mock_drafts

        mock_get = MagicMock()
        mock_get.execute.return_value = get_response
        mock_drafts.get.return_value = mock_get

        result = await client.get_draft("draft123")

        assert result.success is True
        assert result.draft_id == "draft123"
        assert result.subject == "Test Subject"
        assert "test@example.com" in result.to
        assert "cc@example.com" in result.cc
        assert "Hello World" in result.body

    @pytest.mark.asyncio
    async def test_send_draft_success(self):
        """Test sending a draft."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        send_response = {
            "id": "sent_msg_123",
            "threadId": "thread456",
        }

        mock_users = MagicMock()
        mock_drafts = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.drafts.return_value = mock_drafts

        mock_send = MagicMock()
        mock_send.execute.return_value = send_response
        mock_drafts.send.return_value = mock_send

        result = await client.send_draft("draft123")

        assert result.success is True
        assert result.message_id == "sent_msg_123"
        assert result.thread_id == "thread456"

        # Verify the API was called with draft ID
        call_kwargs = mock_drafts.send.call_args
        assert call_kwargs.kwargs["body"]["id"] == "draft123"

    @pytest.mark.asyncio
    async def test_send_draft_not_authenticated(self):
        """Test send_draft when not authenticated."""
        client = GmailClient()

        with patch("assistant.google.gmail.google_auth") as mock_auth:
            mock_auth.credentials = None
            mock_auth.load_saved_credentials.return_value = False

            result = await client.send_draft("draft123")

            assert result.success is False
            assert "not authenticated" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_draft_success(self):
        """Test deleting a draft."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        mock_users = MagicMock()
        mock_drafts = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.drafts.return_value = mock_drafts

        mock_delete = MagicMock()
        mock_delete.execute.return_value = None
        mock_drafts.delete.return_value = mock_delete

        result = await client.delete_draft("draft123")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_draft_not_authenticated(self):
        """Test delete_draft when not authenticated."""
        client = GmailClient()

        with patch("assistant.google.gmail.google_auth") as mock_auth:
            mock_auth.credentials = None
            mock_auth.load_saved_credentials.return_value = False

            result = await client.delete_draft("draft123")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_email_direct_success(self):
        """Test sending email directly (not via draft)."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        send_response = {
            "id": "msg123",
            "threadId": "thread456",
        }

        mock_users = MagicMock()
        mock_messages = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages

        mock_send = MagicMock()
        mock_send.execute.return_value = send_response
        mock_messages.send.return_value = mock_send

        result = await client.send_email(
            to=["test@example.com"],
            subject="Direct Send Test",
            body="This was sent directly.",
        )

        assert result.success is True
        assert result.message_id == "msg123"


class TestDraftConvenienceFunctions:
    """Test module-level convenience functions for drafts."""

    @pytest.mark.asyncio
    async def test_create_draft_convenience(self):
        """Test create_draft convenience function."""
        with patch("assistant.google.gmail.get_gmail_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.create_draft.return_value = DraftResult(
                success=True,
                draft_id="draft123",
                subject="Test",
                to=["test@example.com"],
            )
            mock_get.return_value = mock_client

            result = await create_draft(
                to=["test@example.com"],
                subject="Test",
                body="Hello",
            )

            assert result.success is True
            mock_client.create_draft.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_draft_convenience(self):
        """Test get_draft convenience function."""
        with patch("assistant.google.gmail.get_gmail_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.get_draft.return_value = DraftResult(success=True)
            mock_get.return_value = mock_client

            result = await get_draft("draft123")

            mock_client.get_draft.assert_called_once_with("draft123")

    @pytest.mark.asyncio
    async def test_send_draft_convenience(self):
        """Test send_draft convenience function."""
        with patch("assistant.google.gmail.get_gmail_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.send_draft.return_value = SendResult(
                success=True,
                message_id="msg123",
            )
            mock_get.return_value = mock_client

            result = await send_draft("draft123")

            assert result.success is True
            mock_client.send_draft.assert_called_once_with("draft123")

    @pytest.mark.asyncio
    async def test_delete_draft_convenience(self):
        """Test delete_draft convenience function."""
        with patch("assistant.google.gmail.get_gmail_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.delete_draft.return_value = True
            mock_get.return_value = mock_client

            result = await delete_draft("draft123")

            assert result is True
            mock_client.delete_draft.assert_called_once_with("draft123")

    @pytest.mark.asyncio
    async def test_send_email_convenience(self):
        """Test send_email convenience function."""
        with patch("assistant.google.gmail.get_gmail_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.send_email.return_value = SendResult(
                success=True,
                message_id="msg123",
            )
            mock_get.return_value = mock_client

            result = await send_email(
                to=["test@example.com"],
                subject="Test",
                body="Hello",
            )

            assert result.success is True
            mock_client.send_email.assert_called_once()


class TestDraftWorkflow:
    """Test the complete draft workflow per PRD Section 4.5.

    The flow is:
    1. User: "Email Mike about the Q4 numbers"
    2. AI: Creates draft, shows preview
    3. User: "Send it" or "Edit" or "Cancel"
    4. AI: Sends/updates/deletes accordingly
    """

    @pytest.mark.asyncio
    async def test_complete_draft_send_workflow(self):
        """Test: create draft → preview → confirm → send."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        # Step 1: Create draft
        create_response = {
            "id": "draft123",
            "message": {"id": "msg_in_draft", "threadId": "thread1"},
        }

        mock_users = MagicMock()
        mock_drafts = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.drafts.return_value = mock_drafts

        mock_create = MagicMock()
        mock_create.execute.return_value = create_response
        mock_drafts.create.return_value = mock_create

        draft_result = await client.create_draft(
            to=["mike@example.com"],
            subject="Q4 Numbers",
            body="Hi Mike,\n\nHere are the Q4 numbers.\n\nJohn",
        )

        assert draft_result.success is True
        draft_id = draft_result.draft_id

        # Step 2: Generate preview for user
        preview = draft_result.preview
        assert "mike@example.com" in preview
        assert "Q4 Numbers" in preview
        assert "Q4 numbers" in preview

        # Step 3: User confirms "Send it"
        send_response = {
            "id": "sent_msg_123",
            "threadId": "thread1",
        }

        mock_send = MagicMock()
        mock_send.execute.return_value = send_response
        mock_drafts.send.return_value = mock_send

        send_result = await client.send_draft(draft_id)

        assert send_result.success is True
        assert send_result.message_id == "sent_msg_123"

    @pytest.mark.asyncio
    async def test_draft_cancel_workflow(self):
        """Test: create draft → preview → cancel (delete draft)."""
        client = GmailClient()
        mock_service = MagicMock()
        client._service = mock_service

        # Step 1: Create draft
        create_response = {
            "id": "draft123",
            "message": {"id": "msg_in_draft", "threadId": "thread1"},
        }

        mock_users = MagicMock()
        mock_drafts = MagicMock()
        mock_service.users.return_value = mock_users
        mock_users.drafts.return_value = mock_drafts

        mock_create = MagicMock()
        mock_create.execute.return_value = create_response
        mock_drafts.create.return_value = mock_create

        draft_result = await client.create_draft(
            to=["mike@example.com"],
            subject="Q4 Numbers",
            body="Hi Mike,\n\nHere are the Q4 numbers.\n\nJohn",
        )

        assert draft_result.success is True
        draft_id = draft_result.draft_id

        # Step 2: User says "Cancel" - delete the draft
        mock_delete = MagicMock()
        mock_delete.execute.return_value = None
        mock_drafts.delete.return_value = mock_delete

        delete_result = await client.delete_draft(draft_id)

        assert delete_result is True
