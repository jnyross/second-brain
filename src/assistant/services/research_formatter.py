"""Research result formatter service.

Formats and stores research results per PRD Section 4.10:
- Format results for Telegram display
- Log research to audit system with sources
- Store results in relevant task/note

T-104: Build research result formatter
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from assistant.notion.schemas import ActionType
from assistant.services.audit import AuditEntry, AuditLogger, get_audit_logger
from assistant.services.research import ResearchResult, ResearchSource

logger = logging.getLogger(__name__)


# Maximum lengths for various output formats
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
MAX_FINDING_LENGTH = 200
MAX_FINDINGS_IN_BRIEF = 5
MAX_FINDINGS_IN_DETAILED = 15
MAX_SOURCES_DISPLAYED = 5


@dataclass
class FormattedResearch:
    """Formatted research result for display/storage.

    Attributes:
        success: Whether formatting succeeded
        telegram_message: Formatted message for Telegram
        telegram_brief: Shortened version for inline display
        log_summary: Summary for audit log
        sources_text: Formatted sources list
        error: Error message if formatting failed
    """

    success: bool = True
    telegram_message: str = ""
    telegram_brief: str = ""
    log_summary: str = ""
    sources_text: str = ""
    findings_count: int = 0
    sources_count: int = 0
    screenshot_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "telegram_message": self.telegram_message,
            "telegram_brief": self.telegram_brief,
            "log_summary": self.log_summary,
            "sources_text": self.sources_text,
            "findings_count": self.findings_count,
            "sources_count": self.sources_count,
            "screenshot_count": self.screenshot_count,
            "error": self.error,
        }


class ResearchFormatter:
    """Formats and stores research results.

    Handles formatting research results for:
    - Telegram messages (brief and detailed)
    - Audit log entries
    - Notion storage

    Example:
        formatter = ResearchFormatter()
        result = await researcher.research_cinema("Everyman", "Friday")
        formatted = formatter.format_for_telegram(result)
        await formatter.log_research(result)
    """

    def __init__(
        self,
        audit_logger: AuditLogger | None = None,
        notion_client: Any | None = None,
    ) -> None:
        """Initialize the formatter.

        Args:
            audit_logger: AuditLogger instance for logging research
            notion_client: NotionClient for storing results
        """
        self._audit_logger = audit_logger
        self._notion = notion_client

    @property
    def audit_logger(self) -> AuditLogger:
        """Get or create audit logger."""
        if self._audit_logger is None:
            self._audit_logger = get_audit_logger()
        return self._audit_logger

    def format_for_telegram(
        self,
        result: ResearchResult,
        detailed: bool = True,
    ) -> FormattedResearch:
        """Format research result for Telegram display.

        Args:
            result: ResearchResult from web research
            detailed: Whether to include full details or brief summary

        Returns:
            FormattedResearch with telegram_message and telegram_brief
        """
        if not result.success:
            return FormattedResearch(
                success=False,
                telegram_message=f"❌ Research failed: {result.error}",
                telegram_brief="❌ Research failed",
                log_summary=f"Research failed: {result.error}",
                error=result.error,
            )

        # Build the message
        lines: list[str] = []

        # Header with query
        lines.append(f"🔍 **Research: {result.query}**")
        lines.append("")

        # Findings section
        if result.findings:
            findings_limit = MAX_FINDINGS_IN_DETAILED if detailed else MAX_FINDINGS_IN_BRIEF
            displayed_findings = result.findings[:findings_limit]

            lines.append(f"**Found {len(result.findings)} items:**")
            for finding in displayed_findings:
                # Truncate long findings
                if len(finding) > MAX_FINDING_LENGTH:
                    finding = finding[: MAX_FINDING_LENGTH - 3] + "..."
                lines.append(f"• {finding}")

            if len(result.findings) > findings_limit:
                remaining = len(result.findings) - findings_limit
                lines.append(f"_...and {remaining} more_")
        else:
            lines.append("_No specific findings extracted._")

        lines.append("")

        # Sources section
        if result.sources:
            sources_limit = MAX_SOURCES_DISPLAYED
            displayed_sources = result.sources[:sources_limit]

            lines.append(f"**Sources ({len(result.sources)}):**")
            for source in displayed_sources:
                source_line = self._format_source(source)
                lines.append(f"• {source_line}")

            if len(result.sources) > sources_limit:
                remaining = len(result.sources) - sources_limit
                lines.append(f"_...and {remaining} more sources_")

        # Screenshots note
        if result.screenshot_paths:
            lines.append("")
            lines.append(f"📷 {len(result.screenshot_paths)} screenshot(s) captured")

        # Duration
        if result.duration_seconds:
            lines.append(f"⏱️ Completed in {result.duration_seconds:.1f}s")

        telegram_message = "\n".join(lines)

        # Truncate if too long for Telegram
        if len(telegram_message) > MAX_TELEGRAM_MESSAGE_LENGTH:
            telegram_message = telegram_message[: MAX_TELEGRAM_MESSAGE_LENGTH - 100]
            telegram_message += "\n\n_[Message truncated - use /debrief for full results]_"

        # Build brief version
        telegram_brief = self._format_brief(result)

        # Build sources text
        sources_text = self._format_sources_text(result.sources)

        # Build log summary
        log_summary = self._format_log_summary(result)

        return FormattedResearch(
            success=True,
            telegram_message=telegram_message,
            telegram_brief=telegram_brief,
            log_summary=log_summary,
            sources_text=sources_text,
            findings_count=len(result.findings),
            sources_count=len(result.sources),
            screenshot_count=len(result.screenshot_paths),
        )

    def _format_source(self, source: ResearchSource) -> str:
        """Format a single source for display.

        Args:
            source: ResearchSource to format

        Returns:
            Formatted source string
        """
        if source.title:
            # Use title if available
            title = source.title
            if len(title) > 50:
                title = title[:47] + "..."
            return f"[{title}]({source.url})"
        else:
            # Just show domain
            try:
                from urllib.parse import urlparse

                domain = urlparse(source.url).netloc
                return f"[{domain}]({source.url})"
            except Exception:
                return source.url

    def _format_brief(self, result: ResearchResult) -> str:
        """Format a brief one-line summary.

        Args:
            result: ResearchResult to summarize

        Returns:
            Brief summary string
        """
        if not result.success:
            return f"❌ Research failed: {result.error}"

        findings_count = len(result.findings)
        sources_count = len(result.sources)

        if findings_count > 0:
            first_finding = result.findings[0]
            if len(first_finding) > 50:
                first_finding = first_finding[:47] + "..."
            return f"🔍 Found {findings_count} items: {first_finding}"
        else:
            return f"🔍 Searched {sources_count} source(s), no specific items found"

    def _format_sources_text(self, sources: list[ResearchSource]) -> str:
        """Format sources as plain text list for storage.

        Args:
            sources: List of ResearchSource

        Returns:
            Formatted sources text
        """
        if not sources:
            return ""

        lines = ["Sources:"]
        for source in sources:
            line = f"- {source.url}"
            if source.title:
                line = f"- {source.title}: {source.url}"
            if source.visited_at:
                line += f" (visited {source.visited_at.strftime('%Y-%m-%d %H:%M')})"
            lines.append(line)

        return "\n".join(lines)

    def _format_log_summary(self, result: ResearchResult) -> str:
        """Format summary for audit log.

        Args:
            result: ResearchResult to summarize

        Returns:
            Log summary string
        """
        if not result.success:
            return f"Research failed: {result.error}"

        parts = [
            f"Query: {result.query}",
            f"Findings: {len(result.findings)}",
            f"Sources: {len(result.sources)}",
        ]

        if result.screenshot_paths:
            parts.append(f"Screenshots: {len(result.screenshot_paths)}")

        if result.duration_seconds:
            parts.append(f"Duration: {result.duration_seconds:.1f}s")

        return " | ".join(parts)

    async def log_research(
        self,
        result: ResearchResult,
        chat_id: str | None = None,
        message_id: str | None = None,
        task_id: str | None = None,
    ) -> AuditEntry:
        """Log research action to audit system.

        Per PRD 4.10: All research logged with sources.

        Args:
            result: ResearchResult to log
            chat_id: Telegram chat ID if from message
            message_id: Telegram message ID for idempotency
            task_id: Notion task ID if research is for a task

        Returns:
            AuditEntry for the research
        """
        # Generate idempotency key
        now = datetime.now(UTC)
        if chat_id and message_id:
            idempotency_key = f"research:telegram:{chat_id}:{message_id}"
        elif task_id:
            idempotency_key = f"research:task:{task_id}:{now.isoformat()}"
        else:
            idempotency_key = f"research:query:{hash(result.query)}:{now.isoformat()}"

        # Format the log entry
        formatted = self.format_for_telegram(result, detailed=False)

        # Build entities affected
        entities_affected: list[str] = []
        if task_id:
            entities_affected.append(task_id)

        # External resource IDs (source URLs)
        source_urls = ", ".join(s.url for s in result.sources[:5])
        if len(result.sources) > 5:
            source_urls += f" (+{len(result.sources) - 5} more)"

        return await self.audit_logger.log_action(
            action_type=ActionType.RESEARCH,
            idempotency_key=idempotency_key,
            input_text=result.query,
            interpretation=f"Searched {len(result.sources)} sources",
            action_taken=formatted.log_summary,
            confidence=100 if result.success else 0,
            entities_affected=entities_affected,
            external_api="playwright",
            external_resource_id=source_urls if result.sources else None,
            error_code="RESEARCH_FAILED" if not result.success else None,
            error_message=result.error,
        )

    def format_for_notion_note(self, result: ResearchResult) -> str:
        """Format research result for storage as Notion note.

        Args:
            result: ResearchResult to format

        Returns:
            Markdown-formatted note content
        """
        if not result.success:
            return f"## Research Failed\n\n**Query:** {result.query}\n\n**Error:** {result.error}"

        lines: list[str] = []

        # Header
        lines.append(f"## Research: {result.query}")
        lines.append(f"_Completed: {result.completed_at or 'N/A'}_")
        lines.append("")

        # Findings
        if result.findings:
            lines.append("### Findings")
            for finding in result.findings:
                lines.append(f"- {finding}")
            lines.append("")

        # Sources
        if result.sources:
            lines.append("### Sources")
            for source in result.sources:
                if source.title:
                    lines.append(f"- [{source.title}]({source.url})")
                else:
                    lines.append(f"- {source.url}")
                if source.screenshot_path:
                    lines.append(f"  - Screenshot: {source.screenshot_path}")
            lines.append("")

        # Screenshots
        if result.screenshot_paths:
            lines.append("### Screenshots")
            for path in result.screenshot_paths:
                lines.append(f"- {path}")
            lines.append("")

        # Metadata
        lines.append("### Metadata")
        if result.duration_seconds:
            lines.append(f"- Duration: {result.duration_seconds:.1f}s")
        else:
            lines.append("- Duration: N/A")
        lines.append(f"- Started: {result.started_at.isoformat()}")
        completed = result.completed_at.isoformat() if result.completed_at else "N/A"
        lines.append(f"- Completed: {completed}")

        return "\n".join(lines)

    async def store_in_task(
        self,
        result: ResearchResult,
        task_id: str,
    ) -> bool:
        """Store research result in a task's notes field.

        Args:
            result: ResearchResult to store
            task_id: Notion task ID to update

        Returns:
            True if stored successfully
        """
        if not self._notion:
            logger.warning("No Notion client available for storing research")
            return False

        note_content = self.format_for_notion_note(result)

        try:
            # Notion rich_text content limit is 2000 chars
            truncated = note_content[:2000]
            await self._notion._request(
                "PATCH",
                f"/pages/{task_id}",
                {"properties": {"notes": {"rich_text": [{"text": {"content": truncated}}]}}},
            )
            logger.info(f"Stored research result in task {task_id}")
            return True
        except Exception as e:
            logger.exception(f"Failed to store research in task: {e}")
            return False


# Module-level singleton
_formatter: ResearchFormatter | None = None


def get_research_formatter() -> ResearchFormatter:
    """Get the global ResearchFormatter instance."""
    global _formatter
    if _formatter is None:
        _formatter = ResearchFormatter()
    return _formatter


def format_research_for_telegram(
    result: ResearchResult,
    detailed: bool = True,
) -> FormattedResearch:
    """Convenience function to format research for Telegram.

    Args:
        result: ResearchResult to format
        detailed: Whether to include full details

    Returns:
        FormattedResearch with formatted message
    """
    formatter = get_research_formatter()
    return formatter.format_for_telegram(result, detailed)


async def log_research_result(
    result: ResearchResult,
    chat_id: str | None = None,
    message_id: str | None = None,
    task_id: str | None = None,
) -> AuditEntry:
    """Convenience function to log research result.

    Args:
        result: ResearchResult to log
        chat_id: Telegram chat ID
        message_id: Telegram message ID
        task_id: Notion task ID

    Returns:
        AuditEntry for the research
    """
    formatter = get_research_formatter()
    return await formatter.log_research(result, chat_id, message_id, task_id)


def format_research_for_notion(result: ResearchResult) -> str:
    """Convenience function to format research for Notion.

    Args:
        result: ResearchResult to format

    Returns:
        Markdown-formatted note content
    """
    formatter = get_research_formatter()
    return formatter.format_for_notion_note(result)
