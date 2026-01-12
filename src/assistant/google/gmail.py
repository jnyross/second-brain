"""Gmail integration for Second Brain.

Read emails for morning briefings and context.
Create drafts and send emails with user confirmation.

Per PRD Section 4.5:
- Fetch recent emails for morning briefing
- Search emails by sender, subject, date
- Extract action items from emails
- Identify emails needing response
- Link email threads to People and Projects
- Draft emails for review
- Send emails with confirmation

Per PRD Section 6.3:
- Send email requires confirmation (show draft first)

OAuth scopes required:
- https://www.googleapis.com/auth/gmail.readonly
- https://www.googleapis.com/auth/gmail.send
- https://www.googleapis.com/auth/gmail.compose
"""

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Any, cast
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from assistant.google.auth import google_auth

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


@dataclass
class DraftResult:
    """Result of creating or retrieving a draft.

    Per PRD Section 4.5, drafts are created for review before sending.
    The html_link allows the user to view/edit the draft in Gmail UI.
    """

    success: bool
    draft_id: str | None = None
    message_id: str | None = None
    thread_id: str | None = None
    subject: str = ""
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    body: str = ""
    html_link: str | None = None
    error: str | None = None

    @property
    def preview(self) -> str:
        """Generate a preview of the draft for display to user.

        Returns:
            Formatted preview string
        """
        if not self.success:
            return f"Draft failed: {self.error}"

        lines = [
            f"**To:** {', '.join(self.to)}",
        ]
        if self.cc:
            lines.append(f"**CC:** {', '.join(self.cc)}")
        lines.extend(
            [
                f"**Subject:** {self.subject}",
                "",
                self.body[:500] + ("..." if len(self.body) > 500 else ""),
            ]
        )
        return "\n".join(lines)


@dataclass
class SendResult:
    """Result of sending an email.

    Per PRD Section 6.3, emails require confirmation before sending.
    The sent email cannot be undone (Table row: "Email sent - Cannot undo").
    """

    success: bool
    message_id: str | None = None
    thread_id: str | None = None
    error: str | None = None


class GmailClient:
    """Gmail client for reading emails and composing drafts.

    Provides Gmail access per PRD Section 4.5:
    Read (Low-risk, autonomous):
    - List recent emails
    - Search emails by query
    - Get email details
    - Detect emails needing response

    Write (Medium-risk, tiered autonomy per PRD Section 6.3):
    - Create drafts for review (default)
    - Send emails with confirmation
    - Reply to threads (with learned patterns)
    """

    def __init__(self) -> None:
        """Initialize the Gmail client."""
        self._service: Any = None
        self._action_patterns = [re.compile(p, re.IGNORECASE) for p in ACTION_PATTERNS]

    @property
    def service(self) -> Any:
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
            def do_list() -> dict[str, Any]:
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

                response = self.service.users().messages().list(**kwargs).execute()
                return cast(dict[str, Any], response)

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

            def do_get() -> dict[str, Any]:
                return cast(
                    dict[str, Any],
                    (
                        self.service.users()
                        .messages()
                        .get(userId="me", id=message_id, format="metadata")
                        .execute()
                    ),
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
            headers = {
                h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])
            }

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
        if any(
            word in text for word in ["urgent", "asap", "priority", "time-sensitive", "critical"]
        ):
            return "high"

        # Low priority indicators
        if any(
            label in labels
            for label in ["CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES"]
        ):
            return "low"

        return "normal"

    # =========================================================================
    # Draft and Send Methods (PRD Section 4.5 - Write capabilities)
    # =========================================================================

    async def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
    ) -> DraftResult:
        """Create an email draft for review before sending.

        Per PRD Section 4.5: "Draft only (default) - Creates draft, notifies you"
        Per PRD Section 6.3: "Send email - Yes - show draft first"

        Args:
            to: List of recipient email addresses
            subject: Email subject line
            body: Plain text email body
            cc: Optional list of CC recipients
            bcc: Optional list of BCC recipients
            thread_id: Optional thread ID for replies
            in_reply_to: Optional message ID being replied to

        Returns:
            DraftResult with draft details and preview
        """
        if not self.is_authenticated():
            return DraftResult(
                success=False,
                error="Gmail not authenticated. Please run OAuth flow first.",
            )

        if not to:
            return DraftResult(
                success=False,
                error="At least one recipient is required.",
            )

        try:
            import asyncio
            from email.mime.text import MIMEText

            loop = asyncio.get_event_loop()

            # Build the MIME message
            message = MIMEText(body)
            message["to"] = ", ".join(to)
            message["subject"] = subject
            if cc:
                message["cc"] = ", ".join(cc)
            if bcc:
                message["bcc"] = ", ".join(bcc)
            if in_reply_to:
                message["In-Reply-To"] = in_reply_to
                message["References"] = in_reply_to

            # Encode the message
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            # Create the draft body
            draft_body: dict[str, Any] = {
                "message": {
                    "raw": raw,
                }
            }
            if thread_id:
                draft_body["message"]["threadId"] = thread_id

            def do_create() -> dict[str, Any]:
                response = (
                    self.service.users().drafts().create(userId="me", body=draft_body).execute()
                )
                return cast(dict[str, Any], response)

            result = await loop.run_in_executor(None, do_create)

            draft_id = result.get("id", "")
            msg = result.get("message", {})
            message_id = msg.get("id", "")
            result_thread_id = msg.get("threadId", "")

            # Generate Gmail web link to the draft
            html_link = f"https://mail.google.com/mail/u/0/#drafts?compose={draft_id}"

            logger.info(f"Created Gmail draft {draft_id} to {to}")

            return DraftResult(
                success=True,
                draft_id=draft_id,
                message_id=message_id,
                thread_id=result_thread_id,
                subject=subject,
                to=to,
                cc=cc or [],
                bcc=bcc or [],
                body=body,
                html_link=html_link,
            )

        except HttpError as e:
            logger.exception(f"Gmail API error creating draft: {e}")
            return DraftResult(
                success=False,
                error=f"Gmail API error: {e.reason if hasattr(e, 'reason') else str(e)}",
            )
        except Exception as e:
            logger.exception(f"Failed to create draft: {e}")
            return DraftResult(
                success=False,
                error=f"Failed to create draft: {str(e)}",
            )

    async def get_draft(self, draft_id: str) -> DraftResult:
        """Retrieve an existing draft for preview.

        Args:
            draft_id: Gmail draft ID

        Returns:
            DraftResult with draft details
        """
        if not self.is_authenticated():
            return DraftResult(
                success=False,
                error="Gmail not authenticated.",
            )

        try:
            import asyncio

            loop = asyncio.get_event_loop()

            def do_get() -> dict[str, Any]:
                return cast(
                    dict[str, Any],
                    (
                        self.service.users()
                        .drafts()
                        .get(userId="me", id=draft_id, format="full")
                        .execute()
                    ),
                )

            result = await loop.run_in_executor(None, do_get)

            msg = result.get("message", {})
            message_id = msg.get("id", "")
            thread_id = msg.get("threadId", "")

            # Parse headers
            headers = {
                h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])
            }

            subject = headers.get("subject", "(no subject)")
            to_raw = headers.get("to", "")
            cc_raw = headers.get("cc", "")
            bcc_raw = headers.get("bcc", "")

            # Parse recipients
            to = [addr.strip() for addr in to_raw.split(",") if addr.strip()]
            cc = [addr.strip() for addr in cc_raw.split(",") if addr.strip()]
            bcc = [addr.strip() for addr in bcc_raw.split(",") if addr.strip()]

            # Extract body
            body = self._extract_body(msg.get("payload", {}))

            html_link = f"https://mail.google.com/mail/u/0/#drafts?compose={draft_id}"

            return DraftResult(
                success=True,
                draft_id=draft_id,
                message_id=message_id,
                thread_id=thread_id,
                subject=subject,
                to=to,
                cc=cc,
                bcc=bcc,
                body=body,
                html_link=html_link,
            )

        except HttpError as e:
            logger.exception(f"Gmail API error getting draft: {e}")
            return DraftResult(
                success=False,
                error=f"Gmail API error: {e.reason if hasattr(e, 'reason') else str(e)}",
            )
        except Exception as e:
            logger.exception(f"Failed to get draft: {e}")
            return DraftResult(
                success=False,
                error=f"Failed to get draft: {str(e)}",
            )

    async def send_draft(self, draft_id: str) -> SendResult:
        """Send an existing draft.

        Per PRD Section 6.3: User must confirm before sending.
        Per PRD Section 6.2: "Email sent - Cannot undo - Log only"

        Args:
            draft_id: Gmail draft ID to send

        Returns:
            SendResult with sent message details
        """
        if not self.is_authenticated():
            return SendResult(
                success=False,
                error="Gmail not authenticated.",
            )

        try:
            import asyncio

            loop = asyncio.get_event_loop()

            def do_send() -> dict[str, Any]:
                return cast(
                    dict[str, Any],
                    (
                        self.service.users()
                        .drafts()
                        .send(userId="me", body={"id": draft_id})
                        .execute()
                    ),
                )

            result = await loop.run_in_executor(None, do_send)

            message_id = result.get("id", "")
            thread_id = result.get("threadId", "")

            logger.info(f"Sent draft {draft_id} as message {message_id}")

            return SendResult(
                success=True,
                message_id=message_id,
                thread_id=thread_id,
            )

        except HttpError as e:
            logger.exception(f"Gmail API error sending draft: {e}")
            return SendResult(
                success=False,
                error=f"Gmail API error: {e.reason if hasattr(e, 'reason') else str(e)}",
            )
        except Exception as e:
            logger.exception(f"Failed to send draft: {e}")
            return SendResult(
                success=False,
                error=f"Failed to send draft: {str(e)}",
            )

    async def delete_draft(self, draft_id: str) -> bool:
        """Delete a draft.

        Used when user cancels sending after reviewing.

        Args:
            draft_id: Gmail draft ID to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        if not self.is_authenticated():
            return False

        try:
            import asyncio

            loop = asyncio.get_event_loop()

            def do_delete() -> None:
                self.service.users().drafts().delete(userId="me", id=draft_id).execute()

            await loop.run_in_executor(None, do_delete)

            logger.info(f"Deleted draft {draft_id}")
            return True

        except Exception as e:
            logger.warning(f"Failed to delete draft {draft_id}: {e}")
            return False

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
    ) -> SendResult:
        """Send an email directly (without creating a visible draft).

        This is a convenience method that creates and immediately sends.
        Per PRD Section 6.3, this should only be used after user confirmation.

        Args:
            to: List of recipient email addresses
            subject: Email subject line
            body: Plain text email body
            cc: Optional list of CC recipients
            bcc: Optional list of BCC recipients
            thread_id: Optional thread ID for replies
            in_reply_to: Optional message ID being replied to

        Returns:
            SendResult with sent message details
        """
        if not self.is_authenticated():
            return SendResult(
                success=False,
                error="Gmail not authenticated.",
            )

        if not to:
            return SendResult(
                success=False,
                error="At least one recipient is required.",
            )

        try:
            import asyncio
            from email.mime.text import MIMEText

            loop = asyncio.get_event_loop()

            # Build the MIME message
            message = MIMEText(body)
            message["to"] = ", ".join(to)
            message["subject"] = subject
            if cc:
                message["cc"] = ", ".join(cc)
            if bcc:
                message["bcc"] = ", ".join(bcc)
            if in_reply_to:
                message["In-Reply-To"] = in_reply_to
                message["References"] = in_reply_to

            # Encode the message
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            # Create the send body
            send_body: dict[str, Any] = {"raw": raw}
            if thread_id:
                send_body["threadId"] = thread_id

            def do_send() -> dict[str, Any]:
                response = (
                    self.service.users().messages().send(userId="me", body=send_body).execute()
                )
                return cast(dict[str, Any], response)

            result = await loop.run_in_executor(None, do_send)

            message_id = result.get("id", "")
            result_thread_id = result.get("threadId", "")

            logger.info(f"Sent email {message_id} to {to}")

            return SendResult(
                success=True,
                message_id=message_id,
                thread_id=result_thread_id,
            )

        except HttpError as e:
            logger.exception(f"Gmail API error sending email: {e}")
            return SendResult(
                success=False,
                error=f"Gmail API error: {e.reason if hasattr(e, 'reason') else str(e)}",
            )
        except Exception as e:
            logger.exception(f"Failed to send email: {e}")
            return SendResult(
                success=False,
                error=f"Failed to send email: {str(e)}",
            )

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Extract plain text body from message payload.

        Args:
            payload: Message payload from Gmail API

        Returns:
            Plain text body content
        """
        # Check for simple body
        body_data = payload.get("body", {}).get("data")
        if body_data:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

        # Check multipart
        parts = payload.get("parts", [])
        for part in parts:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            # Recurse into nested parts
            if part.get("parts"):
                nested = self._extract_body(part)
                if nested:
                    return nested

        return ""


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


# =============================================================================
# Draft and Send Convenience Functions (PRD Section 4.5)
# =============================================================================


async def create_draft(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
) -> DraftResult:
    """Create an email draft for review.

    Per PRD Section 4.5: Default action is draft-only.
    Convenience function using the global client.
    """
    return await get_gmail_client().create_draft(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
    )


async def get_draft(draft_id: str) -> DraftResult:
    """Get a draft by ID for preview.

    Convenience function using the global client.
    """
    return await get_gmail_client().get_draft(draft_id)


async def send_draft(draft_id: str) -> SendResult:
    """Send an existing draft.

    Per PRD Section 6.3: User must confirm before calling this.
    Convenience function using the global client.
    """
    return await get_gmail_client().send_draft(draft_id)


async def delete_draft(draft_id: str) -> bool:
    """Delete a draft.

    Convenience function using the global client.
    """
    return await get_gmail_client().delete_draft(draft_id)


async def send_email(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
) -> SendResult:
    """Send an email directly.

    Per PRD Section 6.3: This should only be called after user confirmation.
    Convenience function using the global client.
    """
    return await get_gmail_client().send_email(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
    )
