"""Tests for research result formatter (T-104)."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.notion.schemas import ActionType
from assistant.services.audit import AuditEntry
from assistant.services.research import ResearchResult, ResearchSource
from assistant.services.research_formatter import (
    MAX_FINDING_LENGTH,
    MAX_FINDINGS_IN_BRIEF,
    MAX_FINDINGS_IN_DETAILED,
    MAX_SOURCES_DISPLAYED,
    MAX_TELEGRAM_MESSAGE_LENGTH,
    FormattedResearch,
    ResearchFormatter,
    format_research_for_notion,
    format_research_for_telegram,
    get_research_formatter,
    log_research_result,
)


class TestFormattedResearch:
    """Tests for FormattedResearch dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        formatted = FormattedResearch()
        assert formatted.success is True
        assert formatted.telegram_message == ""
        assert formatted.telegram_brief == ""
        assert formatted.log_summary == ""
        assert formatted.sources_text == ""
        assert formatted.findings_count == 0
        assert formatted.sources_count == 0
        assert formatted.screenshot_count == 0
        assert formatted.error is None

    def test_with_error(self):
        """Test FormattedResearch with error."""
        formatted = FormattedResearch(
            success=False,
            error="Connection failed",
            telegram_message="❌ Research failed: Connection failed",
        )
        assert formatted.success is False
        assert formatted.error == "Connection failed"
        assert "failed" in formatted.telegram_message.lower()

    def test_to_dict(self):
        """Test conversion to dictionary."""
        formatted = FormattedResearch(
            success=True,
            telegram_message="Found items",
            findings_count=5,
            sources_count=2,
        )
        result = formatted.to_dict()
        assert result["success"] is True
        assert result["telegram_message"] == "Found items"
        assert result["findings_count"] == 5
        assert result["sources_count"] == 2


class TestResearchFormatterInit:
    """Tests for ResearchFormatter initialization."""

    def test_default_init(self):
        """Test default initialization."""
        formatter = ResearchFormatter()
        assert formatter._audit_logger is None
        assert formatter._notion is None

    def test_with_audit_logger(self):
        """Test initialization with audit logger."""
        mock_logger = MagicMock()
        formatter = ResearchFormatter(audit_logger=mock_logger)
        assert formatter._audit_logger is mock_logger

    def test_with_notion_client(self):
        """Test initialization with Notion client."""
        mock_notion = MagicMock()
        formatter = ResearchFormatter(notion_client=mock_notion)
        assert formatter._notion is mock_notion

    def test_audit_logger_property_creates_instance(self):
        """Test that audit_logger property creates instance if none."""
        formatter = ResearchFormatter()
        with patch("assistant.services.research_formatter.get_audit_logger") as mock_get:
            mock_get.return_value = MagicMock()
            logger = formatter.audit_logger
            mock_get.assert_called_once()
            assert logger is not None


class TestResearchFormatterFormatTelegram:
    """Tests for format_for_telegram method."""

    @pytest.fixture
    def formatter(self):
        """Create a formatter instance."""
        return ResearchFormatter()

    @pytest.fixture
    def successful_result(self):
        """Create a successful research result."""
        return ResearchResult(
            success=True,
            query="What movies are showing?",
            findings=["Movie 1", "Movie 2", "Movie 3"],
            sources=[
                ResearchSource(url="https://example.com", title="Example Site"),
                ResearchSource(url="https://other.com", title="Other Site"),
            ],
            screenshot_paths=[Path("/tmp/screenshot1.png")],
            completed_at=datetime.now(),
        )

    @pytest.fixture
    def failed_result(self):
        """Create a failed research result."""
        return ResearchResult(
            success=False,
            query="What movies are showing?",
            error="Network timeout",
        )

    def test_format_successful_result(self, formatter, successful_result):
        """Test formatting a successful result."""
        formatted = formatter.format_for_telegram(successful_result)
        assert formatted.success is True
        assert "🔍" in formatted.telegram_message
        assert "What movies are showing?" in formatted.telegram_message
        assert "Movie 1" in formatted.telegram_message
        assert "Sources" in formatted.telegram_message
        assert formatted.findings_count == 3
        assert formatted.sources_count == 2
        assert formatted.screenshot_count == 1

    def test_format_failed_result(self, formatter, failed_result):
        """Test formatting a failed result."""
        formatted = formatter.format_for_telegram(failed_result)
        assert formatted.success is False
        assert "❌" in formatted.telegram_message
        assert "Network timeout" in formatted.telegram_message
        assert formatted.error == "Network timeout"

    def test_format_with_no_findings(self, formatter):
        """Test formatting result with no findings."""
        result = ResearchResult(
            success=True,
            query="Test query",
            findings=[],
            sources=[ResearchSource(url="https://example.com")],
            completed_at=datetime.now(),
        )
        formatted = formatter.format_for_telegram(result)
        assert formatted.success is True
        assert "no specific findings" in formatted.telegram_message.lower()

    def test_format_brief_mode(self, formatter, successful_result):
        """Test formatting in brief mode."""
        formatted = formatter.format_for_telegram(successful_result, detailed=False)
        assert formatted.success is True
        # Brief mode should have fewer findings
        max_items = MAX_FINDINGS_IN_BRIEF + MAX_SOURCES_DISPLAYED
        assert formatted.telegram_message.count("•") <= max_items

    def test_truncate_long_findings(self, formatter):
        """Test that long findings are truncated."""
        long_finding = "A" * 300  # Longer than MAX_FINDING_LENGTH
        result = ResearchResult(
            success=True,
            query="Test query",
            findings=[long_finding],
            sources=[],
            completed_at=datetime.now(),
        )
        formatted = formatter.format_for_telegram(result)
        # Should be truncated with "..."
        assert "..." in formatted.telegram_message
        assert len(formatted.telegram_message) < len(long_finding) + 200

    def test_truncate_long_message(self, formatter):
        """Test that very long messages are truncated for Telegram."""
        # Create result with many findings
        result = ResearchResult(
            success=True,
            query="Test query",
            findings=["Finding " * 50] * 100,  # Many long findings
            sources=[ResearchSource(url=f"https://example{i}.com") for i in range(50)],
            completed_at=datetime.now(),
        )
        formatted = formatter.format_for_telegram(result)
        assert len(formatted.telegram_message) <= MAX_TELEGRAM_MESSAGE_LENGTH

    def test_format_includes_duration(self, formatter, successful_result):
        """Test that duration is included if available."""
        # Set duration by having both started_at and completed_at
        successful_result.started_at = datetime.now()
        formatted = formatter.format_for_telegram(successful_result)
        assert "⏱️" in formatted.telegram_message

    def test_format_includes_screenshot_count(self, formatter, successful_result):
        """Test that screenshot count is included."""
        formatted = formatter.format_for_telegram(successful_result)
        assert "📷" in formatted.telegram_message
        assert "1 screenshot" in formatted.telegram_message


class TestResearchFormatterFormatBrief:
    """Tests for _format_brief method."""

    @pytest.fixture
    def formatter(self):
        """Create a formatter instance."""
        return ResearchFormatter()

    def test_brief_with_findings(self, formatter):
        """Test brief format with findings."""
        result = ResearchResult(
            success=True,
            query="Test",
            findings=["First finding here", "Second finding"],
            sources=[],
            completed_at=datetime.now(),
        )
        formatted = formatter.format_for_telegram(result)
        assert "🔍" in formatted.telegram_brief
        assert "First finding" in formatted.telegram_brief

    def test_brief_truncates_long_finding(self, formatter):
        """Test that brief truncates long first finding."""
        result = ResearchResult(
            success=True,
            query="Test",
            findings=["A very long finding that goes on and on for quite a while indeed"],
            sources=[],
            completed_at=datetime.now(),
        )
        formatted = formatter.format_for_telegram(result)
        assert len(formatted.telegram_brief) < 100

    def test_brief_with_no_findings(self, formatter):
        """Test brief format with no findings."""
        result = ResearchResult(
            success=True,
            query="Test",
            findings=[],
            sources=[ResearchSource(url="https://example.com")],
            completed_at=datetime.now(),
        )
        formatted = formatter.format_for_telegram(result)
        assert "Searched" in formatted.telegram_brief
        assert "1 source" in formatted.telegram_brief


class TestResearchFormatterFormatSource:
    """Tests for _format_source method."""

    @pytest.fixture
    def formatter(self):
        """Create a formatter instance."""
        return ResearchFormatter()

    def test_format_source_with_title(self, formatter):
        """Test formatting source with title."""
        source = ResearchSource(url="https://example.com", title="Example Site")
        result = formatter._format_source(source)
        assert "[Example Site]" in result
        assert "(https://example.com)" in result

    def test_format_source_without_title(self, formatter):
        """Test formatting source without title uses domain."""
        source = ResearchSource(url="https://example.com/path/to/page")
        result = formatter._format_source(source)
        assert "example.com" in result

    def test_format_source_truncates_long_title(self, formatter):
        """Test that long titles are truncated."""
        source = ResearchSource(
            url="https://example.com",
            title="A" * 100,  # Very long title
        )
        result = formatter._format_source(source)
        assert "..." in result
        assert len(result) < 100


class TestResearchFormatterLogResearch:
    """Tests for log_research method."""

    @pytest.fixture
    def formatter(self):
        """Create a formatter with mock audit logger."""
        mock_logger = MagicMock()
        mock_logger.log_action = AsyncMock(return_value=AuditEntry())
        return ResearchFormatter(audit_logger=mock_logger)

    @pytest.fixture
    def result(self):
        """Create a research result."""
        return ResearchResult(
            success=True,
            query="Test query",
            findings=["Finding 1"],
            sources=[ResearchSource(url="https://example.com")],
            completed_at=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_log_with_telegram_context(self, formatter, result):
        """Test logging with Telegram context."""
        await formatter.log_research(result, chat_id="123", message_id="456")
        formatter._audit_logger.log_action.assert_called_once()
        call_kwargs = formatter._audit_logger.log_action.call_args[1]
        assert call_kwargs["action_type"] == ActionType.RESEARCH
        assert "telegram:123:456" in call_kwargs["idempotency_key"]

    @pytest.mark.asyncio
    async def test_log_with_task_context(self, formatter, result):
        """Test logging with task context."""
        await formatter.log_research(result, task_id="task-123")
        call_kwargs = formatter._audit_logger.log_action.call_args[1]
        assert "task:task-123" in call_kwargs["idempotency_key"]
        assert "task-123" in call_kwargs["entities_affected"]

    @pytest.mark.asyncio
    async def test_log_includes_sources(self, formatter, result):
        """Test that log includes source URLs."""
        await formatter.log_research(result)
        call_kwargs = formatter._audit_logger.log_action.call_args[1]
        assert call_kwargs["external_api"] == "playwright"
        assert "example.com" in call_kwargs["external_resource_id"]

    @pytest.mark.asyncio
    async def test_log_failed_research(self, formatter):
        """Test logging failed research."""
        result = ResearchResult(
            success=False,
            query="Test query",
            error="Connection failed",
        )
        await formatter.log_research(result)
        call_kwargs = formatter._audit_logger.log_action.call_args[1]
        assert call_kwargs["error_code"] == "RESEARCH_FAILED"
        assert call_kwargs["confidence"] == 0


class TestResearchFormatterNotionNote:
    """Tests for format_for_notion_note method."""

    @pytest.fixture
    def formatter(self):
        """Create a formatter instance."""
        return ResearchFormatter()

    def test_format_successful_result(self, formatter):
        """Test formatting successful result as Notion note."""
        result = ResearchResult(
            success=True,
            query="Test query",
            findings=["Finding 1", "Finding 2"],
            sources=[ResearchSource(url="https://example.com", title="Example")],
            screenshot_paths=[Path("/tmp/shot.png")],
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        note = formatter.format_for_notion_note(result)
        assert "## Research: Test query" in note
        assert "### Findings" in note
        assert "Finding 1" in note
        assert "### Sources" in note
        assert "[Example]" in note
        assert "### Screenshots" in note
        assert "### Metadata" in note

    def test_format_failed_result(self, formatter):
        """Test formatting failed result as Notion note."""
        result = ResearchResult(
            success=False,
            query="Test query",
            error="Network error",
        )
        note = formatter.format_for_notion_note(result)
        assert "## Research Failed" in note
        assert "Network error" in note


class TestResearchFormatterStoreInTask:
    """Tests for store_in_task method."""

    @pytest.fixture
    def formatter_with_notion(self):
        """Create a formatter with mock Notion client."""
        mock_notion = MagicMock()
        mock_notion._request = AsyncMock()
        return ResearchFormatter(notion_client=mock_notion)

    @pytest.fixture
    def result(self):
        """Create a research result."""
        return ResearchResult(
            success=True,
            query="Test",
            findings=["Finding"],
            sources=[],
            completed_at=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_store_succeeds(self, formatter_with_notion, result):
        """Test successful store to task."""
        stored = await formatter_with_notion.store_in_task(result, "task-123")
        assert stored is True
        formatter_with_notion._notion._request.assert_called_once()
        args = formatter_with_notion._notion._request.call_args
        assert args[0][0] == "PATCH"
        assert "/pages/task-123" in args[0][1]

    @pytest.mark.asyncio
    async def test_store_without_notion_client(self, result):
        """Test store fails without Notion client."""
        formatter = ResearchFormatter()
        stored = await formatter.store_in_task(result, "task-123")
        assert stored is False

    @pytest.mark.asyncio
    async def test_store_handles_error(self, formatter_with_notion, result):
        """Test store handles Notion errors."""
        formatter_with_notion._notion._request.side_effect = Exception("API error")
        stored = await formatter_with_notion.store_in_task(result, "task-123")
        assert stored is False


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_research_formatter_singleton(self):
        """Test singleton pattern."""
        formatter1 = get_research_formatter()
        formatter2 = get_research_formatter()
        assert formatter1 is formatter2

    def test_format_research_for_telegram(self):
        """Test convenience function for Telegram formatting."""
        result = ResearchResult(
            success=True,
            query="Test",
            findings=["Item"],
            sources=[],
            completed_at=datetime.now(),
        )
        formatted = format_research_for_telegram(result)
        assert formatted.success is True
        assert "Test" in formatted.telegram_message

    @pytest.mark.asyncio
    async def test_log_research_result(self):
        """Test convenience function for logging."""
        result = ResearchResult(
            success=True,
            query="Test",
            findings=[],
            sources=[],
            completed_at=datetime.now(),
        )
        with patch("assistant.services.research_formatter.get_research_formatter") as mock_get:
            mock_formatter = MagicMock()
            mock_formatter.log_research = AsyncMock(return_value=AuditEntry())
            mock_get.return_value = mock_formatter

            await log_research_result(result, chat_id="123")
            mock_formatter.log_research.assert_called_once_with(result, "123", None, None)

    def test_format_research_for_notion(self):
        """Test convenience function for Notion formatting."""
        result = ResearchResult(
            success=True,
            query="Test",
            findings=["Item"],
            sources=[],
            completed_at=datetime.now(),
        )
        note = format_research_for_notion(result)
        assert "## Research: Test" in note


class TestConstants:
    """Tests for module constants."""

    def test_max_telegram_length(self):
        """Test Telegram message length constant."""
        assert MAX_TELEGRAM_MESSAGE_LENGTH == 4096

    def test_max_finding_length(self):
        """Test finding length constant."""
        assert MAX_FINDING_LENGTH == 200

    def test_max_findings_brief(self):
        """Test brief findings limit."""
        assert MAX_FINDINGS_IN_BRIEF == 5

    def test_max_findings_detailed(self):
        """Test detailed findings limit."""
        assert MAX_FINDINGS_IN_DETAILED == 15

    def test_max_sources_displayed(self):
        """Test sources display limit."""
        assert MAX_SOURCES_DISPLAYED == 5


class TestAT112Integration:
    """Integration tests for AT-112 cinema research formatting."""

    @pytest.fixture
    def cinema_result(self):
        """Create a cinema research result."""
        return ResearchResult(
            success=True,
            query="What's showing at Everyman this Friday?",
            findings=[
                "The Batman (7:30 PM, 10:15 PM)",
                "Dune Part Two (6:00 PM, 9:00 PM)",
                "Oppenheimer (7:00 PM)",
            ],
            sources=[
                ResearchSource(
                    url="https://www.everymancinema.com/whats-on",
                    title="Everyman Cinema - What's On",
                    screenshot_path=Path("/tmp/everyman_Friday_20260112.png"),
                )
            ],
            screenshot_paths=[Path("/tmp/everyman_Friday_20260112.png")],
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )

    def test_cinema_telegram_format(self, cinema_result):
        """Test cinema results format correctly for Telegram."""
        formatter = ResearchFormatter()
        formatted = formatter.format_for_telegram(cinema_result)

        # Should include query
        assert "Everyman" in formatted.telegram_message
        assert "Friday" in formatted.telegram_message

        # Should include findings (movies)
        assert "The Batman" in formatted.telegram_message
        assert "Dune Part Two" in formatted.telegram_message

        # Should include source
        assert "Everyman Cinema" in formatted.telegram_message

        # Should mention screenshot
        assert "📷" in formatted.telegram_message

    def test_cinema_log_includes_source_url(self, cinema_result):
        """Test cinema research logging includes source URL per AT-112."""
        formatter = ResearchFormatter()
        formatted = formatter.format_for_telegram(cinema_result)

        # Log summary should include query info
        assert "Query:" in formatted.log_summary
        assert "Findings: 3" in formatted.log_summary
        assert "Sources: 1" in formatted.log_summary

    def test_cinema_notion_format(self, cinema_result):
        """Test cinema results format correctly for Notion storage."""
        formatter = ResearchFormatter()
        note = formatter.format_for_notion_note(cinema_result)

        # Should have structured sections
        assert "## Research:" in note
        assert "### Findings" in note
        assert "### Sources" in note
        assert "### Screenshots" in note

        # Should include all findings
        assert "The Batman" in note
        assert "Dune Part Two" in note
        assert "Oppenheimer" in note


class TestPRDSection410Compliance:
    """Tests for PRD Section 4.10 compliance."""

    def test_results_logged_with_sources(self):
        """Verify results are logged with sources per PRD 4.10."""
        result = ResearchResult(
            success=True,
            query="Test",
            findings=["Finding"],
            sources=[ResearchSource(url="https://example.com")],
            completed_at=datetime.now(),
        )
        formatter = ResearchFormatter()
        formatted = formatter.format_for_telegram(result)
        assert formatted.sources_count == 1
        assert "example.com" in formatted.sources_text

    def test_screenshots_referenced(self):
        """Verify screenshots are tracked per PRD 4.10."""
        result = ResearchResult(
            success=True,
            query="Test",
            findings=[],
            sources=[],
            screenshot_paths=[Path("/tmp/test.png")],
            completed_at=datetime.now(),
        )
        formatter = ResearchFormatter()
        formatted = formatter.format_for_telegram(result)
        assert formatted.screenshot_count == 1
        assert "📷" in formatted.telegram_message

    def test_results_summarized(self):
        """Verify results are summarized per PRD 4.10."""
        result = ResearchResult(
            success=True,
            query="Test",
            findings=["A", "B", "C"],
            sources=[ResearchSource(url="https://example.com")],
            completed_at=datetime.now(),
        )
        formatter = ResearchFormatter()
        formatted = formatter.format_for_telegram(result)
        assert "Found 3 items" in formatted.telegram_message
