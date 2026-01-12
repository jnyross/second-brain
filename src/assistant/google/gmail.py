"""Gmail integration for Second Brain.

Read emails for morning briefings and context.

Per PRD Section 4.5:
- Fetch recent emails for morning briefing
- Search emails by sender, subject, date
- Extract action items from emails
- Identify emails needing response
- Link email threads to People and Projects

OAuth scopes required:
- https://www.googleapis.com/auth/gmail.readonly
"""

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Any
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from assistant.google.auth import google_auth
from assistant.config import settings

logger = logging.getLogger(__name__)

# Default number of emails to fetch for briefings
DEFAULT_EMAIL_LIMIT = 20

# Labels to exclude from attention-needing emails
SKIP_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "SPAM", "TRASH"}

# Patterns that indicate an email needs a response
ACTION_PATTERNS = [
    r"\?",  # Contains a question
    r"(?:please|pls|kindly)\s+(?:send|share|review|confirm|let me know)",
    r"(?:can|could|would)\s+you\s+(?:please|pls)?",
    r"(?:need|require|request)(?:ing|ed)?\s+(?:your|a)\s+(?:response|reply|input|feedback)",
    r"(?:waiting|await)(?:ing)?\s+(?:for\s+)?(?:your|a)\s+(?:response|reply)",
    r"(?:asap|urgent|priority|time-sensitive)",
    r"action\s+(?:required|needed|item)",
]


@dataclass
class EmailMessage:
    """Represents a Gmail message."""

    message_id: str
    thread_id: str
    subject: str
    sender_name: str
    sender_email: str
    snippet: str
    received_at: datetime
    is_read: bool
    labels: list[str] = field(default_factory=list)
    needs_response: bool = False
    priority: str = "normal"  # high, normal, low
    has_attachments: bool = False


@dataclass
class EmailListResult:
    """Result of listing emails."""

    success: bool
    emails: list[EmailMessage] = field(default_factory=list)
    error: str | None = None
    total_count: int = 0


class GmailClient:
    """Gmail client for reading emails.

    Provides read-only access to Gmail:
    - List recent emails
    - Search emails by query
    - Get email details
    - Detect emails needing response
    """

    def __init__(self):
        """Initialize the Gmail client."""
        self._service = None
        self._action_patterns = [re.compile(p, re.IGNORECASE) for p in ACTION_PATTERNS]

    @property
    def service(self):
        """Get or create the Gmail API service.

        Returns:
            Gmail API service object, or None if not authenticated.
        """
        if self._service is None:
            creds = google_auth.credentials
            if creds is None:
                # Try loading saved credentials
                if google_auth.load_saved_credentials():
                    creds = google_auth.credentials

            if creds is not None:
                self._service = build("gmail", "v1", credentials=creds)

        return self._service

    def is_authenticated(self) -> bool:
        """Check if we have valid Gmail credentials."""
        return self.service is not None

    async def list_emails(
        self,
        max_results: int = DEFAULT_EMAIL_LIMIT,
        query: str | None = None,
        label_ids: list[str] | None = None,
        include_spam_trash: bool = False,
    ) -> EmailListResult:
        """List recent emails from the inbox.

        Args:
            max_results: Maximum number of emails to return (default: 20)
            query: Gmail search query (e.g., "from:mike@example.com")
            label_ids: Filter by label IDs (default: INBOX)
            include_spam_trash: Include spam and trash messages

        Returns:
            EmailListResult with list of EmailMessage objects
        """
        if not self.is_authenticated():
            return EmailListResult(
                success=False,
                error="Gmail not authenticated. Please run OAuth flow first.",
            )

        try:
            import asyncio
            loop = asyncio.get_event_loop()

            # Build list request
            def do_list():
                kwargs: dict[str, Any] = {
                    "userId": "me",
                    "maxResults": max_results,
                    "includeSpamTrash": include_spam_trash,
                }
                if query:
                    kwargs["q"] = query
                if label_ids:
                    kwargs["labelIds"] = label_ids
                else:
                    kwargs["labelIds"] = ["INBOX"]

                return self.service.users().messages().list(**kwargs).execute()

            result = await loop.run_in_executor(None, do_list)

            messages = result.get("messages", [])
            if not messages:
                return EmailListResult(success=True, emails=[], total_count=0)

            # Fetch details for each message
            emails: list[EmailMessage] = []
            for msg_ref in messages:
                email = await self._get_email_details(msg_ref["id"])
                if email:
                    # Skip promotional/social emails
                    if not any(label in SKIP_LABELS for label in email.labels):
                        emails.append(email)

            # Sort by received date, newest first
            emails.sort(key=lambda e: e.received_at, reverse=True)

            logger.info(f"Listed {len(emails)} emails from Gmail")

            return EmailListResult(
                success=True,
                emails=emails,
                total_count=result.get("resultSizeEstimate", len(emails)),
            )

        except HttpError as e:
            logger.exception(f"Gmail API error: {e}")
            return EmailListResult(
                success=False,
                error=f"Gmail API error: {e.reason if hasattr(e, 'reason') else str(e)}",
            )
        except Exception as e:
            logger.exception(f"Failed to list emails: {e}")
            return EmailListResult(
                success=False,
                error=f"Failed to list emails: {str(e)}",
            )

    async def _get_email_details(self, message_id: str) -> EmailMessage | None:
        """Get details for a single email message.

        Args:
            message_id: Gmail message ID

        Returns:
            EmailMessage or None if failed
        """
        try:
            import asyncio
            loop = asyncio.get_event_loop()

            def do_get():
                return (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=message_id, format="metadata")
                    .execute()
                )

            msg = await loop.run_in_executor(None, do_get)
            return self._parse_message(msg)

        except Exception as e:
            logger.warning(f"Failed to get email details for {message_id}: {e}")
            return None

    async def get_email(self, message_id: str) -> EmailMessage | None:
        """Get a single email by ID.

        Args:
            message_id: Gmail message ID

        Returns:
            EmailMessage or None if not found
        """
        if not self.is_authenticated():
            return None

        return await self._get_email_details(message_id)

    async def list_unread(
        self,
        max_results: int = DEFAULT_EMAIL_LIMIT,
        since_hours: int = 24,
    ) -> EmailListResult:
        """List unread emails from the last N hours.

        Args:
            max_results: Maximum number of emails to return
            since_hours: Only include emails from this many hours ago

        Returns:
            EmailListResult with unread emails
        """
        since = datetime.now(ZoneInfo("UTC")) - timedelta(hours=since_hours)
        since_unix = int(since.timestamp())

        query = f"is:unread after:{since_unix}"
        return await self.list_emails(max_results=max_results, query=query)

    async def list_needing_response(
        self,
        max_results: int = 10,
        since_hours: int = 48,
    ) -> EmailListResult:
        """List emails that likely need a response.

        Uses heuristics to identify emails that:
        - Are unread
        - Contain questions or action requests
        - Are from real people (not promotions)

        Args:
            max_results: Maximum number of emails to return
            since_hours: Only include emails from this many hours ago

        Returns:
            EmailListResult with emails needing attention
        """
        # Get recent unread emails
        result = await self.list_unread(max_results=max_results * 2, since_hours=since_hours)

        if not result.success:
            return result

        # Filter to those that need response
        needing_response = [e for e in result.emails if e.needs_response]

        return EmailListResult(
            success=True,
            emails=needing_response[:max_results],
            total_count=len(needing_response),
        )

    def _parse_message(self, msg: dict[str, Any]) -> EmailMessage | None:
        """Parse a Gmail API message response into EmailMessage.

        Args:
            msg: Raw message dict from Gmail API

        Returns:
            EmailMessage or None if parsing fails
        """
        try:
            message_id = msg.get("id", "")
            thread_id = msg.get("threadId", "")
            snippet = msg.get("snippet", "")
            labels = msg.get("labelIds", [])

            # Parse headers
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

            subject = headers.get("subject", "(no subject)")
            from_header = headers.get("from", "")
            date_header = headers.get("date", "")

            # Parse sender
            sender_name, sender_email = parseaddr(from_header)
            if not sender_name:
                sender_name = sender_email.split("@")[0] if sender_email else "Unknown"

            # Parse date
            received_at = self._parse_date(date_header)

            # Check if read
            is_read = "UNREAD" not in labels

            # Check for attachments
            has_attachments = self._has_attachments(msg.get("payload", {}))

            # Detect if response needed
            needs_response = self._needs_response(subject, snippet)

            # Determine priority
            priority = self._determine_priority(subject, snippet, labels)

            return EmailMessage(
                message_id=message_id,
                thread_id=thread_id,
                subject=subject,
                sender_name=sender_name,
                sender_email=sender_email,
                snippet=snippet,
                received_at=received_at,
                is_read=is_read,
                labels=labels,
                needs_response=needs_response,
                priority=priority,
                has_attachments=has_attachments,
            )

        except Exception as e:
            logger.warning(f"Failed to parse email message: {e}")
            return None

    def _parse_date(self, date_str: str) -> datetime:
        """Parse email date header into datetime.

        Args:
            date_str: Date string from email header

        Returns:
            Datetime object (defaults to now if parsing fails)
        """
        from email.utils import parsedate_to_datetime

        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            # Fall back to UTC now
            return datetime.now(ZoneInfo("UTC"))

    def _has_attachments(self, payload: dict[str, Any]) -> bool:
        """Check if message has attachments.

        Args:
            payload: Message payload from Gmail API

        Returns:
            True if message has attachments
        """
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("filename"):
                return True
            # Recurse into nested parts
            if part.get("parts") and self._has_attachments(part):
                return True
        return False

    def _needs_response(self, subject: str, snippet: str) -> bool:
        """Detect if an email likely needs a response.

        Args:
            subject: Email subject
            snippet: Email snippet/preview

        Returns:
            True if email likely needs response
        """
        text = f"{subject} {snippet}".lower()

        for pattern in self._action_patterns:
            if pattern.search(text):
                return True

        return False

    def _determine_priority(
        self,
        subject: str,
        snippet: str,
        labels: list[str],
    ) -> str:
        """Determine email priority based on content and labels.

        Args:
            subject: Email subject
            snippet: Email snippet
            labels: Gmail labels

        Returns:
            Priority string: "high", "normal", or "low"
        """
        text = f"{subject} {snippet}".lower()

        # High priority indicators
        if "IMPORTANT" in labels:
            return "high"
        if any(word in text for word in ["urgent", "asap", "priority", "time-sensitive", "critical"]):
            return "high"

        # Low priority indicators
        if any(label in labels for label in ["CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES"]):
            return "low"

        return "normal"


# Module-level singleton instance
_gmail_client: GmailClient | None = None


def get_gmail_client() -> GmailClient:
    """Get or create the global GmailClient instance."""
    global _gmail_client
    if _gmail_client is None:
        _gmail_client = GmailClient()
    return _gmail_client


async def list_emails(
    max_results: int = DEFAULT_EMAIL_LIMIT,
    query: str | None = None,
) -> EmailListResult:
    """List recent emails.

    Convenience function using the global client.
    """
    return await get_gmail_client().list_emails(max_results=max_results, query=query)


async def list_unread_emails(
    max_results: int = DEFAULT_EMAIL_LIMIT,
    since_hours: int = 24,
) -> EmailListResult:
    """List unread emails from the last N hours.

    Convenience function using the global client.
    """
    return await get_gmail_client().list_unread(max_results=max_results, since_hours=since_hours)


async def list_emails_needing_response(
    max_results: int = 10,
    since_hours: int = 48,
) -> EmailListResult:
    """List emails that likely need a response.

    Convenience function using the global client.
    """
    return await get_gmail_client().list_needing_response(
        max_results=max_results,
        since_hours=since_hours,
    )


async def get_email_by_id(message_id: str) -> EmailMessage | None:
    """Get a single email by ID.

    Convenience function using the global client.
    """
    return await get_gmail_client().get_email(message_id)
