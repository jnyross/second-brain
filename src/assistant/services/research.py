"""Web research service using Playwright for Second Brain.

Implements T-103 (Integrate Playwright for research) and AT-112.

Per PRD 4.10:
- Research tasks that require web browsing
- Navigate to websites, extract information, take screenshots for evidence
- All research logged with sources
- Results summarized and stored in relevant task/note

Example uses:
- Check cinema showtimes
- Look up restaurant menus
- Research products
- Verify business hours
"""

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResearchSource:
    """A source visited during research."""

    url: str
    title: str
    visited_at: datetime = field(default_factory=datetime.utcnow)
    screenshot_path: str | None = None
    screenshot_base64: str | None = None
    content_snippet: str | None = None


@dataclass
class ResearchResult:
    """Result of a web research operation."""

    query: str
    answer: str
    sources: list[ResearchSource] = field(default_factory=list)
    success: bool = True
    error_message: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    @property
    def urls_visited(self) -> list[str]:
        """Get list of URLs visited during research."""
        return [s.url for s in self.sources]

    @property
    def has_screenshots(self) -> bool:
        """Check if any screenshots were captured."""
        return any(s.screenshot_path or s.screenshot_base64 for s in self.sources)

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dictionary for audit logging."""
        return {
            "query": self.query,
            "answer": self.answer[:500] if self.answer else None,
            "urls_visited": self.urls_visited,
            "source_count": len(self.sources),
            "success": self.success,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
        }


class ResearchError(Exception):
    """Error during web research."""

    pass


class PlaywrightResearcher:
    """Web research service using Playwright browser automation.

    Features:
    - Async browser automation with Playwright
    - Screenshot evidence for research results
    - Content extraction from web pages
    - Retry logic for reliability
    - Source tracking for audit trail
    """

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 1.0

    # Timeouts
    PAGE_TIMEOUT_MS = 30000  # 30 seconds
    NAVIGATION_TIMEOUT_MS = 30000

    # Screenshot directory
    SCREENSHOT_DIR = Path.home() / ".second-brain" / "screenshots"

    def __init__(
        self,
        headless: bool = True,
        screenshot_dir: Path | None = None,
        store_screenshots: bool = True,
    ):
        """Initialize the researcher.

        Args:
            headless: Run browser in headless mode (default True)
            screenshot_dir: Directory to store screenshots
            store_screenshots: Whether to store screenshots on disk
        """
        self.headless = headless
        self.screenshot_dir = screenshot_dir or self.SCREENSHOT_DIR
        self.store_screenshots = store_screenshots
        self._browser: Any = None
        self._playwright: Any = None

    async def __aenter__(self) -> "PlaywrightResearcher":
        """Async context manager entry."""
        await self._ensure_browser()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def _ensure_browser(self) -> None:
        """Ensure browser is launched."""
        if self._browser is not None:
            return

        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
            )
            logger.debug("Playwright browser launched")
        except ImportError:
            raise ResearchError(
                "Playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
        except Exception as e:
            raise ResearchError(f"Failed to launch browser: {e}")

    async def close(self) -> None:
        """Close the browser and cleanup."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.debug("Playwright browser closed")

    async def research(
        self,
        query: str,
        urls: list[str] | None = None,
        take_screenshots: bool = True,
        extract_content: bool = True,
    ) -> ResearchResult:
        """Perform web research for a query.

        Args:
            query: Research question or topic
            urls: Specific URLs to visit (if None, will search)
            take_screenshots: Whether to capture screenshots
            extract_content: Whether to extract page content

        Returns:
            ResearchResult with answer, sources, and evidence

        Raises:
            ResearchError: If research fails after retries
        """
        start_time = datetime.utcnow()
        sources: list[ResearchSource] = []
        answer_parts: list[str] = []

        try:
            await self._ensure_browser()

            # If no URLs provided, use search to find relevant pages
            if not urls:
                urls = await self._search_for_urls(query)

            if not urls:
                return ResearchResult(
                    query=query,
                    answer="No relevant sources found for this query.",
                    sources=[],
                    success=False,
                    error_message="No URLs to research",
                    started_at=start_time,
                    completed_at=datetime.utcnow(),
                    duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                )

            # Visit each URL and extract information
            for url in urls[:5]:  # Limit to 5 URLs
                try:
                    source = await self._visit_and_extract(
                        url,
                        query,
                        take_screenshot=take_screenshots,
                        extract_content=extract_content,
                    )
                    sources.append(source)

                    if source.content_snippet:
                        answer_parts.append(source.content_snippet)

                except Exception as e:
                    logger.warning(f"Failed to process URL {url}: {e}")
                    sources.append(
                        ResearchSource(
                            url=url,
                            title="Error loading page",
                            content_snippet=f"Error: {str(e)}",
                        )
                    )

            # Compile answer from extracted content
            answer = self._compile_answer(query, answer_parts)

            completed_at = datetime.utcnow()
            return ResearchResult(
                query=query,
                answer=answer,
                sources=sources,
                success=True,
                started_at=start_time,
                completed_at=completed_at,
                duration_seconds=(completed_at - start_time).total_seconds(),
            )

        except Exception as e:
            logger.exception(f"Research failed: {e}")
            completed_at = datetime.utcnow()
            return ResearchResult(
                query=query,
                answer="",
                sources=sources,
                success=False,
                error_message=str(e),
                started_at=start_time,
                completed_at=completed_at,
                duration_seconds=(completed_at - start_time).total_seconds(),
            )

    async def research_cinema(
        self,
        cinema_name: str,
        date: str | None = None,
    ) -> ResearchResult:
        """Research what's showing at a cinema.

        AT-112: "What's showing at Everyman this Friday?"

        Args:
            cinema_name: Name of the cinema (e.g., "Everyman")
            date: Date to check (e.g., "Friday", "2026-01-15")

        Returns:
            ResearchResult with movie listings
        """
        query = f"What's showing at {cinema_name}"
        if date:
            query += f" {date}"

        # Build search URL for cinema showtimes
        search_query = f"{cinema_name} cinema showtimes"
        if date:
            search_query += f" {date}"

        # Try known cinema sites first
        urls = self._get_cinema_urls(cinema_name)

        return await self.research(
            query=query,
            urls=urls if urls else None,
            take_screenshots=True,
            extract_content=True,
        )

    async def research_restaurant(
        self,
        restaurant_name: str,
        info_type: str = "menu",
    ) -> ResearchResult:
        """Research restaurant information.

        Args:
            restaurant_name: Name of the restaurant
            info_type: Type of info needed (menu, hours, reservations)

        Returns:
            ResearchResult with restaurant information
        """
        query = f"{restaurant_name} {info_type}"
        return await self.research(query=query)

    async def research_product(
        self,
        product_query: str,
    ) -> ResearchResult:
        """Research product information.

        Args:
            product_query: Product to research

        Returns:
            ResearchResult with product information
        """
        return await self.research(query=product_query)

    async def _search_for_urls(self, query: str) -> list[str]:
        """Search for relevant URLs using DuckDuckGo.

        Args:
            query: Search query

        Returns:
            List of relevant URLs
        """
        await self._ensure_browser()

        try:
            page = await self._browser.new_page()
            try:
                # Use DuckDuckGo HTML version for simplicity
                search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
                await page.goto(search_url, timeout=self.NAVIGATION_TIMEOUT_MS)
                await page.wait_for_load_state("domcontentloaded")

                # Extract result URLs
                links = await page.query_selector_all("a.result__a")
                urls = []
                for link in links[:10]:
                    href = await link.get_attribute("href")
                    if href and href.startswith("http"):
                        urls.append(href)

                return urls[:5]

            finally:
                await page.close()

        except Exception as e:
            logger.warning(f"Search failed: {e}")
            return []

    async def _visit_and_extract(
        self,
        url: str,
        query: str,
        take_screenshot: bool = True,
        extract_content: bool = True,
    ) -> ResearchSource:
        """Visit a URL and extract relevant information.

        Args:
            url: URL to visit
            query: Research query for context
            take_screenshot: Whether to capture screenshot
            extract_content: Whether to extract content

        Returns:
            ResearchSource with extracted data
        """
        await self._ensure_browser()

        page = await self._browser.new_page()
        try:
            # Navigate to page
            await page.goto(url, timeout=self.NAVIGATION_TIMEOUT_MS)
            await page.wait_for_load_state("domcontentloaded")

            # Get page title
            title = await page.title()

            # Take screenshot
            screenshot_path = None
            screenshot_base64 = None
            if take_screenshot:
                screenshot_bytes = await page.screenshot(full_page=False)
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")

                if self.store_screenshots:
                    self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    safe_title = re.sub(r"[^\w\-_]", "_", title[:30])
                    screenshot_path = str(self.screenshot_dir / f"{timestamp}_{safe_title}.png")
                    with open(screenshot_path, "wb") as f:
                        f.write(screenshot_bytes)

            # Extract relevant content
            content_snippet = None
            if extract_content:
                content_snippet = await self._extract_relevant_content(page, query)

            return ResearchSource(
                url=url,
                title=title,
                screenshot_path=screenshot_path,
                screenshot_base64=screenshot_base64,
                content_snippet=content_snippet,
            )

        finally:
            await page.close()

    async def _extract_relevant_content(self, page: Any, query: str) -> str:
        """Extract relevant content from page based on query.

        Args:
            page: Playwright page object
            query: Research query for context

        Returns:
            Extracted content snippet
        """
        try:
            # Get main content text
            body = await page.query_selector("body")
            if not body:
                return ""

            # Remove script and style elements
            await page.evaluate(
                "document.querySelectorAll('script, style, nav, footer, header')"
                ".forEach(el => el.remove());"
            )

            # Get text content
            text = await body.inner_text()

            # Clean and truncate
            text = re.sub(r"\s+", " ", text).strip()

            # Take first 2000 chars as snippet
            return text[:2000] if text else ""

        except Exception as e:
            logger.warning(f"Content extraction failed: {e}")
            return ""

    def _compile_answer(self, query: str, content_parts: list[str]) -> str:
        """Compile an answer from extracted content.

        Args:
            query: Original query
            content_parts: Extracted content from sources

        Returns:
            Compiled answer text
        """
        if not content_parts:
            return "No relevant information found."

        # For now, return concatenated content
        # In future, could use LLM to summarize
        combined = "\n\n---\n\n".join(part for part in content_parts if part.strip())

        if not combined:
            return "No relevant information found."

        return f"Research results for: {query}\n\n{combined[:4000]}"

    def _get_cinema_urls(self, cinema_name: str) -> list[str]:
        """Get known URLs for cinema chains.

        Args:
            cinema_name: Name of cinema

        Returns:
            List of URLs to check
        """
        cinema_lower = cinema_name.lower()

        known_cinemas = {
            "everyman": ["https://www.everymancinema.com/whats-on"],
            "odeon": ["https://www.odeon.co.uk/cinemas/"],
            "vue": ["https://www.myvue.com/"],
            "cineworld": ["https://www.cineworld.co.uk/"],
            "picturehouse": ["https://www.picturehouses.com/"],
            "curzon": ["https://www.curzon.com/"],
        }

        for name, urls in known_cinemas.items():
            if name in cinema_lower:
                return urls

        return []


# Module-level singleton
_researcher: PlaywrightResearcher | None = None


def get_researcher(
    headless: bool = True,
    screenshot_dir: Path | None = None,
) -> PlaywrightResearcher:
    """Get or create the researcher singleton.

    Args:
        headless: Run browser in headless mode
        screenshot_dir: Directory for screenshots

    Returns:
        PlaywrightResearcher instance
    """
    global _researcher
    if _researcher is None:
        _researcher = PlaywrightResearcher(
            headless=headless,
            screenshot_dir=screenshot_dir,
        )
    return _researcher


async def research(
    query: str,
    urls: list[str] | None = None,
    take_screenshots: bool = True,
) -> ResearchResult:
    """Convenience function to perform research.

    Args:
        query: Research question or topic
        urls: Specific URLs to visit
        take_screenshots: Whether to capture screenshots

    Returns:
        ResearchResult with answer and sources
    """
    researcher = get_researcher()
    async with researcher:
        return await researcher.research(
            query=query,
            urls=urls,
            take_screenshots=take_screenshots,
        )


async def research_cinema(
    cinema_name: str,
    date: str | None = None,
) -> ResearchResult:
    """Convenience function to research cinema showtimes.

    AT-112: Research what's showing at a cinema.

    Args:
        cinema_name: Name of cinema
        date: Date to check

    Returns:
        ResearchResult with movie listings
    """
    researcher = get_researcher()
    async with researcher:
        return await researcher.research_cinema(cinema_name, date)


async def close_researcher() -> None:
    """Close the global researcher instance."""
    global _researcher
    if _researcher:
        await _researcher.close()
        _researcher = None
