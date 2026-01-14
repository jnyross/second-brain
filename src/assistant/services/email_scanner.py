"""Background email scanner service.

Periodically scans Gmail inbox, analyzes emails with LLM,
and stores important ones in Notion for tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from assistant.config import settings
from assistant.google.auth import google_auth
from assistant.google.gmail import GmailClient
from assistant.notion.client import NotionClient
from assistant.notion.schemas import Email
from assistant.services.email_intelligence import (
    EmailAnalysis,
    get_email_intelligence_service,
)

logger = logging.getLogger(__name__)

# Default scan interval in seconds (5 minutes)
DEFAULT_SCAN_INTERVAL = 300

# Path for tracking processed emails
PROCESSED_EMAILS_PATH = Path.home() / ".second-brain" / "email-scanner" / "processed.json"


@dataclass
class ScanResult:
    """Result of an email scan cycle."""

    timestamp: datetime
    emails_fetched: int = 0
    emails_analyzed: int = 0
    emails_stored: int = 0
    emails_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True if scan completed without errors."""
        return len(self.errors) == 0


class EmailScannerService:
    """Background service for scanning and analyzing emails.

    Follows the same lifecycle pattern as HeartbeatService:
    - start() begins the background loop
    - stop() gracefully shuts down
    - Sends results to Notion for persistence
    """

    def __init__(
        self,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        importance_threshold: int = 50,
        max_emails_per_scan: int = 50,
    ):
        """Initialize the email scanner.

        Args:
            scan_interval: Seconds between scans
            importance_threshold: Minimum score to store in Notion
            max_emails_per_scan: Maximum emails to process per cycle
        """
        self._interval = scan_interval
        self._importance_threshold = importance_threshold
        self._max_emails = max_emails_per_scan
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_result: ScanResult | None = None
        self._processed_ids: set[str] = set()
        self._gmail_client: GmailClient | None = None
        self._notion_client: NotionClient | None = None

    @property
    def is_configured(self) -> bool:
        """Check if email scanning is configured."""
        return (
            settings.email_scan_enabled
            and settings.has_openrouter
            and settings.notion_emails_db_id
            and google_auth.is_authenticated()
        )

    @property
    def is_running(self) -> bool:
        """Check if scanner loop is running."""
        return self._running

    @property
    def last_result(self) -> ScanResult | None:
        """Get the last scan result."""
        return self._last_result

    @property
    def interval(self) -> int:
        """Get scan interval in seconds."""
        return self._interval

    def _load_processed_ids(self) -> None:
        """Load set of already processed email IDs from disk."""
        if PROCESSED_EMAILS_PATH.exists():
            try:
                with open(PROCESSED_EMAILS_PATH) as f:
                    data = json.load(f)
                    self._processed_ids = set(data.get("processed_ids", []))
                    logger.debug("Loaded %d processed email IDs", len(self._processed_ids))
            except Exception as e:
                logger.warning("Failed to load processed IDs: %s", e)
                self._processed_ids = set()
        else:
            self._processed_ids = set()

    def _save_processed_ids(self) -> None:
        """Save processed email IDs to disk."""
        try:
            PROCESSED_EMAILS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(PROCESSED_EMAILS_PATH, "w") as f:
                json.dump(
                    {
                        "processed_ids": list(self._processed_ids),
                        "last_updated": datetime.now(UTC).isoformat(),
                    },
                    f,
                )
        except Exception as e:
            logger.warning("Failed to save processed IDs: %s", e)

    async def start(self) -> None:
        """Start the email scanner loop."""
        if not self.is_configured:
            reasons = []
            if not settings.email_scan_enabled:
                reasons.append("EMAIL_SCAN_ENABLED=false")
            if not settings.has_openrouter:
                reasons.append("OPENROUTER_API_KEY not set")
            if not settings.notion_emails_db_id:
                reasons.append("NOTION_EMAILS_DB_ID not set")
            if not google_auth.is_authenticated():
                reasons.append("Google not authenticated")
            logger.info(
                "Email scanner not configured: %s",
                ", ".join(reasons) if reasons else "unknown",
            )
            return

        if self._running:
            logger.warning("Email scanner already running")
            return

        self._running = True
        self._load_processed_ids()
        logger.info("Starting email scanner (interval: %ds)", self._interval)

        # Initialize clients
        self._gmail_client = GmailClient()
        self._notion_client = NotionClient()

        # Run initial scan
        await self._scan_emails()

        # Start background loop
        self._task = asyncio.create_task(self._scan_loop())

    async def stop(self) -> None:
        """Stop the email scanner loop."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Save processed IDs
        self._save_processed_ids()

        # Cleanup clients
        if self._notion_client:
            await self._notion_client.close()
            self._notion_client = None

        self._gmail_client = None

        logger.info("Email scanner stopped")

    async def _scan_loop(self) -> None:
        """Background loop that scans emails periodically."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                if self._running:
                    await self._scan_emails()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in email scan loop: %s", e)

    async def _scan_emails(self) -> ScanResult:
        """Perform a single email scan cycle."""
        result = ScanResult(timestamp=datetime.now(UTC))

        try:
            if not self._gmail_client:
                self._gmail_client = GmailClient()

            # Fetch recent unread emails
            emails = self._gmail_client.list_emails(
                max_results=self._max_emails,
                label_ids=["INBOX"],
                query="is:unread",
            )
            result.emails_fetched = len(emails)
            logger.info("Fetched %d emails for analysis", len(emails))

            # Get intelligence service
            intelligence = get_email_intelligence_service()

            for email in emails:
                # Skip if already processed
                if email.gmail_id in self._processed_ids:
                    result.emails_skipped += 1
                    continue

                try:
                    # Analyze with LLM
                    analysis = intelligence.analyze_email(email)
                    result.emails_analyzed += 1

                    # Store if important enough
                    if analysis.importance_score >= self._importance_threshold:
                        await self._store_email(email, analysis)
                        result.emails_stored += 1
                        logger.info(
                            "Stored important email: %s (score=%d)",
                            email.subject[:50],
                            analysis.importance_score,
                        )

                    # Mark as processed
                    self._processed_ids.add(email.gmail_id)

                except Exception as e:
                    logger.error("Failed to process email %s: %s", email.gmail_id, e)
                    result.errors.append(f"{email.gmail_id}: {e}")

            # Periodically save processed IDs
            self._save_processed_ids()

        except Exception as e:
            logger.exception("Email scan failed: %s", e)
            result.errors.append(str(e))

        self._last_result = result
        logger.info(
            "Scan complete: fetched=%d, analyzed=%d, stored=%d, skipped=%d, errors=%d",
            result.emails_fetched,
            result.emails_analyzed,
            result.emails_stored,
            result.emails_skipped,
            len(result.errors),
        )
        return result

    async def _store_email(
        self,
        gmail_email: Any,  # EmailMessage from gmail.py
        analysis: EmailAnalysis,
    ) -> str:
        """Store an analyzed email in Notion."""
        if not self._notion_client:
            self._notion_client = NotionClient()

        # Create Email schema object
        email = Email(
            gmail_id=gmail_email.gmail_id,
            thread_id=gmail_email.thread_id,
            subject=gmail_email.subject,
            from_address=gmail_email.from_address,
            to_address=gmail_email.to_addresses[0] if gmail_email.to_addresses else None,
            snippet=gmail_email.snippet,
            body_preview=(gmail_email.body_text or gmail_email.body_html or "")[:500],
            received_at=gmail_email.date or datetime.now(UTC),
            has_attachments=gmail_email.has_attachments,
            labels=gmail_email.labels,
            importance_score=analysis.importance_score,
            urgency=analysis.urgency,
            action_items=analysis.action_items,
            people_mentioned=analysis.people_mentioned,
            suggested_response=analysis.suggested_response,
            category=analysis.category,
            analyzed_at=analysis.analyzed_at,
            processed=True,
            needs_response=analysis.needs_response,
        )

        # Store in Notion
        page_id = await self._notion_client.create_email(email)
        return page_id

    async def scan_now(self) -> ScanResult:
        """Trigger an immediate scan (for CLI/manual use)."""
        return await self._scan_emails()


# Module-level singleton
_scanner_service: EmailScannerService | None = None


def get_email_scanner_service() -> EmailScannerService:
    """Get or create the email scanner service singleton."""
    global _scanner_service
    if _scanner_service is None:
        _scanner_service = EmailScannerService(
            scan_interval=settings.email_scan_interval,
            importance_threshold=settings.email_importance_threshold,
        )
    return _scanner_service


async def start_email_scanner() -> None:
    """Start the email scanner (convenience function)."""
    await get_email_scanner_service().start()


async def stop_email_scanner() -> None:
    """Stop the email scanner (convenience function)."""
    await get_email_scanner_service().stop()


async def scan_emails_now() -> ScanResult:
    """Trigger immediate email scan (convenience function)."""
    return await get_email_scanner_service().scan_now()


def is_email_scanner_configured() -> bool:
    """Check if email scanner is properly configured."""
    return get_email_scanner_service().is_configured
