"""Web research service using Playwright browser automation.

This module provides web research capabilities for the Second Brain assistant,
allowing automated browsing, content extraction, and screenshot capture.

Per PRD Section 4.10:
- Navigate to websites
- Extract structured data
- Store screenshots as evidence
- Log all research with sources
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Default paths for research artifacts
DEFAULT_RESEARCH_DIR = Path.home() / ".second-brain" / "research"
DEFAULT_SCREENSHOTS_DIR = DEFAULT_RESEARCH_DIR / "screenshots"

# Research timeouts
DEFAULT_PAGE_TIMEOUT_MS = 30000  # 30 seconds for page load
DEFAULT_NAVIGATION_TIMEOUT_MS = 15000  # 15 seconds for navigation


@dataclass
class ResearchSource:
    """A source visited during research.

    Attributes:
        url: The URL that was visited
        title: Page title if available
        visited_at: When the page was visited
        screenshot_path: Path to screenshot file if captured
        content_hash: Hash of extracted content for deduplication
    """

    url: str
    title: str | None = None
    visited_at: datetime = field(default_factory=datetime.now)
    screenshot_path: Path | None = None
    content_hash: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "url": self.url,
            "title": self.title,
            "visited_at": self.visited_at.isoformat(),
            "screenshot_path": str(self.screenshot_path) if self.screenshot_path else None,
            "content_hash": self.content_hash,
        }


@dataclass
class ResearchResult:
    """Result of a web research operation.

    Attributes:
        success: Whether research completed successfully
        query: The original research query
        findings: Extracted information/data
        sources: List of sources visited
        screenshot_paths: Paths to captured screenshots
        error: Error message if failed
        started_at: When research started
        completed_at: When research finished
    """

    success: bool
    query: str
    findings: list[str] = field(default_factory=list)
    sources: list[ResearchSource] = field(default_factory=list)
    screenshot_paths: list[Path] = field(default_factory=list)
    error: str | None = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        """Calculate research duration in seconds."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def source_urls(self) -> list[str]:
        """Get list of URLs visited."""
        return [s.url for s in self.sources]

    def summary(self) -> str:
        """Generate a human-readable summary of the research."""
        if not self.success:
            return f"Research failed: {self.error}"

        lines = [f"Found {len(self.findings)} items from {len(self.sources)} sources:"]
        for finding in self.findings[:10]:  # Limit to first 10 for summary
            lines.append(f"  - {finding}")
        if len(self.findings) > 10:
            lines.append(f"  ... and {len(self.findings) - 10} more")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "query": self.query,
            "findings": self.findings,
            "sources": [s.to_dict() for s in self.sources],
            "screenshot_paths": [str(p) for p in self.screenshot_paths],
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
        }


class WebResearcher:
    """Web research service using Playwright browser automation.

    This class provides methods for performing automated web research,
    including page navigation, content extraction, and screenshot capture.

    Example:
        researcher = WebResearcher()
        await researcher.initialize()
        result = await researcher.research_cinema("Everyman cinema", "Friday")
        await researcher.close()
    """

    def __init__(
        self,
        research_dir: Path | None = None,
        headless: bool = True,
    ) -> None:
        """Initialize the web researcher.

        Args:
            research_dir: Directory for storing research artifacts
            headless: Whether to run browser in headless mode
        """
        self.research_dir = research_dir or DEFAULT_RESEARCH_DIR
        self.screenshots_dir = self.research_dir / "screenshots"
        self.headless = headless
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Playwright browser.

        This must be called before performing any research operations.
        Creates necessary directories and launches the browser.
        """
        if self._initialized:
            return

        # Create directories
        self.research_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Import playwright here to avoid import errors when not installed
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            self._initialized = True
            logger.info("WebResearcher initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Playwright: {e}")
            raise

    async def close(self) -> None:
        """Close browser and cleanup resources."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if hasattr(self, "_playwright"):
            await self._playwright.stop()
        self._initialized = False
        logger.info("WebResearcher closed")

    def is_initialized(self) -> bool:
        """Check if browser is initialized and ready."""
        return self._initialized and self._browser is not None

    async def _ensure_initialized(self) -> None:
        """Ensure browser is initialized before operations."""
        if not self.is_initialized():
            await self.initialize()

    async def _new_page(self) -> Page:
        """Create a new browser page."""
        await self._ensure_initialized()
        if not self._context:
            raise RuntimeError("Browser context not available")
        page = await self._context.new_page()
        page.set_default_timeout(DEFAULT_PAGE_TIMEOUT_MS)
        page.set_default_navigation_timeout(DEFAULT_NAVIGATION_TIMEOUT_MS)
        return page

    async def _capture_screenshot(self, page: Page, name: str) -> Path:
        """Capture and save a screenshot.

        Args:
            page: Playwright page to capture
            name: Base name for the screenshot file

        Returns:
            Path to the saved screenshot
        """
        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:50]
        filename = f"{safe_name}_{timestamp}.png"
        screenshot_path = self.screenshots_dir / filename

        await page.screenshot(path=str(screenshot_path), full_page=False)
        logger.debug(f"Screenshot saved: {screenshot_path}")
        return screenshot_path

    def _hash_content(self, content: str) -> str:
        """Generate hash of content for deduplication."""
        return hashlib.md5(content.encode()).hexdigest()[:12]

    async def navigate_and_extract(
        self,
        url: str,
        selector: str | None = None,
        capture_screenshot: bool = True,
    ) -> tuple[str, ResearchSource]:
        """Navigate to URL and extract content.

        Args:
            url: URL to navigate to
            selector: Optional CSS selector to extract specific content
            capture_screenshot: Whether to capture a screenshot

        Returns:
            Tuple of (extracted_content, source_info)
        """
        page = await self._new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=10000)

            title = await page.title()

            # Extract content
            if selector:
                elements = await page.query_selector_all(selector)
                content = "\n".join([await el.inner_text() for el in elements])
            else:
                content = await page.inner_text("body")

            # Capture screenshot if requested
            screenshot_path = None
            if capture_screenshot:
                screenshot_path = await self._capture_screenshot(page, title or url)

            source = ResearchSource(
                url=url,
                title=title,
                screenshot_path=screenshot_path,
                content_hash=self._hash_content(content),
            )

            return content, source

        finally:
            await page.close()

    async def research_cinema(
        self,
        cinema_name: str,
        day: str = "today",
    ) -> ResearchResult:
        """Research cinema showtimes for a specific cinema.

        This is the primary method for AT-112 acceptance test.

        Args:
            cinema_name: Name of the cinema (e.g., "Everyman")
            day: Day to check (e.g., "today", "tomorrow", "Friday")

        Returns:
            ResearchResult with movie titles and showtimes
        """
        result = ResearchResult(
            success=False,
            query=f"What's showing at {cinema_name} {day}?",
        )

        try:
            await self._ensure_initialized()
            page = await self._new_page()

            try:
                # Strategy 1: Try direct cinema website search
                # Everyman cinema URLs follow a pattern
                if "everyman" in cinema_name.lower():
                    url = "https://www.everymancinema.com/whats-on"
                else:
                    # Fallback to Google search for other cinemas
                    search_query = f"{cinema_name} cinema showtimes {day}"
                    url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"

                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_load_state("networkidle", timeout=10000)

                title = await page.title()

                # Capture screenshot as evidence
                screenshot_path = await self._capture_screenshot(
                    page, f"cinema_{cinema_name}_{day}"
                )
                result.screenshot_paths.append(screenshot_path)

                # Record source
                source = ResearchSource(
                    url=page.url,
                    title=title,
                    screenshot_path=screenshot_path,
                )
                result.sources.append(source)

                # Extract movie information
                # For Everyman, look for film listings
                films = []
                if "everyman" in cinema_name.lower():
                    # Try to find film cards/listings
                    film_elements = await page.query_selector_all(
                        "[class*='film'], [class*='movie'], [class*='title'], h2, h3"
                    )
                    for elem in film_elements[:20]:  # Limit to prevent overload
                        text = await elem.inner_text()
                        text = text.strip()
                        if text and len(text) > 2 and len(text) < 100:
                            # Basic filtering for movie-like titles
                            films.append(text)
                else:
                    # For Google search, try to extract movie titles from results
                    result_elements = await page.query_selector_all(
                        "[data-movie-name], .movie-title, h3"
                    )
                    for elem in result_elements[:10]:
                        text = await elem.inner_text()
                        text = text.strip()
                        if text and len(text) > 2:
                            films.append(text)

                # Deduplicate and clean findings
                seen = set()
                for film in films:
                    film_clean = film.strip()
                    if film_clean.lower() not in seen:
                        seen.add(film_clean.lower())
                        result.findings.append(film_clean)

                result.success = True
                result.completed_at = datetime.now()

                logger.info(
                    f"Cinema research completed: {len(result.findings)} films found "
                    f"from {len(result.sources)} sources"
                )

            finally:
                await page.close()

        except Exception as e:
            result.error = str(e)
            result.completed_at = datetime.now()
            logger.error(f"Cinema research failed: {e}")

        return result

    async def research_url(
        self,
        url: str,
        query: str,
        selectors: list[str] | None = None,
    ) -> ResearchResult:
        """Research a specific URL.

        Args:
            url: URL to research
            query: The research query for context
            selectors: Optional CSS selectors to extract specific content

        Returns:
            ResearchResult with extracted information
        """
        result = ResearchResult(
            success=False,
            query=query,
        )

        try:
            content, source = await self.navigate_and_extract(
                url,
                selector=selectors[0] if selectors else None,
            )
            result.sources.append(source)
            if source.screenshot_path:
                result.screenshot_paths.append(source.screenshot_path)

            # Split content into findings
            lines = [line.strip() for line in content.split("\n") if line.strip()]
            result.findings = lines[:50]  # Limit findings

            result.success = True
            result.completed_at = datetime.now()

        except Exception as e:
            result.error = str(e)
            result.completed_at = datetime.now()
            logger.error(f"URL research failed: {e}")

        return result

    async def research_query(self, query: str) -> ResearchResult:
        """Perform general web research for a query.

        This method attempts to understand the query and route to
        appropriate specialized research methods.

        Args:
            query: Natural language research query

        Returns:
            ResearchResult with findings
        """
        query_lower = query.lower()

        # Route to specialized methods based on query content
        if "cinema" in query_lower or "movie" in query_lower or "showing" in query_lower:
            # Extract cinema name and day
            cinema_name = "Everyman"  # Default, could be extracted
            day = "today"

            # Simple day extraction
            if "friday" in query_lower:
                day = "Friday"
            elif "saturday" in query_lower:
                day = "Saturday"
            elif "sunday" in query_lower:
                day = "Sunday"
            elif "tomorrow" in query_lower:
                day = "tomorrow"

            # Simple cinema name extraction
            for cinema in ["Everyman", "Odeon", "Vue", "Cineworld", "Picturehouse"]:
                if cinema.lower() in query_lower:
                    cinema_name = cinema
                    break

            return await self.research_cinema(cinema_name, day)

        # Default: Google search
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        return await self.research_url(search_url, query)


# Module-level singleton
_researcher: WebResearcher | None = None


def get_web_researcher() -> WebResearcher:
    """Get the global WebResearcher instance."""
    global _researcher
    if _researcher is None:
        _researcher = WebResearcher()
    return _researcher


async def research(query: str) -> ResearchResult:
    """Convenience function to perform web research.

    Args:
        query: Research query

    Returns:
        ResearchResult with findings
    """
    researcher = get_web_researcher()
    return await researcher.research_query(query)


async def research_cinema(cinema_name: str, day: str = "today") -> ResearchResult:
    """Convenience function to research cinema showtimes.

    Args:
        cinema_name: Name of the cinema
        day: Day to check

    Returns:
        ResearchResult with movie listings
    """
    researcher = get_web_researcher()
    return await researcher.research_cinema(cinema_name, day)


async def close_researcher() -> None:
    """Close the global researcher and cleanup resources."""
    global _researcher
    if _researcher:
        await _researcher.close()
        _researcher = None


def is_research_available() -> bool:
    """Check if Playwright is installed and available."""
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False
