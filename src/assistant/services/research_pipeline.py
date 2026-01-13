"""Research-to-Doc pipeline service.

This module implements T-164: Build research-to-doc pipeline per PRD AT-124.
When user requests research, this pipeline:
1. Performs web research via Playwright
2. Creates a Google Doc in Second Brain/Research/ folder with findings
3. Creates a Notion task linking to the Drive document

Per PRD AT-124:
- "Research best CRM options" creates Google Doc in Second Brain/Research/
- Document populated with research findings
- Task created linking to Drive document
- Pass: Drive API confirms doc exists AND task.drive_file_id populated
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from assistant.google.drive import DriveClient, DriveFile
    from assistant.notion.client import NotionClient
    from assistant.services.research import ResearchResult, WebResearcher

logger = logging.getLogger(__name__)


@dataclass
class ResearchPipelineResult:
    """Result of the research-to-doc pipeline.

    Attributes:
        success: Whether pipeline completed successfully
        query: Original research query
        research_success: Whether web research succeeded
        findings_count: Number of findings from research
        drive_file_id: Google Drive file ID if created
        drive_file_url: Google Drive web view URL if created
        task_id: Notion task ID if created
        task_title: Notion task title
        error: Error message if failed
        telegram_message: Formatted message for user response
    """

    success: bool = False
    query: str = ""
    research_success: bool = False
    findings_count: int = 0
    sources_count: int = 0
    drive_file_id: str | None = None
    drive_file_url: str | None = None
    task_id: str | None = None
    task_title: str | None = None
    error: str | None = None
    telegram_message: str = ""

    @property
    def has_drive_doc(self) -> bool:
        """Check if Drive document was created."""
        return self.drive_file_id is not None

    @property
    def has_task(self) -> bool:
        """Check if Notion task was created."""
        return self.task_id is not None


# Research query patterns
RESEARCH_PATTERNS = [
    r"^research\s+(.+)",  # "Research X"
    r"^find\s+out\s+(?:about\s+)?(.+)",  # "Find out about X"
    r"^look\s+(?:up|into)\s+(.+)",  # "Look up X" or "Look into X"
    r"^investigate\s+(.+)",  # "Investigate X"
    r"^what\s+(?:are\s+)?(?:the\s+)?best\s+(.+)",  # "What are the best X"
    r"^compare\s+(.+)",  # "Compare X"
]


def is_research_request(text: str) -> bool:
    """Check if text is a research request.

    Args:
        text: User input text

    Returns:
        True if text matches a research pattern
    """
    text_lower = text.lower().strip()
    for pattern in RESEARCH_PATTERNS:
        if re.match(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def extract_research_topic(text: str) -> str:
    """Extract the research topic from a query.

    Args:
        text: User input text

    Returns:
        Extracted topic string
    """
    text_lower = text.lower().strip()
    for pattern in RESEARCH_PATTERNS:
        match = re.match(pattern, text_lower, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    # Fallback: return the whole text after "research"
    return text


class ResearchPipeline:
    """Pipeline service for research → Drive doc → Task flow.

    This service orchestrates the complete research pipeline per PRD AT-124:
    1. Accept research request
    2. Perform web research via WebResearcher
    3. Create Google Doc with findings via DriveClient
    4. Create Notion task with drive_file_id link

    Example:
        pipeline = ResearchPipeline()
        result = await pipeline.execute("Research best CRM options for small business")
        if result.success:
            print(f"Doc: {result.drive_file_url}")
            print(f"Task: {result.task_id}")
    """

    def __init__(
        self,
        web_researcher: "WebResearcher | None" = None,
        drive_client: "DriveClient | None" = None,
        notion_client: "NotionClient | None" = None,
    ) -> None:
        """Initialize the research pipeline.

        Args:
            web_researcher: WebResearcher instance for performing research
            drive_client: DriveClient instance for creating docs
            notion_client: NotionClient instance for creating tasks
        """
        self._web_researcher = web_researcher
        self._drive_client = drive_client
        self._notion_client = notion_client

    @property
    def web_researcher(self) -> "WebResearcher":
        """Get or create web researcher."""
        if self._web_researcher is None:
            from assistant.services.research import get_web_researcher

            self._web_researcher = get_web_researcher()
        return self._web_researcher

    @property
    def drive_client(self) -> "DriveClient":
        """Get or create drive client."""
        if self._drive_client is None:
            from assistant.google.drive import DriveClient

            self._drive_client = DriveClient()
        return self._drive_client

    @property
    def notion_client(self) -> "NotionClient":
        """Get or create notion client."""
        if self._notion_client is None:
            from assistant.notion.client import NotionClient

            self._notion_client = NotionClient()
        return self._notion_client

    async def execute(
        self,
        query: str,
        project: str | None = None,
        chat_id: str | None = None,
    ) -> ResearchPipelineResult:
        """Execute the complete research pipeline.

        Steps:
        1. Perform web research
        2. Create Google Doc with findings
        3. Create Notion task linking to doc

        Args:
            query: Research query (e.g., "Research best CRM options")
            project: Optional project name for folder organization
            chat_id: Optional Telegram chat ID for logging

        Returns:
            ResearchPipelineResult with all artifacts
        """
        result = ResearchPipelineResult(query=query)
        topic = extract_research_topic(query)

        try:
            # Step 1: Perform web research
            logger.info(f"Starting research pipeline for: {topic}")
            research_result = await self._perform_research(topic)
            result.research_success = research_result.success
            result.findings_count = len(research_result.findings)
            result.sources_count = len(research_result.sources)

            if not research_result.success:
                result.error = f"Research failed: {research_result.error}"
                result.telegram_message = self._format_failure_message(result)
                return result

            # Step 2: Create Google Doc with findings
            drive_file = await self._create_research_doc(
                topic=topic,
                research_result=research_result,
                project=project,
            )
            result.drive_file_id = drive_file.id
            result.drive_file_url = drive_file.web_view_link

            # Step 3: Create Notion task linking to doc
            task_id, task_title = await self._create_research_task(
                topic=topic,
                drive_file=drive_file,
                findings_count=result.findings_count,
            )
            result.task_id = task_id
            result.task_title = task_title

            # Success
            result.success = True
            result.telegram_message = self._format_success_message(result)
            logger.info(f"Research pipeline completed: {result.drive_file_id}, {result.task_id}")

        except Exception as e:
            logger.exception(f"Research pipeline failed: {e}")
            result.error = str(e)
            result.telegram_message = self._format_failure_message(result)

        return result

    async def _perform_research(self, topic: str) -> "ResearchResult":
        """Perform web research on the topic.

        Args:
            topic: Research topic

        Returns:
            ResearchResult from WebResearcher
        """
        return await self.web_researcher.research_query(topic)

    async def _create_research_doc(
        self,
        topic: str,
        research_result: "ResearchResult",
        project: str | None = None,
    ) -> "DriveFile":
        """Create Google Doc with research findings.

        Args:
            topic: Research topic
            research_result: ResearchResult with findings
            project: Optional project name for folder

        Returns:
            DriveFile for the created document
        """
        # Format findings for document
        findings_text = self._format_findings_for_doc(research_result)

        # Create the document
        return await self.drive_client.create_research_document(
            topic=topic,
            project=project,
            initial_findings=findings_text,
        )

    def _format_findings_for_doc(self, research_result: "ResearchResult") -> str:
        """Format research findings for Google Doc content.

        Args:
            research_result: ResearchResult with findings and sources

        Returns:
            Formatted text for document
        """
        lines: list[str] = []

        # Findings section
        if research_result.findings:
            for finding in research_result.findings:
                lines.append(f"- {finding}")
        else:
            lines.append("_No specific findings extracted._")

        lines.append("")

        # Sources section
        if research_result.sources:
            lines.append("**Sources:**")
            for source in research_result.sources:
                if source.title:
                    lines.append(f"- {source.title}: {source.url}")
                else:
                    lines.append(f"- {source.url}")
                if source.screenshot_path:
                    lines.append(f"  (Screenshot: {source.screenshot_path})")

        # Metadata
        if research_result.duration_seconds:
            lines.append("")
            lines.append(f"_Research completed in {research_result.duration_seconds:.1f}s_")

        return "\n".join(lines)

    async def _create_research_task(
        self,
        topic: str,
        drive_file: "DriveFile",
        findings_count: int,
    ) -> tuple[str, str]:
        """Create Notion task linking to Drive document.

        Args:
            topic: Research topic
            drive_file: DriveFile for the created document
            findings_count: Number of findings for notes

        Returns:
            Tuple of (task_id, task_title)
        """
        from assistant.notion.schemas import Task, TaskPriority, TaskSource, TaskStatus

        task_title = f"Review research: {topic}"
        task = Task(
            title=task_title,
            status=TaskStatus.TODO,
            priority=TaskPriority.MEDIUM,
            source=TaskSource.AI_CREATED,
            created_by="ai",
            drive_file_id=drive_file.id,
            drive_file_url=drive_file.web_view_link,
            notes=f"Research: {findings_count} findings. See: {drive_file.web_view_link}",
        )

        task_id = await self.notion_client.create_task(task)
        return task_id, task_title

    def _format_success_message(self, result: ResearchPipelineResult) -> str:
        """Format success message for Telegram.

        Args:
            result: ResearchPipelineResult

        Returns:
            Formatted Telegram message
        """
        lines = [
            f"Research completed for: **{result.query}**",
            "",
            f"Found {result.findings_count} items from {result.sources_count} sources",
            "",
            "Created Google Doc with findings",
            f"[View Document]({result.drive_file_url})",
            "",
            f"Created task: **{result.task_title}**",
        ]
        return "\n".join(lines)

    def _format_failure_message(self, result: ResearchPipelineResult) -> str:
        """Format failure message for Telegram.

        Args:
            result: ResearchPipelineResult

        Returns:
            Formatted Telegram message
        """
        return f"Research failed for: **{result.query}**\n\nError: {result.error}"


# Module-level singleton
_pipeline: ResearchPipeline | None = None


def get_research_pipeline() -> ResearchPipeline:
    """Get the global ResearchPipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = ResearchPipeline()
    return _pipeline


async def execute_research_pipeline(
    query: str,
    project: str | None = None,
    chat_id: str | None = None,
) -> ResearchPipelineResult:
    """Convenience function to execute the research pipeline.

    Args:
        query: Research query
        project: Optional project name
        chat_id: Optional Telegram chat ID

    Returns:
        ResearchPipelineResult
    """
    pipeline = get_research_pipeline()
    return await pipeline.execute(query, project, chat_id)
