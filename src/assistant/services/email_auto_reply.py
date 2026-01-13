"""Gmail auto-reply service for Second Brain.

Implements pattern-based auto-reply per PRD Section 4.5 and 6.4:

Auto-send levels (PRD Section 4.5):
| Level | Trigger | Action |
|-------|---------|--------|
| Draft only | Default | Creates draft, notifies you |
| Send with confirmation | You say "email Mike about X" | Drafts, shows preview, waits for "send it" |
| Auto-send simple | Pattern established (3+ similar sent) | Sends, logs, shows in debrief |
| Auto-send complex | Future (high confidence + pattern) | Full autonomy with audit |

Per PRD Section 6.4:
- Send email draft: User says "send it" or confidence > 95% from pattern

Email Intelligence (PRD Section 4.5):
- Learns your writing style from sent folder
- Knows who you reply to quickly vs slowly
- Understands thread context
- Detects urgency from sender patterns

Dependencies:
- T-121: Gmail draft creation (complete)
- T-092: Pattern storage (complete)
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from assistant.google.gmail import (
    DraftResult,
    EmailMessage,
    GmailClient,
    SendResult,
    get_gmail_client,
)
from assistant.notion import NotionClient
from assistant.notion.schemas import Pattern

logger = logging.getLogger(__name__)

# Minimum replies to same sender before auto-reply is enabled
MIN_REPLIES_FOR_AUTO = 3

# Confidence threshold for automatic sending (PRD 6.4)
AUTO_SEND_CONFIDENCE_THRESHOLD = 95

# Pattern confidence threshold (matches pattern system)
PATTERN_CONFIDENCE_THRESHOLD = 70

# Hours to look back for sender patterns
SENDER_HISTORY_HOURS = 168  # 7 days

# Maximum age of sent emails to analyze for style
STYLE_ANALYSIS_MAX_AGE_DAYS = 30


@dataclass
class SenderPattern:
    """Pattern learned from replies to a specific sender."""

    sender_email: str
    sender_name: str
    reply_count: int = 0
    avg_reply_time_hours: float = 0.0
    typical_greeting: str = ""  # e.g., "Hi Mike,", "Hello,", ""
    typical_signoff: str = ""  # e.g., "Thanks,", "Best,", ""
    tone: str = "neutral"  # formal, casual, neutral
    last_reply_at: datetime | None = None
    confidence: int = 0  # 0-100


@dataclass
class ReplyContext:
    """Context for generating a reply."""

    original_email: EmailMessage
    sender_pattern: SenderPattern | None
    thread_emails: list[EmailMessage] = field(default_factory=list)
    suggested_content: str = ""
    urgency: str = "normal"  # urgent, normal, low


@dataclass
class AutoReplyResult:
    """Result of auto-reply analysis and action."""

    success: bool
    action: str  # "draft_created", "auto_sent", "skipped", "error"
    draft_result: DraftResult | None = None
    send_result: SendResult | None = None
    confidence: int = 0
    reason: str = ""
    sender_pattern: SenderPattern | None = None


class EmailAutoReplyService:
    """Service for pattern-based email auto-replies.

    Learns from sent emails to understand:
    - Writing style per sender
    - Reply timing patterns
    - Greeting/signoff preferences
    - Tone (formal vs casual)

    Uses patterns to:
    - Generate appropriate draft replies
    - Auto-send when confidence > 95% and pattern established
    """

    def __init__(
        self,
        gmail_client: GmailClient | None = None,
        notion_client: NotionClient | None = None,
    ):
        """Initialize the auto-reply service.

        Args:
            gmail_client: Optional GmailClient instance
            notion_client: Optional NotionClient instance for pattern storage
        """
        self._gmail = gmail_client
        self._notion = notion_client

        # In-memory cache of sender patterns
        self._sender_patterns: dict[str, SenderPattern] = {}

        # Cache of analyzed writing style
        self._style_cache: dict[str, Any] = {}

    @property
    def gmail(self) -> GmailClient:
        """Get or create GmailClient instance."""
        if self._gmail is None:
            self._gmail = get_gmail_client()
        return self._gmail

    @property
    def notion(self) -> NotionClient:
        """Get or create NotionClient instance."""
        if self._notion is None:
            self._notion = NotionClient()
        return self._notion

    async def analyze_sender_pattern(self, sender_email: str) -> SenderPattern:
        """Analyze reply patterns for a specific sender.

        Looks at sent emails to this address to learn:
        - How often we reply
        - Typical response time
        - Greeting and signoff style
        - Tone (formal/casual)

        Args:
            sender_email: Email address to analyze

        Returns:
            SenderPattern with learned characteristics
        """
        # Check cache first
        if sender_email in self._sender_patterns:
            pattern = self._sender_patterns[sender_email]
            # Return cached if recently updated
            if pattern.last_reply_at:
                age = datetime.now(ZoneInfo("UTC")) - pattern.last_reply_at.replace(
                    tzinfo=ZoneInfo("UTC")
                )
                if age < timedelta(hours=24):
                    return pattern

        # Query sent emails to this address
        query = f"to:{sender_email} in:sent"
        result = await self.gmail.list_emails(max_results=50, query=query)

        if not result.success or not result.emails:
            # No history - return empty pattern
            pattern = SenderPattern(
                sender_email=sender_email,
                sender_name=sender_email.split("@")[0].title(),
            )
            self._sender_patterns[sender_email] = pattern
            return pattern

        emails = result.emails

        # Calculate reply count and timing
        reply_count = len(emails)
        last_reply_at = emails[0].received_at if emails else None

        # Calculate average reply time (would need thread analysis)
        avg_reply_time = 0.0  # Default - would need thread correlation

        # Analyze greeting and signoff patterns
        greeting, signoff, tone = await self._analyze_style(emails)

        # Calculate confidence based on history depth
        confidence = min(100, reply_count * 15)  # 15% per reply, max 100%

        pattern = SenderPattern(
            sender_email=sender_email,
            sender_name=emails[0].sender_name if emails else sender_email.split("@")[0].title(),
            reply_count=reply_count,
            avg_reply_time_hours=avg_reply_time,
            typical_greeting=greeting,
            typical_signoff=signoff,
            tone=tone,
            last_reply_at=last_reply_at,
            confidence=confidence,
        )

        self._sender_patterns[sender_email] = pattern
        return pattern

    async def _analyze_style(
        self, sent_emails: list[EmailMessage]
    ) -> tuple[str, str, str]:
        """Analyze writing style from sent emails.

        Args:
            sent_emails: List of sent emails to analyze

        Returns:
            Tuple of (greeting, signoff, tone)
        """
        greetings: dict[str, int] = {}
        signoffs: dict[str, int] = {}
        formal_indicators = 0
        casual_indicators = 0

        # Common greeting patterns
        greeting_patterns = [
            r"^(Hi [A-Z][a-z]+,?)",
            r"^(Hello [A-Z][a-z]+,?)",
            r"^(Hey [A-Z][a-z]+,?)",
            r"^(Dear [A-Z][a-z]+,?)",
            r"^(Hi,)",
            r"^(Hello,)",
        ]

        # Common signoff patterns
        signoff_patterns = [
            r"(Thanks,?)$",
            r"(Thank you,?)$",
            r"(Best,?)$",
            r"(Best regards,?)$",
            r"(Regards,?)$",
            r"(Cheers,?)$",
            r"(Sincerely,?)$",
        ]

        for email in sent_emails[:20]:  # Analyze up to 20 recent emails
            snippet = email.snippet

            # Check greetings
            for pattern in greeting_patterns:
                match = re.search(pattern, snippet, re.MULTILINE)
                if match:
                    greeting = match.group(1)
                    greetings[greeting] = greetings.get(greeting, 0) + 1

                    # Tone indicators
                    if greeting.lower().startswith("hey"):
                        casual_indicators += 1
                    elif greeting.lower().startswith("dear"):
                        formal_indicators += 1
                    break

            # Check signoffs (in snippet, limited)
            for pattern in signoff_patterns:
                match = re.search(pattern, snippet, re.IGNORECASE)
                if match:
                    signoff = match.group(1)
                    signoffs[signoff] = signoffs.get(signoff, 0) + 1

                    # Tone indicators
                    if signoff.lower().startswith("cheers"):
                        casual_indicators += 1
                    elif signoff.lower().startswith("sincerely"):
                        formal_indicators += 1
                    break

        # Determine most common greeting and signoff
        typical_greeting = max(greetings, key=lambda k: greetings[k]) if greetings else ""
        typical_signoff = max(signoffs, key=lambda k: signoffs[k]) if signoffs else ""

        # Determine tone
        if formal_indicators > casual_indicators:
            tone = "formal"
        elif casual_indicators > formal_indicators:
            tone = "casual"
        else:
            tone = "neutral"

        return typical_greeting, typical_signoff, tone

    async def should_auto_reply(self, email: EmailMessage) -> tuple[bool, int, str]:
        """Determine if an email should get an auto-reply.

        Per PRD Section 6.4, auto-send requires:
        - Confidence > 95% from pattern, OR
        - Pattern established (3+ similar sent)

        Args:
            email: The incoming email to analyze

        Returns:
            Tuple of (should_auto_reply, confidence, reason)
        """
        # Get sender pattern
        pattern = await self.analyze_sender_pattern(email.sender_email)

        # Check if we have enough history
        if pattern.reply_count < MIN_REPLIES_FOR_AUTO:
            return (
                False,
                pattern.confidence,
                f"Insufficient history: {pattern.reply_count}/{MIN_REPLIES_FOR_AUTO} replies",
            )

        # Check confidence threshold
        if pattern.confidence < AUTO_SEND_CONFIDENCE_THRESHOLD:
            return (
                False,
                pattern.confidence,
                f"Confidence too low: {pattern.confidence}% < {AUTO_SEND_CONFIDENCE_THRESHOLD}%",
            )

        # Check if this looks like a simple reply scenario
        if email.needs_response and pattern.reply_count >= MIN_REPLIES_FOR_AUTO:
            return (
                True,
                pattern.confidence,
                f"Pattern established: {pattern.reply_count} replies, {pattern.confidence}% confidence",
            )

        return (
            False,
            pattern.confidence,
            "Email does not appear to need auto-response",
        )

    async def generate_reply_content(
        self,
        email: EmailMessage,
        sender_pattern: SenderPattern,
        user_guidance: str | None = None,
    ) -> str:
        """Generate reply content based on patterns and context.

        Args:
            email: Email to reply to
            sender_pattern: Learned sender pattern
            user_guidance: Optional user input for reply content

        Returns:
            Generated reply content
        """
        lines: list[str] = []

        # Add greeting
        if sender_pattern.typical_greeting:
            # Personalize greeting with sender's first name
            greeting = sender_pattern.typical_greeting
            if "[Name]" not in greeting and sender_pattern.sender_name:
                first_name = sender_pattern.sender_name.split()[0]
                # Replace generic greeting with personalized
                greeting = re.sub(r"Hi,?$", f"Hi {first_name},", greeting)
                greeting = re.sub(r"Hello,?$", f"Hello {first_name},", greeting)
            lines.append(greeting)
            lines.append("")

        # Add body (from user guidance or placeholder)
        if user_guidance:
            lines.append(user_guidance)
        else:
            lines.append("[Reply content here]")

        lines.append("")

        # Add signoff
        if sender_pattern.typical_signoff:
            lines.append(sender_pattern.typical_signoff)

        return "\n".join(lines)

    async def create_reply_draft(
        self,
        email: EmailMessage,
        user_guidance: str | None = None,
    ) -> AutoReplyResult:
        """Create a draft reply to an email.

        This is the default action per PRD Section 4.5: "Draft only (default)"

        Args:
            email: Email to reply to
            user_guidance: Optional user input for reply content

        Returns:
            AutoReplyResult with draft details
        """
        # Get sender pattern
        pattern = await self.analyze_sender_pattern(email.sender_email)

        # Generate reply content
        content = await self.generate_reply_content(email, pattern, user_guidance)

        # Create draft
        subject = email.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        draft_result = await self.gmail.create_draft(
            to=[email.sender_email],
            subject=subject,
            body=content,
            thread_id=email.thread_id,
            in_reply_to=email.message_id,
        )

        return AutoReplyResult(
            success=draft_result.success,
            action="draft_created" if draft_result.success else "error",
            draft_result=draft_result,
            confidence=pattern.confidence,
            reason="Draft created for review" if draft_result.success else draft_result.error or "",
            sender_pattern=pattern,
        )

    async def process_auto_reply(
        self,
        email: EmailMessage,
        force_draft: bool = False,
    ) -> AutoReplyResult:
        """Process an email for potential auto-reply.

        Per PRD Section 4.5 and 6.4:
        - If pattern established and confidence > 95%: auto-send
        - Otherwise: create draft

        Args:
            email: Email to process
            force_draft: If True, always create draft instead of auto-sending

        Returns:
            AutoReplyResult with action taken
        """
        # Check if we should auto-reply
        should_auto, confidence, reason = await self.should_auto_reply(email)

        # Get sender pattern
        pattern = await self.analyze_sender_pattern(email.sender_email)

        if not email.needs_response:
            return AutoReplyResult(
                success=True,
                action="skipped",
                confidence=confidence,
                reason="Email does not appear to need response",
                sender_pattern=pattern,
            )

        if force_draft or not should_auto:
            # Create draft for review
            return await self.create_reply_draft(email)

        # Auto-send - generate and send immediately
        content = await self.generate_reply_content(email, pattern)

        subject = email.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        send_result = await self.gmail.send_email(
            to=[email.sender_email],
            subject=subject,
            body=content,
            thread_id=email.thread_id,
            in_reply_to=email.message_id,
        )

        return AutoReplyResult(
            success=send_result.success,
            action="auto_sent" if send_result.success else "error",
            send_result=send_result,
            confidence=confidence,
            reason=reason if send_result.success else send_result.error or "",
            sender_pattern=pattern,
        )

    async def store_reply_pattern(
        self,
        sender_email: str,
        pattern_data: dict[str, Any],
    ) -> bool:
        """Store a reply pattern to Notion Patterns database.

        Args:
            sender_email: Email address the pattern is for
            pattern_data: Pattern data to store

        Returns:
            True if stored successfully
        """
        try:
            pattern = Pattern(
                trigger=f"email_from:{sender_email}",
                meaning=str(pattern_data),
                confidence=pattern_data.get("confidence", 50),
            )
            await self.notion.create_pattern(pattern)
            return True
        except Exception as e:
            logger.warning(f"Failed to store email pattern: {e}")
            return False

    async def load_reply_patterns(self) -> dict[str, SenderPattern]:
        """Load stored reply patterns from Notion.

        Returns:
            Dict mapping sender email to SenderPattern
        """
        try:
            # Query patterns with email_from: trigger prefix
            patterns = await self.notion.query_patterns(
                trigger="email_from:",
                min_confidence=PATTERN_CONFIDENCE_THRESHOLD,
            )

            loaded: dict[str, SenderPattern] = {}
            for pattern_dict in patterns:
                # Extract sender email from trigger (patterns is list[dict])
                trigger = pattern_dict.get("trigger", "")
                if trigger.startswith("email_from:"):
                    sender_email = trigger.replace("email_from:", "")
                    # Parse meaning as pattern data
                    # Note: In production, this would be JSON
                    loaded[sender_email] = SenderPattern(
                        sender_email=sender_email,
                        sender_name=sender_email.split("@")[0].title(),
                        confidence=pattern_dict.get("confidence", 50),
                    )

            return loaded
        except Exception as e:
            logger.warning(f"Failed to load email patterns: {e}")
            return {}

    def clear_cache(self) -> None:
        """Clear sender pattern cache."""
        self._sender_patterns.clear()
        self._style_cache.clear()


# Module-level singleton instance
_auto_reply_service: EmailAutoReplyService | None = None


def get_auto_reply_service() -> EmailAutoReplyService:
    """Get or create the global EmailAutoReplyService instance."""
    global _auto_reply_service
    if _auto_reply_service is None:
        _auto_reply_service = EmailAutoReplyService()
    return _auto_reply_service


# Convenience functions


async def analyze_sender_pattern(sender_email: str) -> SenderPattern:
    """Analyze reply patterns for a sender.

    Convenience function using global service.
    """
    return await get_auto_reply_service().analyze_sender_pattern(sender_email)


async def should_auto_reply(email: EmailMessage) -> tuple[bool, int, str]:
    """Check if email should get auto-reply.

    Convenience function using global service.
    """
    return await get_auto_reply_service().should_auto_reply(email)


async def create_reply_draft(
    email: EmailMessage,
    user_guidance: str | None = None,
) -> AutoReplyResult:
    """Create a draft reply to an email.

    Convenience function using global service.
    """
    return await get_auto_reply_service().create_reply_draft(email, user_guidance)


async def process_auto_reply(
    email: EmailMessage,
    force_draft: bool = False,
) -> AutoReplyResult:
    """Process an email for auto-reply.

    Convenience function using global service.
    """
    return await get_auto_reply_service().process_auto_reply(email, force_draft)
