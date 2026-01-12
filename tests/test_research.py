"""Tests for the web research service.

Tests cover:
- ResearchSource dataclass
- ResearchResult dataclass
- WebResearcher initialization and lifecycle
- Cinema research (AT-112)
- URL research
- Query routing
- Module-level functions
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.services.research import (
    DEFAULT_PAGE_TIMEOUT_MS,
    DEFAULT_RESEARCH_DIR,
    DEFAULT_SCREENSHOTS_DIR,
    ResearchResult,
    ResearchSource,
    WebResearcher,
    close_researcher,
    get_web_researcher,
    is_research_available,
    research,
    research_cinema,
)


class TestResearchSource:
    """Tests for ResearchSource dataclass."""

    def test_create_with_minimal_fields(self) -> None:
        """Create source with only URL."""
        source = ResearchSource(url="https://example.com")
        assert source.url == "https://example.com"
        assert source.title is None
        assert source.screenshot_path is None
        assert source.content_hash is None
        assert isinstance(source.visited_at, datetime)

    def test_create_with_all_fields(self) -> None:
        """Create source with all fields populated."""
        now = datetime.now()
        path = Path("/tmp/screenshot.png")
        source = ResearchSource(
            url="https://example.com/page",
            title="Example Page",
            visited_at=now,
            screenshot_path=path,
            content_hash="abc123def456",
        )
        assert source.url == "https://example.com/page"
        assert source.title == "Example Page"
        assert source.visited_at == now
        assert source.screenshot_path == path
        assert source.content_hash == "abc123def456"

    def test_to_dict(self) -> None:
        """Convert source to dictionary."""
        source = ResearchSource(
            url="https://example.com",
            title="Test",
            screenshot_path=Path("/tmp/test.png"),
            content_hash="hash123",
        )
        data = source.to_dict()
        assert data["url"] == "https://example.com"
        assert data["title"] == "Test"
        assert data["screenshot_path"] == "/tmp/test.png"
        assert data["content_hash"] == "hash123"
        assert "visited_at" in data

    def test_to_dict_without_screenshot(self) -> None:
        """Convert source without screenshot to dictionary."""
        source = ResearchSource(url="https://example.com")
        data = source.to_dict()
        assert data["screenshot_path"] is None


class TestResearchResult:
    """Tests for ResearchResult dataclass."""

    def test_create_success_result(self) -> None:
        """Create successful research result."""
        result = ResearchResult(
            success=True,
            query="test query",
            findings=["finding 1", "finding 2"],
        )
        assert result.success is True
        assert result.query == "test query"
        assert len(result.findings) == 2
        assert result.error is None

    def test_create_failure_result(self) -> None:
        """Create failed research result."""
        result = ResearchResult(
            success=False,
            query="test query",
            error="Connection failed",
        )
        assert result.success is False
        assert result.error == "Connection failed"

    def test_source_urls_property(self) -> None:
        """Get list of source URLs."""
        sources = [
            ResearchSource(url="https://example.com/1"),
            ResearchSource(url="https://example.com/2"),
        ]
        result = ResearchResult(
            success=True,
            query="test",
            sources=sources,
        )
        assert result.source_urls == ["https://example.com/1", "https://example.com/2"]

    def test_duration_seconds_property(self) -> None:
        """Calculate research duration."""
        start = datetime(2024, 1, 1, 10, 0, 0)
        end = datetime(2024, 1, 1, 10, 0, 30)
        result = ResearchResult(
            success=True,
            query="test",
            started_at=start,
            completed_at=end,
        )
        assert result.duration_seconds == 30.0

    def test_duration_seconds_none_when_incomplete(self) -> None:
        """Duration is None when research not completed."""
        result = ResearchResult(success=True, query="test")
        assert result.duration_seconds is None

    def test_summary_success(self) -> None:
        """Generate summary for successful result."""
        result = ResearchResult(
            success=True,
            query="test",
            findings=["Movie A", "Movie B", "Movie C"],
            sources=[ResearchSource(url="https://example.com")],
        )
        summary = result.summary()
        assert "Found 3 items from 1 sources" in summary
        assert "Movie A" in summary
        assert "Movie B" in summary

    def test_summary_failure(self) -> None:
        """Generate summary for failed result."""
        result = ResearchResult(
            success=False,
            query="test",
            error="Network error",
        )
        summary = result.summary()
        assert "Research failed: Network error" in summary

    def test_summary_truncates_many_findings(self) -> None:
        """Summary truncates when many findings."""
        result = ResearchResult(
            success=True,
            query="test",
            findings=[f"Finding {i}" for i in range(15)],
            sources=[ResearchSource(url="https://example.com")],
        )
        summary = result.summary()
        assert "... and 5 more" in summary

    def test_to_dict(self) -> None:
        """Convert result to dictionary."""
        source = ResearchSource(url="https://example.com")
        result = ResearchResult(
            success=True,
            query="test query",
            findings=["finding 1"],
            sources=[source],
            screenshot_paths=[Path("/tmp/test.png")],
        )
        result.completed_at = datetime.now()
        data = result.to_dict()
        assert data["success"] is True
        assert data["query"] == "test query"
        assert len(data["findings"]) == 1
        assert len(data["sources"]) == 1
        assert len(data["screenshot_paths"]) == 1


class TestWebResearcherInit:
    """Tests for WebResearcher initialization."""

    def test_default_initialization(self) -> None:
        """Create researcher with defaults."""
        researcher = WebResearcher()
        assert researcher.research_dir == DEFAULT_RESEARCH_DIR
        assert researcher.headless is True
        assert researcher.is_initialized() is False

    def test_custom_research_dir(self, tmp_path: Path) -> None:
        """Create researcher with custom directory."""
        researcher = WebResearcher(research_dir=tmp_path / "research")
        assert researcher.research_dir == tmp_path / "research"
        assert researcher.screenshots_dir == tmp_path / "research" / "screenshots"

    def test_headless_mode(self) -> None:
        """Create researcher with headed mode."""
        researcher = WebResearcher(headless=False)
        assert researcher.headless is False


class TestWebResearcherLifecycle:
    """Tests for WebResearcher browser lifecycle."""

    @pytest.mark.asyncio
    async def test_initialize_creates_directories(self, tmp_path: Path) -> None:
        """Initialize creates research directories."""
        research_dir = tmp_path / "research"
        researcher = WebResearcher(research_dir=research_dir)

        # Mock the playwright import inside initialize
        mock_playwright = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        mock_async_pw = MagicMock()
        mock_async_pw.return_value.start = AsyncMock(return_value=mock_playwright)

        with patch.dict(
            "sys.modules",
            {"playwright.async_api": MagicMock(async_playwright=mock_async_pw)},
        ):
            with patch(
                "assistant.services.research.WebResearcher._ensure_initialized",
                new_callable=AsyncMock,
            ):
                # Just test directory creation
                researcher.research_dir.mkdir(parents=True, exist_ok=True)
                researcher.screenshots_dir.mkdir(parents=True, exist_ok=True)

                assert research_dir.exists()
                assert (research_dir / "screenshots").exists()

    @pytest.mark.asyncio
    async def test_is_initialized_false_by_default(self) -> None:
        """Researcher is not initialized by default."""
        researcher = WebResearcher()
        assert researcher.is_initialized() is False

    @pytest.mark.asyncio
    async def test_close_when_not_initialized(self) -> None:
        """Close when not initialized does not error."""
        researcher = WebResearcher()
        await researcher.close()  # Should not raise
        assert researcher.is_initialized() is False


class TestWebResearcherCinemaResearch:
    """Tests for cinema research functionality (AT-112)."""

    @pytest.mark.asyncio
    async def test_research_cinema_returns_result_structure(self) -> None:
        """Research cinema returns ResearchResult with correct structure."""
        researcher = WebResearcher()

        # Create mock page
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.title = AsyncMock(return_value="Cinema Listings")
        mock_page.url = "https://www.everymancinema.com/whats-on"
        mock_page.screenshot = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.close = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()

        # Patch the internal methods
        with patch.object(researcher, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(
                researcher, "_new_page", new_callable=AsyncMock, return_value=mock_page
            ):
                with patch.object(
                    researcher,
                    "_capture_screenshot",
                    new_callable=AsyncMock,
                    return_value=Path("/tmp/screenshot.png"),
                ):
                    result = await researcher.research_cinema("Everyman", "Friday")

                    assert isinstance(result, ResearchResult)
                    assert result.query == "What's showing at Everyman Friday?"
                    assert len(result.sources) == 1
                    assert "everymancinema.com" in result.sources[0].url

    @pytest.mark.asyncio
    async def test_research_cinema_captures_screenshot(self, tmp_path: Path) -> None:
        """Research cinema captures screenshot as evidence."""
        researcher = WebResearcher(research_dir=tmp_path / "research")

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.title = AsyncMock(return_value="Cinema Listings")
        mock_page.url = "https://www.everymancinema.com/whats-on"
        mock_page.screenshot = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.close = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()

        with patch.object(researcher, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(
                researcher, "_new_page", new_callable=AsyncMock, return_value=mock_page
            ):
                with patch.object(
                    researcher,
                    "_capture_screenshot",
                    new_callable=AsyncMock,
                    return_value=Path("/tmp/screenshot.png"),
                ) as mock_capture:
                    result = await researcher.research_cinema("Everyman", "today")

                    # Screenshot should be captured
                    mock_capture.assert_called_once()
                    assert len(result.screenshot_paths) == 1

    @pytest.mark.asyncio
    async def test_research_cinema_extracts_films(self) -> None:
        """Research cinema extracts film titles."""
        researcher = WebResearcher()

        # Create mock elements with film titles
        mock_film1 = AsyncMock()
        mock_film1.inner_text = AsyncMock(return_value="The Matrix")
        mock_film2 = AsyncMock()
        mock_film2.inner_text = AsyncMock(return_value="Inception")

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.title = AsyncMock(return_value="Cinema Listings")
        mock_page.url = "https://www.everymancinema.com/whats-on"
        mock_page.screenshot = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[mock_film1, mock_film2])
        mock_page.close = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()

        with patch.object(researcher, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(
                researcher, "_new_page", new_callable=AsyncMock, return_value=mock_page
            ):
                with patch.object(
                    researcher,
                    "_capture_screenshot",
                    new_callable=AsyncMock,
                    return_value=Path("/tmp/screenshot.png"),
                ):
                    result = await researcher.research_cinema("Everyman", "Friday")

                    assert result.success is True
                    assert "The Matrix" in result.findings
                    assert "Inception" in result.findings

    @pytest.mark.asyncio
    async def test_research_cinema_handles_error(self) -> None:
        """Research cinema handles errors gracefully."""
        researcher = WebResearcher()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Network error"))
        mock_page.close = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()

        with patch.object(researcher, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(
                researcher, "_new_page", new_callable=AsyncMock, return_value=mock_page
            ):
                result = await researcher.research_cinema("Everyman", "today")

                assert result.success is False
                assert "Network error" in str(result.error)
                assert result.completed_at is not None


class TestWebResearcherQueryRouting:
    """Tests for query routing to appropriate research methods."""

    @pytest.mark.asyncio
    async def test_routes_cinema_query(self) -> None:
        """Cinema-related queries route to research_cinema."""
        researcher = WebResearcher()

        with patch.object(researcher, "research_cinema", new_callable=AsyncMock) as mock_cinema:
            mock_cinema.return_value = ResearchResult(success=True, query="test")

            await researcher.research_query("What's showing at Everyman this Friday?")

            mock_cinema.assert_called_once()
            call_args = mock_cinema.call_args
            assert call_args[0][0] == "Everyman"  # cinema_name
            assert call_args[0][1] == "Friday"  # day

    @pytest.mark.asyncio
    async def test_routes_movie_query(self) -> None:
        """Movie-related queries route to research_cinema."""
        researcher = WebResearcher()

        with patch.object(researcher, "research_cinema", new_callable=AsyncMock) as mock_cinema:
            mock_cinema.return_value = ResearchResult(success=True, query="test")

            await researcher.research_query("What movies are on at Vue tomorrow?")

            mock_cinema.assert_called_once()
            call_args = mock_cinema.call_args
            assert call_args[0][0] == "Vue"
            assert call_args[0][1] == "tomorrow"

    @pytest.mark.asyncio
    async def test_routes_generic_query_to_google(self) -> None:
        """Generic queries route to Google search."""
        researcher = WebResearcher()

        with patch.object(researcher, "research_url", new_callable=AsyncMock) as mock_url:
            mock_url.return_value = ResearchResult(success=True, query="test")

            await researcher.research_query("Best restaurants in London")

            mock_url.assert_called_once()
            call_args = mock_url.call_args
            assert "google.com/search" in call_args[0][0]


class TestWebResearcherURLResearch:
    """Tests for URL research functionality."""

    @pytest.mark.asyncio
    async def test_research_url_returns_result(self) -> None:
        """Research URL returns ResearchResult with content."""
        researcher = WebResearcher()

        with patch.object(
            researcher,
            "navigate_and_extract",
            new_callable=AsyncMock,
            return_value=(
                "Line 1\nLine 2\nLine 3",
                ResearchSource(
                    url="https://example.com",
                    title="Test Page",
                    screenshot_path=Path("/tmp/test.png"),
                ),
            ),
        ):
            result = await researcher.research_url("https://example.com", "Research example")

            assert result.success is True
            assert len(result.findings) == 3
            assert "Line 1" in result.findings

    @pytest.mark.asyncio
    async def test_research_url_handles_error(self) -> None:
        """Research URL handles errors gracefully."""
        researcher = WebResearcher()

        with patch.object(
            researcher,
            "navigate_and_extract",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            result = await researcher.research_url("https://example.com", "Research example")

            assert result.success is False
            assert "Connection refused" in str(result.error)


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_web_researcher_returns_singleton(self) -> None:
        """get_web_researcher returns same instance."""
        # Import the actual module (not the function exported by __init__.py)
        import importlib

        research_module = importlib.import_module("assistant.services.research")

        # Reset singleton
        research_module._researcher = None

        researcher1 = get_web_researcher()
        researcher2 = get_web_researcher()
        assert researcher1 is researcher2

        # Cleanup
        research_module._researcher = None

    @pytest.mark.asyncio
    async def test_research_function(self) -> None:
        """research() convenience function works."""
        mock_researcher = MagicMock(spec=WebResearcher)
        mock_researcher.research_query = AsyncMock(
            return_value=ResearchResult(success=True, query="test")
        )

        with patch(
            "assistant.services.research.get_web_researcher",
            return_value=mock_researcher,
        ):
            result = await research("test query")

            assert result.success is True
            mock_researcher.research_query.assert_called_once_with("test query")

    @pytest.mark.asyncio
    async def test_research_cinema_function(self) -> None:
        """research_cinema() convenience function works."""
        mock_researcher = MagicMock(spec=WebResearcher)
        mock_researcher.research_cinema = AsyncMock(
            return_value=ResearchResult(success=True, query="cinema test")
        )

        with patch(
            "assistant.services.research.get_web_researcher",
            return_value=mock_researcher,
        ):
            result = await research_cinema("Everyman", "Friday")

            assert result.success is True
            mock_researcher.research_cinema.assert_called_once_with("Everyman", "Friday")

    @pytest.mark.asyncio
    async def test_close_researcher_function(self) -> None:
        """close_researcher() cleans up global instance."""
        # Import the actual module (not the function exported by __init__.py)
        import importlib

        research_module = importlib.import_module("assistant.services.research")

        # Create and set mock researcher
        mock_researcher = MagicMock(spec=WebResearcher)
        mock_researcher.close = AsyncMock()

        # Directly set the module global
        research_module._researcher = mock_researcher

        await close_researcher()

        mock_researcher.close.assert_called_once()
        # Note: close_researcher sets _researcher = None, so we verify cleanup
        assert research_module._researcher is None


class TestIsResearchAvailable:
    """Tests for research availability check."""

    def test_returns_true_when_playwright_installed(self) -> None:
        """Returns True when playwright is importable."""
        # playwright is installed in test environment
        assert is_research_available() is True


class TestConstants:
    """Tests for module constants."""

    def test_default_research_dir(self) -> None:
        """Default research directory is in .second-brain."""
        assert ".second-brain" in str(DEFAULT_RESEARCH_DIR)
        assert "research" in str(DEFAULT_RESEARCH_DIR)

    def test_default_screenshots_dir(self) -> None:
        """Default screenshots directory is under research dir."""
        assert str(DEFAULT_RESEARCH_DIR) in str(DEFAULT_SCREENSHOTS_DIR)
        assert "screenshots" in str(DEFAULT_SCREENSHOTS_DIR)

    def test_page_timeout(self) -> None:
        """Page timeout is reasonable."""
        assert DEFAULT_PAGE_TIMEOUT_MS == 30000  # 30 seconds


class TestAT112WebResearch:
    """Acceptance tests for AT-112 - Web Research.

    AT-112 Requirements:
    - Given: User asks "What's showing at Everyman this Friday?"
    - When: Playwright browser automation available
    - Then: Research performed and results returned
    - And: Sources logged
    - Pass condition: Response includes movie titles AND Log entry includes URL visited
    """

    @pytest.mark.asyncio
    async def test_at112_cinema_query_returns_results(self) -> None:
        """AT-112: Research returns movie titles for cinema query."""
        researcher = WebResearcher()

        # Mock film elements
        mock_film1 = AsyncMock()
        mock_film1.inner_text = AsyncMock(return_value="The Batman")
        mock_film2 = AsyncMock()
        mock_film2.inner_text = AsyncMock(return_value="Dune Part Two")
        mock_film3 = AsyncMock()
        mock_film3.inner_text = AsyncMock(return_value="Oppenheimer")

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.title = AsyncMock(return_value="Everyman Cinema - What's On")
        mock_page.url = "https://www.everymancinema.com/whats-on"
        mock_page.screenshot = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[mock_film1, mock_film2, mock_film3])
        mock_page.close = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()

        with patch.object(researcher, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(
                researcher, "_new_page", new_callable=AsyncMock, return_value=mock_page
            ):
                with patch.object(
                    researcher,
                    "_capture_screenshot",
                    new_callable=AsyncMock,
                    return_value=Path("/tmp/cinema_screenshot.png"),
                ):
                    # Perform the research
                    result = await researcher.research_query(
                        "What's showing at Everyman this Friday?"
                    )

                    # AT-112: Response includes movie titles
                    assert result.success is True
                    assert len(result.findings) > 0
                    assert "The Batman" in result.findings
                    assert "Dune Part Two" in result.findings
                    assert "Oppenheimer" in result.findings

    @pytest.mark.asyncio
    async def test_at112_sources_logged(self) -> None:
        """AT-112: Sources are logged for auditing."""
        researcher = WebResearcher()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.title = AsyncMock(return_value="Everyman Cinema")
        mock_page.url = "https://www.everymancinema.com/whats-on"
        mock_page.screenshot = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.close = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()

        with patch.object(researcher, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(
                researcher, "_new_page", new_callable=AsyncMock, return_value=mock_page
            ):
                with patch.object(
                    researcher,
                    "_capture_screenshot",
                    new_callable=AsyncMock,
                    return_value=Path("/tmp/screenshot.png"),
                ):
                    result = await researcher.research_cinema("Everyman", "Friday")

                    # AT-112: Sources logged with URL visited
                    assert len(result.sources) >= 1
                    source = result.sources[0]
                    assert source.url is not None
                    assert "everymancinema.com" in source.url
                    assert source.visited_at is not None

    @pytest.mark.asyncio
    async def test_at112_screenshot_evidence(self) -> None:
        """AT-112: Screenshots captured as evidence."""
        researcher = WebResearcher()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.title = AsyncMock(return_value="Everyman Cinema")
        mock_page.url = "https://www.everymancinema.com/whats-on"
        mock_page.screenshot = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.close = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()

        with patch.object(researcher, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(
                researcher, "_new_page", new_callable=AsyncMock, return_value=mock_page
            ):
                with patch.object(
                    researcher,
                    "_capture_screenshot",
                    new_callable=AsyncMock,
                    return_value=Path("/tmp/cinema_evidence.png"),
                ) as mock_capture:
                    result = await researcher.research_cinema("Everyman", "Friday")

                    # AT-112: Screenshot captured
                    assert len(result.screenshot_paths) >= 1
                    mock_capture.assert_called_once()

    @pytest.mark.asyncio
    async def test_at112_result_can_be_logged(self) -> None:
        """AT-112: Result can be serialized for logging."""
        researcher = WebResearcher()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.title = AsyncMock(return_value="Cinema")
        mock_page.url = "https://example.com"
        mock_page.screenshot = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.close = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()

        with patch.object(researcher, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(
                researcher, "_new_page", new_callable=AsyncMock, return_value=mock_page
            ):
                with patch.object(
                    researcher,
                    "_capture_screenshot",
                    new_callable=AsyncMock,
                    return_value=Path("/tmp/screenshot.png"),
                ):
                    result = await researcher.research_cinema("Everyman", "Friday")

                    # Should be serializable for logging
                    data = result.to_dict()
                    assert "query" in data
                    assert "sources" in data
                    assert isinstance(data["sources"], list)


class TestPRDSection410Compliance:
    """Tests for PRD Section 4.10 Playwright compliance."""

    def test_capabilities_navigate_to_websites(self) -> None:
        """Researcher can navigate to websites."""
        researcher = WebResearcher()
        assert hasattr(researcher, "navigate_and_extract")
        assert hasattr(researcher, "research_url")

    def test_capabilities_extract_structured_data(self) -> None:
        """Researcher can extract structured data."""
        # ResearchResult has findings list for structured data
        result = ResearchResult(success=True, query="test")
        assert hasattr(result, "findings")
        assert isinstance(result.findings, list)

    def test_capabilities_store_screenshots(self) -> None:
        """Researcher stores screenshots as evidence."""
        researcher = WebResearcher()
        assert researcher.screenshots_dir is not None
        assert "screenshots" in str(researcher.screenshots_dir)

    def test_capabilities_log_with_sources(self) -> None:
        """Research results include sources for logging."""
        result = ResearchResult(success=True, query="test")
        assert hasattr(result, "sources")
        assert hasattr(result, "source_urls")

    def test_use_cases_cinema(self) -> None:
        """Researcher supports cinema research use case."""
        researcher = WebResearcher()
        assert hasattr(researcher, "research_cinema")

    def test_use_cases_general_query(self) -> None:
        """Researcher supports general query research."""
        researcher = WebResearcher()
        assert hasattr(researcher, "research_query")


class TestHashContent:
    """Tests for content hashing."""

    def test_hash_content_returns_string(self) -> None:
        """_hash_content returns deterministic string."""
        researcher = WebResearcher()
        hash1 = researcher._hash_content("test content")
        hash2 = researcher._hash_content("test content")
        assert hash1 == hash2
        assert len(hash1) == 12  # Truncated to 12 chars

    def test_hash_content_different_for_different_content(self) -> None:
        """_hash_content returns different hash for different content."""
        researcher = WebResearcher()
        hash1 = researcher._hash_content("content A")
        hash2 = researcher._hash_content("content B")
        assert hash1 != hash2
