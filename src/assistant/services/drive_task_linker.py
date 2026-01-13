"""Drive-Task bidirectional linking service (T-167).

Provides high-level methods for linking Google Drive files to Notion tasks
and looking up tasks by their linked Drive files.

Key features:
- Forward linking: Task -> Drive file
- Reverse lookup: Drive file -> Task
- Unlink capability
- Batch operations

Example usage:
    linker = get_drive_task_linker()

    # Link a Drive file to a task
    result = await linker.link(task_id="abc123", drive_file_id="xyz789", drive_file_url="https://...")

    # Find task linked to a Drive file
    task = await linker.find_task_by_drive_file("xyz789")

    # Check if a Drive file is already linked
    is_linked = await linker.is_drive_file_linked("xyz789")
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from assistant.notion.client import NotionClient

logger = logging.getLogger(__name__)


@dataclass
class LinkResult:
    """Result of a link/unlink operation."""

    success: bool
    task_id: str | None = None
    drive_file_id: str | None = None
    drive_file_url: str | None = None
    error: str | None = None
    linked_at: datetime | None = None

    @property
    def has_link(self) -> bool:
        """Check if link was created/exists."""
        return self.success and self.drive_file_id is not None


@dataclass
class TaskInfo:
    """Extracted task information from Notion result."""

    page_id: str
    title: str
    drive_file_id: str | None = None
    drive_file_url: str | None = None
    status: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    @property
    def has_drive_link(self) -> bool:
        """Check if task has a Drive file link."""
        return self.drive_file_id is not None


class DriveTaskLinker:
    """High-level service for bidirectional Drive-Task linking."""

    def __init__(self, notion_client: NotionClient | None = None) -> None:
        """Initialize the linker.

        Args:
            notion_client: NotionClient instance (creates one if not provided)
        """
        self._notion = notion_client

    @property
    def notion(self) -> NotionClient:
        """Get or create NotionClient."""
        if self._notion is None:
            self._notion = NotionClient()
        return self._notion

    async def link(
        self,
        task_id: str,
        drive_file_id: str,
        drive_file_url: str | None = None,
    ) -> LinkResult:
        """Link a Google Drive file to a Notion task.

        Args:
            task_id: Notion page ID of the task
            drive_file_id: Google Drive file ID
            drive_file_url: Google Drive web view URL (optional but recommended)

        Returns:
            LinkResult with success status
        """
        try:
            await self.notion.update_task_drive_file(
                page_id=task_id,
                drive_file_id=drive_file_id,
                drive_file_url=drive_file_url,
            )
            logger.info(f"Linked Drive file {drive_file_id} to task {task_id}")
            return LinkResult(
                success=True,
                task_id=task_id,
                drive_file_id=drive_file_id,
                drive_file_url=drive_file_url,
                linked_at=datetime.now(UTC),
            )
        except Exception as e:
            logger.error(f"Failed to link Drive file to task: {e}")
            return LinkResult(
                success=False,
                task_id=task_id,
                drive_file_id=drive_file_id,
                error=str(e),
            )

    async def unlink(self, task_id: str) -> LinkResult:
        """Remove Drive file link from a task.

        Args:
            task_id: Notion page ID of the task

        Returns:
            LinkResult with success status
        """
        try:
            await self.notion.update_task_drive_file(
                page_id=task_id,
                drive_file_id=None,
                drive_file_url=None,
            )
            logger.info(f"Unlinked Drive file from task {task_id}")
            return LinkResult(
                success=True,
                task_id=task_id,
            )
        except Exception as e:
            logger.error(f"Failed to unlink Drive file from task: {e}")
            return LinkResult(
                success=False,
                task_id=task_id,
                error=str(e),
            )

    async def find_task_by_drive_file(
        self,
        drive_file_id: str,
        include_deleted: bool = False,
    ) -> TaskInfo | None:
        """Find the task linked to a specific Drive file.

        Args:
            drive_file_id: Google Drive file ID
            include_deleted: Include soft-deleted tasks

        Returns:
            TaskInfo if found, None otherwise
        """
        result = await self.notion.query_task_by_drive_file(
            drive_file_id=drive_file_id,
            include_deleted=include_deleted,
        )

        if result is None:
            return None

        return self._extract_task_info(result)

    async def get_task_with_drive_info(self, task_id: str) -> TaskInfo | None:
        """Get a task with its Drive file information.

        Args:
            task_id: Notion page ID of the task

        Returns:
            TaskInfo if found, None otherwise
        """
        result = await self.notion.get_task(task_id)

        if result is None:
            return None

        return self._extract_task_info(result)

    async def is_drive_file_linked(self, drive_file_id: str) -> bool:
        """Check if a Drive file is already linked to a task.

        Args:
            drive_file_id: Google Drive file ID

        Returns:
            True if linked, False otherwise
        """
        result = await self.notion.query_task_by_drive_file(drive_file_id)
        return result is not None

    async def is_task_linked_to_drive(self, task_id: str) -> bool:
        """Check if a task has a Drive file link.

        Args:
            task_id: Notion page ID of the task

        Returns:
            True if linked, False otherwise
        """
        task_info = await self.get_task_with_drive_info(task_id)
        return task_info is not None and task_info.has_drive_link

    async def relink(
        self,
        task_id: str,
        new_drive_file_id: str,
        new_drive_file_url: str | None = None,
    ) -> LinkResult:
        """Change the Drive file linked to a task.

        This replaces any existing link with the new one.

        Args:
            task_id: Notion page ID of the task
            new_drive_file_id: New Google Drive file ID
            new_drive_file_url: New Google Drive web view URL

        Returns:
            LinkResult with success status
        """
        # Simply use link() - it will overwrite the existing values
        return await self.link(task_id, new_drive_file_id, new_drive_file_url)

    def _extract_task_info(self, notion_result: dict[str, Any]) -> TaskInfo:
        """Extract TaskInfo from a Notion page result.

        Args:
            notion_result: Raw Notion API page result

        Returns:
            TaskInfo with extracted fields
        """
        page_id = notion_result.get("id", "")
        props = notion_result.get("properties", {})

        # Extract title
        title = ""
        title_prop = props.get("title", {})
        if title_prop.get("title"):
            title_parts = [t.get("plain_text", "") for t in title_prop["title"]]
            title = "".join(title_parts)

        # Extract drive_file_id (rich_text)
        drive_file_id = None
        drive_id_prop = props.get("drive_file_id", {})
        if drive_id_prop.get("rich_text"):
            texts = [t.get("plain_text", "") for t in drive_id_prop["rich_text"]]
            drive_file_id = "".join(texts) or None

        # Extract drive_file_url (url)
        drive_file_url = None
        drive_url_prop = props.get("drive_file_url", {})
        if drive_url_prop.get("url"):
            drive_file_url = drive_url_prop["url"]

        # Extract status (select)
        status = None
        status_prop = props.get("status", {})
        if status_prop.get("select"):
            status = status_prop["select"].get("name")

        return TaskInfo(
            page_id=page_id,
            title=title,
            drive_file_id=drive_file_id,
            drive_file_url=drive_file_url,
            status=status,
            raw_data=notion_result,
        )


# Module-level singleton
_linker: DriveTaskLinker | None = None


def get_drive_task_linker() -> DriveTaskLinker:
    """Get the singleton DriveTaskLinker instance."""
    global _linker
    if _linker is None:
        _linker = DriveTaskLinker()
    return _linker


async def link_drive_to_task(
    task_id: str,
    drive_file_id: str,
    drive_file_url: str | None = None,
) -> LinkResult:
    """Convenience function to link a Drive file to a task."""
    return await get_drive_task_linker().link(task_id, drive_file_id, drive_file_url)


async def find_task_by_drive_file(
    drive_file_id: str,
    include_deleted: bool = False,
) -> TaskInfo | None:
    """Convenience function to find task by Drive file."""
    return await get_drive_task_linker().find_task_by_drive_file(drive_file_id, include_deleted)


async def is_drive_file_linked(drive_file_id: str) -> bool:
    """Convenience function to check if Drive file is linked."""
    return await get_drive_task_linker().is_drive_file_linked(drive_file_id)


async def unlink_drive_from_task(task_id: str) -> LinkResult:
    """Convenience function to unlink Drive file from task."""
    return await get_drive_task_linker().unlink(task_id)
