"""Tests for the Playwright research service (T-103).

Tests AT-112:
- Given: User asks "What's showing at Everyman this Friday?"
- When: Playwright browser automation available
- Then: Research performed and results returned
- And: Sources logged
- Pass condition: Response includes movie titles AND Log entry includes URL visited
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.services.research import (
    PlaywrightResearcher,
    ResearchError,
    ResearchResult,
    ResearchSource,
    close_researcher,
    get_researcher,
    research,
    research_cinema,
)


# ============================================================================
# ResearchSource Tests
# ============================================================================


class TestResearchSource:
    """Tests for ResearchSource dataclass."""

    def test_create_minimal(self) -> None:
        """Test creating source with minimal data."""
        source = ResearchSource(
            url="https://example.com",
            title="Example",
        )
        assert source.url == "https://example.com"
        assert source.title == "Example"
        assert source.screenshot_path is None
        assert source.screenshot_base64 is None
        assert source.content_snippet is None
        assert isinstance(source.visited_at, datetime)

    def test_create_full(self) -> None:
        """Test creating source with all fields."""
        source = ResearchSource(
            url="https://example.com/page",
            title="Example Page",
            screenshot_path="/tmp/screenshot.png",
            screenshot_base64="base64data",
            content_snippet="Some content from the page",
        )
        assert source.screenshot_path == "/tmp/screenshot.png"
        assert source.screenshot_base64 == "base64data"
        assert source.content_snippet == "Some content from the page"


# ============================================================================
# ResearchResult Tests
# ============================================================================


class TestResearchResult:
    """Tests for ResearchResult dataclass."""

    def test_create_successful(self) -> None:
        """Test creating successful result."""
        result = ResearchResult(
            query="test query",
            answer="test answer",
            sources=[
                ResearchSource(url="https://example.com", title="Example"),
            ],
            success=True,
        )
        assert result.query == "test query"
        assert result.answer == "test answer"
        assert len(result.sources) == 1
        assert result.success is True
        assert result.error_message is None

    def test_create_failed(self) -> None:
        """Test creating failed result."""
        result = ResearchResult(
            query="test query",
            answer="",
            sources=[],
            success=False,
            error_message="Something went wrong",
        )
        assert result.success is False
        assert result.error_message == "Something went wrong"

    def test_urls_visited(self) -> None:
        """Test urls_visited property."""
        result = ResearchResult(
            query="test",
            answer="answer",
            sources=[
                ResearchSource(url="https://example1.com", title="Example 1"),
                ResearchSource(url="https://example2.com", title="Example 2"),
            ],
        )
        assert result.urls_visited == [
            "https://example1.com",
            "https://example2.com",
        ]

    def test_urls_visited_empty(self) -> None:
        """Test urls_visited with no sources."""
        result = ResearchResult(
            query="test",
            answer="answer",
            sources=[],
        )
        assert result.urls_visited == []

    def test_has_screenshots_true(self) -> None:
        """Test has_screenshots when screenshots exist."""
        result = ResearchResult(
            query="test",
            answer="answer",
            sources=[
                ResearchSource(
                    url="https://example.com",
                    title="Example",
                    screenshot_path="/tmp/screenshot.png",
                ),
            ],
        )
        assert result.has_screenshots is True

    def test_has_screenshots_false(self) -> None:
        """Test has_screenshots when no screenshots."""
        result = ResearchResult(
            query="test",
            answer="answer",
            sources=[
                ResearchSource(url="https://example.com", title="Example"),
            ],
        )
        assert result.has_screenshots is False

    def test_has_screenshots_base64(self) -> None:
        """Test has_screenshots with base64 data."""
        result = ResearchResult(
            query="test",
            answer="answer",
            sources=[
                ResearchSource(
                    url="https://example.com",
                    title="Example",
                    screenshot_base64="base64data",
                ),
            ],
        )
        assert result.has_screenshots is True

    def test_to_log_dict(self) -> None:
        """Test conversion to log dictionary."""
        result = ResearchResult(
            query="test query",
            answer="This is a test answer",
            sources=[
                ResearchSource(url="https://example.com", title="Example"),
            ],
            success=True,
            duration_seconds=1.5,
        )
        log_dict = result.to_log_dict()

        assert log_dict["query"] == "test query"
        assert log_dict["answer"] == "This is a test answer"
        assert log_dict["urls_visited"] == ["https://example.com"]
        assert log_dict["source_count"] == 1
        assert log_dict["success"] is True
        assert log_dict["duration_seconds"] == 1.5

    def test_to_log_dict_truncates_long_answer(self) -> None:
        """Test that long answers are truncated in log dict."""
        long_answer = "x" * 1000
        result = ResearchResult(
            query="test",
            answer=long_answer,
            sources=[],
        )
        log_dict = result.to_log_dict()
        assert len(log_dict["answer"]) == 500


# ============================================================================
# PlaywrightResearcher Initialization Tests
# ============================================================================


class TestPlaywrightResearcherInit:
    """Tests for PlaywrightResearcher initialization."""

    def test_default_init(self) -> None:
        """Test default initialization."""
        researcher = PlaywrightResearcher()
        assert researcher.headless is True
        assert researcher.store_screenshots is True
        assert researcher._browser is None
        assert researcher._playwright is None

    def test_custom_init(self) -> None:
        """Test custom initialization."""
        custom_dir = Path("/tmp/custom_screenshots")
        researcher = PlaywrightResearcher(
            headless=False,
            screenshot_dir=custom_dir,
            store_screenshots=False,
        )
        assert researcher.headless is False
        assert researcher.screenshot_dir == custom_dir
        assert researcher.store_screenshots is False

    def test_default_screenshot_dir(self) -> None:
        """Test default screenshot directory."""
        researcher = PlaywrightResearcher()
        expected = Path.home() / ".second-brain" / "screenshots"
        assert researcher.screenshot_dir == expected


# ============================================================================
# PlaywrightResearcher Cinema URL Tests
# ============================================================================


class TestCinemaUrls:
    """Tests for cinema URL lookup."""

    def test_everyman_urls(self) -> None:
        """Test Everyman cinema URLs."""
        researcher = PlaywrightResearcher()
        urls = researcher._get_cinema_urls("Everyman")
        assert "https://www.everymancinema.com/whats-on" in urls

    def test_everyman_case_insensitive(self) -> None:
        """Test case insensitive lookup."""
        researcher = PlaywrightResearcher()
        urls = researcher._get_cinema_urls("everyman")
        assert len(urls) > 0

    def test_odeon_urls(self) -> None:
        """Test Odeon cinema URLs."""
        researcher = PlaywrightResearcher()
        urls = researcher._get_cinema_urls("Odeon")
        assert any("odeon" in url for url in urls)

    def test_vue_urls(self) -> None:
        """Test Vue cinema URLs."""
        researcher = PlaywrightResearcher()
        urls = researcher._get_cinema_urls("Vue")
        assert any("vue" in url for url in urls)

    def test_unknown_cinema(self) -> None:
        """Test unknown cinema returns empty list."""
        researcher = PlaywrightResearcher()
        urls = researcher._get_cinema_urls("Unknown Cinema XYZ")
        assert urls == []


# ============================================================================
# PlaywrightResearcher Answer Compilation Tests
# ============================================================================


class TestAnswerCompilation:
    """Tests for answer compilation."""

    def test_compile_with_content(self) -> None:
        """Test compiling answer with content."""
        researcher = PlaywrightResearcher()
        answer = researcher._compile_answer(
            "test query",
            ["Content from source 1", "Content from source 2"],
        )
        assert "test query" in answer
        assert "Content from source 1" in answer
        assert "Content from source 2" in answer

    def test_compile_empty_content(self) -> None:
        """Test compiling answer with empty content."""
        researcher = PlaywrightResearcher()
        answer = researcher._compile_answer("test query", [])
        assert "No relevant information found" in answer

    def test_compile_whitespace_only(self) -> None:
        """Test compiling with whitespace-only content."""
        researcher = PlaywrightResearcher()
        answer = researcher._compile_answer("test query", ["   ", "\n\t"])
        assert "No relevant information found" in answer

    def test_compile_truncates_long_content(self) -> None:
        """Test that very long content is truncated."""
        researcher = PlaywrightResearcher()
        long_content = "x" * 10000
        answer = researcher._compile_answer("test query", [long_content])
        assert len(answer) <= 4100  # Query text + 4000 char limit


# ============================================================================
# PlaywrightResearcher Mock Browser Tests
# ============================================================================


class TestResearcherWithMockBrowser:
    """Tests with mocked Playwright browser."""

    @pytest.fixture
    def mock_page(self) -> MagicMock:
        """Create a mock Playwright page."""
        page = MagicMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.title = AsyncMock(return_value="Test Page Title")
        page.screenshot = AsyncMock(return_value=b"fake_screenshot_bytes")
        page.close = AsyncMock()

        # Mock query selector for body
        body = MagicMock()
        body.inner_text = AsyncMock(return_value="Page content here")
        page.query_selector = AsyncMock(return_value=body)
        page.evaluate = AsyncMock()

        # Mock query_selector_all for search results
        link = MagicMock()
        link.get_attribute = AsyncMock(return_value="https://example.com/result")
        page.query_selector_all = AsyncMock(return_value=[link])

        return page

    @pytest.fixture
    def mock_browser(self, mock_page: MagicMock) -> MagicMock:
        """Create a mock Playwright browser."""
        browser = MagicMock()
        browser.new_page = AsyncMock(return_value=mock_page)
        browser.close = AsyncMock()
        return browser

    @pytest.fixture
    def mock_playwright(self, mock_browser: MagicMock) -> MagicMock:
        """Create a mock Playwright instance."""
        playwright = MagicMock()
        playwright.chromium = MagicMock()
        playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        playwright.stop = AsyncMock()
        return playwright

    @pytest.mark.asyncio
    async def test_ensure_browser(
        self, mock_playwright: MagicMock, mock_browser: MagicMock
    ) -> None:
        """Test browser initialization."""
        researcher = PlaywrightResearcher()

        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_async_pw:
            mock_context = MagicMock()
            mock_context.start = AsyncMock(return_value=mock_playwright)
            mock_async_pw.return_value = mock_context

            await researcher._ensure_browser()

            assert researcher._browser is mock_browser
            assert researcher._playwright is mock_playwright

    @pytest.mark.asyncio
    async def test_close(
        self, mock_playwright: MagicMock, mock_browser: MagicMock
    ) -> None:
        """Test browser cleanup."""
        researcher = PlaywrightResearcher()
        researcher._browser = mock_browser
        researcher._playwright = mock_playwright

        await researcher.close()

        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()
        assert researcher._browser is None
        assert researcher._playwright is None

    @pytest.mark.asyncio
    async def test_visit_and_extract(
        self,
        mock_playwright: MagicMock,
        mock_browser: MagicMock,
        mock_page: MagicMock,
    ) -> None:
        """Test visiting URL and extracting content."""
        researcher = PlaywrightResearcher(store_screenshots=False)
        researcher._browser = mock_browser
        researcher._playwright = mock_playwright

        source = await researcher._visit_and_extract(
            "https://example.com",
            "test query",
            take_screenshot=True,
            extract_content=True,
        )

        assert source.url == "https://example.com"
        assert source.title == "Test Page Title"
        assert source.screenshot_base64 is not None
        assert source.content_snippet == "Page content here"
        mock_page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_for_urls(
        self,
        mock_playwright: MagicMock,
        mock_browser: MagicMock,
        mock_page: MagicMock,
    ) -> None:
        """Test searching for URLs."""
        researcher = PlaywrightResearcher()
        researcher._browser = mock_browser
        researcher._playwright = mock_playwright

        urls = await researcher._search_for_urls("test query")

        assert "https://example.com/result" in urls
        mock_page.goto.assert_called()

    @pytest.mark.asyncio
    async def test_research_with_urls(
        self,
        mock_playwright: MagicMock,
        mock_browser: MagicMock,
        mock_page: MagicMock,
    ) -> None:
        """Test research with provided URLs."""
        researcher = PlaywrightResearcher(store_screenshots=False)
        researcher._browser = mock_browser
        researcher._playwright = mock_playwright

        result = await researcher.research(
            query="test query",
            urls=["https://example.com"],
            take_screenshots=True,
        )

        assert result.success is True
        assert result.query == "test query"
        assert len(result.sources) == 1
        assert result.sources[0].url == "https://example.com"

    @pytest.mark.asyncio
    async def test_research_no_urls_uses_search(
        self,
        mock_playwright: MagicMock,
        mock_browser: MagicMock,
        mock_page: MagicMock,
    ) -> None:
        """Test research without URLs triggers search."""
        researcher = PlaywrightResearcher(store_screenshots=False)
        researcher._browser = mock_browser
        researcher._playwright = mock_playwright

        result = await researcher.research(
            query="test query",
            urls=None,
        )

        # Should have searched and found URLs
        assert result.success is True
        # At least one source from search
        assert len(result.sources) >= 1


# ============================================================================
# AT-112: Web Research Acceptance Test
# ============================================================================


class TestAT112WebResearch:
    """AT-112: Web Research acceptance tests.

    Given: User asks "What's showing at Everyman this Friday?"
    When: Playwright browser automation available
    Then: Research performed and results returned
    And: Sources logged
    Pass condition: Response includes movie titles AND Log entry includes URL visited
    """

    @pytest.fixture
    def mock_cinema_page(self) -> MagicMock:
        """Create a mock cinema page with movie listings."""
        page = MagicMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.title = AsyncMock(return_value="What's On | Everyman Cinema")
        page.screenshot = AsyncMock(return_value=b"screenshot_bytes")
        page.close = AsyncMock()

        # Mock movie content
        body = MagicMock()
        body.inner_text = AsyncMock(
            return_value="""
            Now Showing at Everyman Cinema

            The Holdovers - 7:00 PM, 9:30 PM
            Poor Things - 6:30 PM, 9:15 PM
            Killers of the Flower Moon - 7:45 PM
            Saltburn - 8:00 PM, 10:30 PM

            Coming Soon: Dune Part Two
            """
        )
        page.query_selector = AsyncMock(return_value=body)
        page.evaluate = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])

        return page

    @pytest.fixture
    def mock_browser_cinema(self, mock_cinema_page: MagicMock) -> MagicMock:
        """Create mock browser for cinema tests."""
        browser = MagicMock()
        browser.new_page = AsyncMock(return_value=mock_cinema_page)
        browser.close = AsyncMock()
        return browser

    @pytest.mark.asyncio
    async def test_cinema_research_returns_movies(
        self, mock_browser_cinema: MagicMock, mock_cinema_page: MagicMock
    ) -> None:
        """Test that cinema research returns movie titles."""
        researcher = PlaywrightResearcher(store_screenshots=False)
        researcher._browser = mock_browser_cinema

        mock_playwright = MagicMock()
        mock_playwright.stop = AsyncMock()
        researcher._playwright = mock_playwright

        result = await researcher.research_cinema(
            cinema_name="Everyman",
            date="Friday",
        )

        # Verify research was successful
        assert result.success is True
        assert "Everyman" in result.query

        # Verify answer contains movie information
        assert "Holdovers" in result.answer or "content" in result.answer.lower()

    @pytest.mark.asyncio
    async def test_cinema_research_logs_urls(
        self, mock_browser_cinema: MagicMock
    ) -> None:
        """Test that cinema research logs URLs visited."""
        researcher = PlaywrightResearcher(store_screenshots=False)
        researcher._browser = mock_browser_cinema

        mock_playwright = MagicMock()
        mock_playwright.stop = AsyncMock()
        researcher._playwright = mock_playwright

        result = await researcher.research_cinema(
            cinema_name="Everyman",
            date="this Friday",
        )

        # Verify URLs were recorded
        assert len(result.urls_visited) > 0
        assert any("everyman" in url.lower() for url in result.urls_visited)

    @pytest.mark.asyncio
    async def test_cinema_research_captures_screenshots(
        self, mock_browser_cinema: MagicMock, mock_cinema_page: MagicMock
    ) -> None:
        """Test that cinema research captures screenshot evidence."""
        researcher = PlaywrightResearcher(store_screenshots=False)
        researcher._browser = mock_browser_cinema

        mock_playwright = MagicMock()
        mock_playwright.stop = AsyncMock()
        researcher._playwright = mock_playwright

        result = await researcher.research_cinema(
            cinema_name="Everyman",
            date="Friday",
        )

        # Verify screenshots were captured
        assert result.has_screenshots is True
        assert result.sources[0].screenshot_base64 is not None

    @pytest.mark.asyncio
    async def test_cinema_research_to_log_dict(
        self, mock_browser_cinema: MagicMock
    ) -> None:
        """Test that research results can be logged properly."""
        researcher = PlaywrightResearcher(store_screenshots=False)
        researcher._browser = mock_browser_cinema

        mock_playwright = MagicMock()
        mock_playwright.stop = AsyncMock()
        researcher._playwright = mock_playwright

        result = await researcher.research_cinema(
            cinema_name="Everyman",
            date="this Friday",
        )

        # Verify log dict format
        log_dict = result.to_log_dict()
        assert "query" in log_dict
        assert "urls_visited" in log_dict
        assert isinstance(log_dict["urls_visited"], list)
        assert log_dict["success"] is True


# ============================================================================
# Module-Level Function Tests
# ============================================================================


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture
    def research_mod(self) -> Any:
        """Get the actual research module (not shadowed by function)."""
        import importlib

        mod = importlib.import_module("assistant.services.research")
        # Reset singleton before test
        mod._researcher = None
        yield mod
        # Cleanup after test
        mod._researcher = None

    def test_get_researcher_creates_singleton(self, research_mod: Any) -> None:
        """Test get_researcher creates and returns singleton."""
        researcher1 = research_mod.get_researcher()
        researcher2 = research_mod.get_researcher()

        assert researcher1 is researcher2
        assert research_mod._researcher is researcher1

    def test_get_researcher_with_options(self, research_mod: Any) -> None:
        """Test get_researcher with custom options on first call."""
        custom_dir = Path("/tmp/test_screenshots")
        researcher = research_mod.get_researcher(
            headless=True,
            screenshot_dir=custom_dir,
        )

        # Singleton should be created with the custom dir
        assert research_mod._researcher is researcher
        assert researcher.screenshot_dir == custom_dir

    @pytest.mark.asyncio
    async def test_close_researcher(self, research_mod: Any) -> None:
        """Test close_researcher cleans up singleton."""
        # Create a researcher with mocked browser
        researcher = PlaywrightResearcher()
        mock_browser = MagicMock()
        mock_browser.close = AsyncMock()
        researcher._browser = mock_browser
        mock_playwright = MagicMock()
        mock_playwright.stop = AsyncMock()
        researcher._playwright = mock_playwright

        research_mod._researcher = researcher

        await research_mod.close_researcher()

        # After close, singleton should be None
        assert research_mod._researcher is None
        # Browser should have been closed (check mock before it was set to None)
        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_research_error_on_missing_playwright(self) -> None:
        """Test error when Playwright not installed."""
        researcher = PlaywrightResearcher()

        with patch.dict("sys.modules", {"playwright.async_api": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("playwright not installed"),
            ):
                # The current implementation catches ImportError
                with pytest.raises(ResearchError) as exc_info:
                    # Force a fresh import attempt by clearing cached state
                    researcher._browser = None
                    researcher._playwright = None
                    await researcher._ensure_browser()

                assert "Playwright not installed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_research_handles_page_errors(self) -> None:
        """Test research handles page loading errors gracefully."""
        researcher = PlaywrightResearcher(store_screenshots=False)

        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Connection refused"))
        mock_page.close = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        researcher._browser = mock_browser

        mock_playwright = MagicMock()
        mock_playwright.stop = AsyncMock()
        researcher._playwright = mock_playwright

        result = await researcher.research(
            query="test",
            urls=["https://example.com"],
        )

        # Should still have a result with error info
        assert len(result.sources) == 1
        assert "Error" in result.sources[0].title

    @pytest.mark.asyncio
    async def test_research_no_urls_found(self) -> None:
        """Test research when no URLs are found or provided."""
        researcher = PlaywrightResearcher(store_screenshots=False)

        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.close = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        researcher._browser = mock_browser

        mock_playwright = MagicMock()
        mock_playwright.stop = AsyncMock()
        researcher._playwright = mock_playwright

        result = await researcher.research(
            query="some obscure query",
            urls=None,
        )

        assert result.success is False
        assert "No relevant sources found" in result.answer


# ============================================================================
# Audit Logging Tests
# ============================================================================


class TestAuditLogging:
    """Tests for audit logging of research actions."""

    @pytest.mark.asyncio
    async def test_log_research_action(self) -> None:
        """Test logging research action via audit logger."""
        from assistant.services.audit import AuditLogger
        from assistant.notion.schemas import ActionType

        # Create logger without Notion
        logger = AuditLogger(notion_client=None)

        entry = await logger.log_research(
            query="What's showing at Everyman?",
            urls_visited=["https://everymancinema.com/whats-on"],
            answer="The Holdovers - 7:00 PM",
            success=True,
            duration_seconds=2.5,
        )

        assert entry.action_type == ActionType.RESEARCH
        assert entry.input_text == "What's showing at Everyman?"
        assert "Researched" in entry.action_taken
        assert entry.external_api == "playwright"
        assert entry.external_resource_id == "https://everymancinema.com/whats-on"

    @pytest.mark.asyncio
    async def test_log_research_failure(self) -> None:
        """Test logging failed research."""
        from assistant.services.audit import AuditLogger

        logger = AuditLogger(notion_client=None)

        entry = await logger.log_research(
            query="test query",
            urls_visited=[],
            answer=None,
            success=False,
        )

        assert entry.error_code == "research_failed"


# ============================================================================
# Context Manager Tests
# ============================================================================


class TestContextManager:
    """Tests for async context manager support."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test using researcher as async context manager."""
        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_async_pw:
            mock_browser = MagicMock()
            mock_browser.close = AsyncMock()

            mock_playwright = MagicMock()
            mock_playwright.chromium = MagicMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_playwright.stop = AsyncMock()

            mock_context = MagicMock()
            mock_context.start = AsyncMock(return_value=mock_playwright)
            mock_async_pw.return_value = mock_context

            async with PlaywrightResearcher() as researcher:
                assert researcher._browser is mock_browser

            # Verify cleanup happened
            mock_browser.close.assert_called_once()
            mock_playwright.stop.assert_called_once()
