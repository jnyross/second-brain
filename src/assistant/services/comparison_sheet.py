"""Comparison sheet generator service (T-166).

Creates Google Sheets comparison matrices from user requests like:
- "Compare iPhone vs Android - create a sheet"
- "Make a comparison of AWS vs GCP vs Azure"

Per PRD AT-126:
- Sheet created with comparison matrix structure
- Columns: Criteria, Option 1, Option 2, ..., Notes
- Default criteria rows if not specified
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from assistant.google.drive import DriveClient, DriveFile
    from assistant.notion.client import NotionClient

from assistant.notion.schemas import TaskPriority, TaskSource, TaskStatus

logger = logging.getLogger(__name__)

# Patterns for detecting comparison requests
COMPARISON_PATTERNS = [
    # "Compare X vs Y"
    r"compare\s+(.+?)\s+(?:vs\.?|versus|and)\s+(.+?)(?:\s*[-–—]\s*create\s+(?:a\s+)?sheet)?",
    # "Create a comparison of X and Y"
    r"create\s+(?:a\s+)?comparison\s+(?:of\s+)?(.+?)\s+(?:vs\.?|versus|and)\s+(.+)",
    # "Make a comparison sheet for X vs Y"
    r"make\s+(?:a\s+)?comparison\s+(?:sheet\s+)?(?:for\s+)?(.+?)\s+(?:vs\.?|versus|and)\s+(.+)",
    # "X vs Y comparison"
    r"(.+?)\s+(?:vs\.?|versus)\s+(.+?)\s+comparison",
    # "Compare X, Y, and Z"
    r"compare\s+(.+?)(?:\s*[-–—]\s*create\s+(?:a\s+)?sheet)?$",
]

# Patterns indicating sheet creation is desired
SHEET_INDICATORS = [
    r"create\s+(?:a\s+)?sheet",
    r"make\s+(?:a\s+)?sheet",
    r"spreadsheet",
    r"comparison\s+sheet",
    r"comparison\s+matrix",
]


@dataclass
class ComparisonSheetResult:
    """Result of comparison sheet creation."""

    success: bool = False
    topic: str = ""
    options: list[str] = field(default_factory=list)
    criteria: list[str] = field(default_factory=list)
    drive_file_id: str | None = None
    drive_file_url: str | None = None
    task_id: str | None = None
    task_title: str = ""
    error: str = ""

    @property
    def has_drive_sheet(self) -> bool:
        """Check if Drive sheet was created."""
        return self.drive_file_id is not None

    @property
    def has_task(self) -> bool:
        """Check if Notion task was created."""
        return self.task_id is not None


def is_comparison_request(text: str) -> bool:
    """Check if text is a comparison sheet request.

    Returns True if text matches comparison patterns AND indicates
    sheet creation (vs just asking to compare verbally).

    Args:
        text: Input text to check

    Returns:
        True if this is a comparison sheet request
    """
    text_lower = text.lower().strip()

    # Must have some comparison pattern
    has_comparison = False
    for pattern in COMPARISON_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            has_comparison = True
            break

    if not has_comparison:
        return False

    # Must indicate sheet creation is desired
    for indicator in SHEET_INDICATORS:
        if re.search(indicator, text_lower, re.IGNORECASE):
            return True

    return False


def extract_comparison_options(text: str) -> list[str]:
    """Extract options to compare from text.

    Handles formats like:
    - "X vs Y"
    - "X and Y"
    - "X, Y, and Z"
    - "X vs Y vs Z"

    Args:
        text: Input text with comparison

    Returns:
        List of options to compare
    """
    text_lower = text.lower().strip()

    # Remove sheet creation suffixes
    text_lower = re.sub(r"\s*[-–—]\s*create\s+(?:a\s+)?sheet\s*$", "", text_lower)
    text_lower = re.sub(r"\s*[-–—]\s*make\s+(?:a\s+)?sheet\s*$", "", text_lower)
    text_lower = re.sub(r"\s*comparison\s*$", "", text_lower)

    # Try to extract from "Compare X vs Y" pattern
    match = re.search(r"compare\s+(.+)", text_lower, re.IGNORECASE)
    if match:
        options_text = match.group(1).strip()
    else:
        # Try "X vs Y" without compare prefix
        match = re.search(r"(.+?)\s+(?:vs\.?|versus)\s+(.+)", text_lower)
        if match:
            options_text = f"{match.group(1)} vs {match.group(2)}"
        else:
            options_text = text_lower

    # Split by "vs", "versus", "and", or comma
    # Handle "X vs Y vs Z" and "X, Y, and Z"
    options = re.split(r"\s+(?:vs\.?|versus|and)\s+|,\s*", options_text)

    # Clean up each option
    cleaned = []
    for opt in options:
        opt = opt.strip()
        # Remove common prefixes
        opt = re.sub(r"^(?:compare|comparison\s+of|make\s+a|create\s+a)\s+", "", opt)
        opt = re.sub(r"\s+sheet$", "", opt)
        if opt and opt not in ["a", "an", "the"]:
            # Capitalize first letter of each word
            opt = " ".join(word.capitalize() for word in opt.split())
            cleaned.append(opt)

    return cleaned


def extract_comparison_topic(text: str) -> str:
    """Extract the comparison topic from text.

    Args:
        text: Input text

    Returns:
        Topic string for the comparison
    """
    options = extract_comparison_options(text)
    if len(options) >= 2:
        return f"{options[0]} vs {options[1]}"
    elif options:
        return options[0]
    return "Comparison"


class ComparisonSheetService:
    """Service for creating comparison sheets in Google Drive."""

    DEFAULT_CRITERIA = [
        "Price",
        "Features",
        "Ease of Use",
        "Support",
        "Integration",
        "Performance",
        "Security",
        "Scalability",
    ]

    def __init__(
        self,
        drive_client: DriveClient | None = None,
        notion_client: NotionClient | None = None,
    ) -> None:
        """Initialize comparison sheet service.

        Args:
            drive_client: Optional DriveClient instance
            notion_client: Optional NotionClient for task creation
        """
        self._drive_client = drive_client
        self._notion_client = notion_client

    def _get_drive_client(self) -> DriveClient:
        """Get or create DriveClient."""
        if self._drive_client is None:
            from assistant.google.drive import DriveClient

            self._drive_client = DriveClient()
        return self._drive_client

    def _get_notion_client(self) -> NotionClient:
        """Get or create NotionClient."""
        if self._notion_client is None:
            from assistant.notion.client import NotionClient

            self._notion_client = NotionClient()
        return self._notion_client

    async def create_comparison_sheet(
        self,
        query: str,
        options: list[str] | None = None,
        criteria: list[str] | None = None,
        create_task: bool = True,
    ) -> ComparisonSheetResult:
        """Create a comparison sheet from user query.

        Args:
            query: User's comparison request
            options: Optional list of options (extracted from query if not provided)
            criteria: Optional list of criteria (uses defaults if not provided)
            create_task: Whether to create a Notion task linking to the sheet

        Returns:
            ComparisonSheetResult with success status and details
        """
        result = ComparisonSheetResult()

        try:
            # Extract options if not provided
            if options is None:
                options = extract_comparison_options(query)

            if len(options) < 2:
                result.error = "Need at least 2 options to compare"
                return result

            result.options = options
            result.topic = f"{options[0]} vs {options[1]}"
            if len(options) > 2:
                result.topic = " vs ".join(options[:3])
                if len(options) > 3:
                    result.topic += f" (+{len(options) - 3} more)"

            # Use provided criteria or defaults
            result.criteria = criteria or self.DEFAULT_CRITERIA

            # Create the sheet
            drive_client = self._get_drive_client()
            drive_file = await drive_client.create_comparison_sheet(
                title=result.topic,
                options=options,
                criteria=result.criteria,
            )

            result.drive_file_id = drive_file.id
            result.drive_file_url = drive_file.web_view_link
            result.success = True

            # Create Notion task if requested
            if create_task:
                await self._create_task(result, drive_file)

            logger.info(f"Created comparison sheet: {result.topic}")

        except Exception as e:
            logger.error(f"Failed to create comparison sheet: {e}")
            result.error = str(e)

        return result

    async def _create_task(
        self, result: ComparisonSheetResult, drive_file: DriveFile
    ) -> None:
        """Create a Notion task linked to the comparison sheet.

        Args:
            result: Result object to update
            drive_file: Created Drive file
        """
        try:
            from assistant.notion.schemas import Task

            notion_client = self._get_notion_client()

            task_title = f"Complete comparison: {result.topic}"
            result.task_title = task_title

            task = Task(
                title=task_title,
                status=TaskStatus.TODO,
                priority=TaskPriority.MEDIUM,
                source=TaskSource.AI_CREATED,
                drive_file_id=drive_file.id,
                drive_file_url=drive_file.web_view_link,
                notes=f"Fill in comparison sheet with {len(result.criteria)} criteria across {len(result.options)} options.",
            )

            result.task_id = await notion_client.create_task(task)

        except Exception as e:
            # Task creation failure shouldn't fail the whole operation
            logger.warning(f"Failed to create task for comparison sheet: {e}")

    def format_success_message(self, result: ComparisonSheetResult) -> str:
        """Format success message for user.

        Args:
            result: Comparison sheet result

        Returns:
            Formatted message string
        """
        parts = [f"Created comparison sheet: {result.topic}"]
        parts.append(f"Options: {', '.join(result.options)}")
        parts.append(f"Criteria: {len(result.criteria)} rows")

        if result.drive_file_url:
            parts.append(f"Link: {result.drive_file_url}")

        if result.task_title:
            parts.append(f"Task: {result.task_title}")

        return "\n".join(parts)

    def format_failure_message(self, result: ComparisonSheetResult) -> str:
        """Format failure message for user.

        Args:
            result: Comparison sheet result

        Returns:
            Formatted error message
        """
        return f"Failed to create comparison sheet: {result.error}"


# Module-level singleton
_service: ComparisonSheetService | None = None


def get_comparison_sheet_service() -> ComparisonSheetService:
    """Get singleton ComparisonSheetService instance."""
    global _service
    if _service is None:
        _service = ComparisonSheetService()
    return _service


async def create_comparison_sheet(
    query: str,
    options: list[str] | None = None,
    criteria: list[str] | None = None,
    create_task: bool = True,
) -> ComparisonSheetResult:
    """Convenience function to create comparison sheet.

    Args:
        query: User's comparison request
        options: Optional list of options
        criteria: Optional list of criteria
        create_task: Whether to create a Notion task

    Returns:
        ComparisonSheetResult
    """
    service = get_comparison_sheet_service()
    return await service.create_comparison_sheet(query, options, criteria, create_task)
