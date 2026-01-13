"""Tests for Drive-Task bidirectional linking service (T-167).

Tests the DriveTaskLinker service that:
1. Links Google Drive files to Notion tasks
2. Looks up tasks by their linked Drive file
3. Provides unlink and relink capabilities

Per T-167 requirements:
- Store drive_file_id in Notion Tasks
- Enable bidirectional linking (Task -> Drive and Drive -> Task)
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.services.drive_task_linker import (
    DriveTaskLinker,
    LinkResult,
    TaskInfo,
    find_task_by_drive_file,
    get_drive_task_linker,
    is_drive_file_linked,
    link_drive_to_task,
    unlink_drive_from_task,
)


class TestLinkResult:
    """Tests for LinkResult dataclass."""

    def test_default_values(self):
        """Test default values for result."""
        result = LinkResult(success=True)
        assert result.success is True
        assert result.task_id is None
        assert result.drive_file_id is None
        assert result.drive_file_url is None
        assert result.error is None
        assert result.linked_at is None

    def test_has_link_true_when_complete(self):
        """Test has_link is True when success and drive_file_id set."""
        result = LinkResult(success=True, drive_file_id="abc123")
        assert result.has_link is True

    def test_has_link_false_when_no_id(self):
        """Test has_link is False when no drive_file_id."""
        result = LinkResult(success=True)
        assert result.has_link is False

    def test_has_link_false_when_failed(self):
        """Test has_link is False when success is False."""
        result = LinkResult(success=False, drive_file_id="abc123")
        assert result.has_link is False

    def test_all_fields(self):
        """Test all fields set correctly."""
        linked_at = datetime.now(UTC)
        result = LinkResult(
            success=True,
            task_id="task-123",
            drive_file_id="drive-456",
            drive_file_url="https://drive.google.com/file/d/drive-456",
            linked_at=linked_at,
        )
        assert result.success is True
        assert result.task_id == "task-123"
        assert result.drive_file_id == "drive-456"
        assert result.drive_file_url == "https://drive.google.com/file/d/drive-456"
        assert result.linked_at == linked_at

    def test_error_field(self):
        """Test error field for failed operations."""
        result = LinkResult(
            success=False,
            task_id="task-123",
            error="API connection failed",
        )
        assert result.success is False
        assert result.error == "API connection failed"


class TestTaskInfo:
    """Tests for TaskInfo dataclass."""

    def test_default_values(self):
        """Test default values for task info."""
        info = TaskInfo(page_id="abc", title="Test Task")
        assert info.page_id == "abc"
        assert info.title == "Test Task"
        assert info.drive_file_id is None
        assert info.drive_file_url is None
        assert info.status is None
        assert info.raw_data == {}

    def test_has_drive_link_true(self):
        """Test has_drive_link when drive_file_id set."""
        info = TaskInfo(page_id="abc", title="Test", drive_file_id="xyz")
        assert info.has_drive_link is True

    def test_has_drive_link_false(self):
        """Test has_drive_link when no drive_file_id."""
        info = TaskInfo(page_id="abc", title="Test")
        assert info.has_drive_link is False

    def test_all_fields(self):
        """Test all fields set correctly."""
        raw_data = {"id": "abc", "properties": {}}
        info = TaskInfo(
            page_id="abc",
            title="Research CRM Options",
            drive_file_id="drive-123",
            drive_file_url="https://drive.google.com/file/d/drive-123",
            status="todo",
            raw_data=raw_data,
        )
        assert info.page_id == "abc"
        assert info.title == "Research CRM Options"
        assert info.drive_file_id == "drive-123"
        assert info.drive_file_url == "https://drive.google.com/file/d/drive-123"
        assert info.status == "todo"
        assert info.raw_data == raw_data


class TestDriveTaskLinkerInit:
    """Tests for DriveTaskLinker initialization."""

    def test_init_without_client(self):
        """Test initialization without NotionClient."""
        linker = DriveTaskLinker()
        assert linker._notion is None

    def test_init_with_client(self):
        """Test initialization with NotionClient."""
        mock_client = MagicMock()
        linker = DriveTaskLinker(notion_client=mock_client)
        assert linker._notion is mock_client

    def test_notion_property_creates_client(self):
        """Test notion property creates client when accessed."""
        linker = DriveTaskLinker()
        with patch("assistant.services.drive_task_linker.NotionClient") as mock:
            mock.return_value = MagicMock()
            client = linker.notion
            assert client is not None
            mock.assert_called_once()

    def test_notion_property_reuses_client(self):
        """Test notion property reuses existing client."""
        mock_client = MagicMock()
        linker = DriveTaskLinker(notion_client=mock_client)
        assert linker.notion is mock_client


class TestDriveTaskLinkerLink:
    """Tests for DriveTaskLinker.link method."""

    @pytest.mark.asyncio
    async def test_link_success(self):
        """Test successful linking."""
        mock_client = AsyncMock()
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.link(
            task_id="task-123",
            drive_file_id="drive-456",
            drive_file_url="https://drive.google.com/file/d/drive-456",
        )

        assert result.success is True
        assert result.task_id == "task-123"
        assert result.drive_file_id == "drive-456"
        assert result.drive_file_url == "https://drive.google.com/file/d/drive-456"
        assert result.linked_at is not None
        mock_client.update_task_drive_file.assert_called_once_with(
            page_id="task-123",
            drive_file_id="drive-456",
            drive_file_url="https://drive.google.com/file/d/drive-456",
        )

    @pytest.mark.asyncio
    async def test_link_without_url(self):
        """Test linking without drive_file_url."""
        mock_client = AsyncMock()
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.link(
            task_id="task-123",
            drive_file_id="drive-456",
        )

        assert result.success is True
        assert result.drive_file_url is None
        mock_client.update_task_drive_file.assert_called_once_with(
            page_id="task-123",
            drive_file_id="drive-456",
            drive_file_url=None,
        )

    @pytest.mark.asyncio
    async def test_link_failure(self):
        """Test link failure handling."""
        mock_client = AsyncMock()
        mock_client.update_task_drive_file.side_effect = Exception("API error")
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.link(
            task_id="task-123",
            drive_file_id="drive-456",
        )

        assert result.success is False
        assert result.error == "API error"
        assert result.task_id == "task-123"
        assert result.drive_file_id == "drive-456"


class TestDriveTaskLinkerUnlink:
    """Tests for DriveTaskLinker.unlink method."""

    @pytest.mark.asyncio
    async def test_unlink_success(self):
        """Test successful unlinking."""
        mock_client = AsyncMock()
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.unlink(task_id="task-123")

        assert result.success is True
        assert result.task_id == "task-123"
        mock_client.update_task_drive_file.assert_called_once_with(
            page_id="task-123",
            drive_file_id=None,
            drive_file_url=None,
        )

    @pytest.mark.asyncio
    async def test_unlink_failure(self):
        """Test unlink failure handling."""
        mock_client = AsyncMock()
        mock_client.update_task_drive_file.side_effect = Exception("API error")
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.unlink(task_id="task-123")

        assert result.success is False
        assert result.error == "API error"


class TestDriveTaskLinkerFindTask:
    """Tests for DriveTaskLinker.find_task_by_drive_file method."""

    @pytest.mark.asyncio
    async def test_find_task_found(self):
        """Test finding task by drive file."""
        mock_client = AsyncMock()
        mock_client.query_task_by_drive_file.return_value = {
            "id": "task-123",
            "properties": {
                "title": {"title": [{"plain_text": "Research CRM"}]},
                "drive_file_id": {"rich_text": [{"plain_text": "drive-456"}]},
                "drive_file_url": {"url": "https://drive.google.com/file/d/drive-456"},
                "status": {"select": {"name": "todo"}},
            },
        }
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.find_task_by_drive_file("drive-456")

        assert result is not None
        assert result.page_id == "task-123"
        assert result.title == "Research CRM"
        assert result.drive_file_id == "drive-456"
        assert result.drive_file_url == "https://drive.google.com/file/d/drive-456"
        assert result.status == "todo"

    @pytest.mark.asyncio
    async def test_find_task_not_found(self):
        """Test finding task when not exists."""
        mock_client = AsyncMock()
        mock_client.query_task_by_drive_file.return_value = None
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.find_task_by_drive_file("drive-456")

        assert result is None

    @pytest.mark.asyncio
    async def test_find_task_include_deleted(self):
        """Test finding task including deleted."""
        mock_client = AsyncMock()
        mock_client.query_task_by_drive_file.return_value = {
            "id": "task-123",
            "properties": {
                "title": {"title": [{"plain_text": "Deleted Task"}]},
            },
        }
        linker = DriveTaskLinker(notion_client=mock_client)

        await linker.find_task_by_drive_file("drive-456", include_deleted=True)

        mock_client.query_task_by_drive_file.assert_called_once_with(
            drive_file_id="drive-456",
            include_deleted=True,
        )


class TestDriveTaskLinkerGetTask:
    """Tests for DriveTaskLinker.get_task_with_drive_info method."""

    @pytest.mark.asyncio
    async def test_get_task_found(self):
        """Test getting task with drive info."""
        mock_client = AsyncMock()
        mock_client.get_task.return_value = {
            "id": "task-123",
            "properties": {
                "title": {"title": [{"plain_text": "My Task"}]},
                "drive_file_id": {"rich_text": [{"plain_text": "drive-abc"}]},
            },
        }
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.get_task_with_drive_info("task-123")

        assert result is not None
        assert result.page_id == "task-123"
        assert result.title == "My Task"
        assert result.drive_file_id == "drive-abc"

    @pytest.mark.asyncio
    async def test_get_task_not_found(self):
        """Test getting task when not exists."""
        mock_client = AsyncMock()
        mock_client.get_task.return_value = None
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.get_task_with_drive_info("task-123")

        assert result is None


class TestDriveTaskLinkerChecks:
    """Tests for DriveTaskLinker check methods."""

    @pytest.mark.asyncio
    async def test_is_drive_file_linked_true(self):
        """Test is_drive_file_linked returns True when linked."""
        mock_client = AsyncMock()
        mock_client.query_task_by_drive_file.return_value = {"id": "task-123"}
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.is_drive_file_linked("drive-456")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_drive_file_linked_false(self):
        """Test is_drive_file_linked returns False when not linked."""
        mock_client = AsyncMock()
        mock_client.query_task_by_drive_file.return_value = None
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.is_drive_file_linked("drive-456")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_task_linked_to_drive_true(self):
        """Test is_task_linked_to_drive returns True when linked."""
        mock_client = AsyncMock()
        mock_client.get_task.return_value = {
            "id": "task-123",
            "properties": {
                "title": {"title": []},
                "drive_file_id": {"rich_text": [{"plain_text": "drive-456"}]},
            },
        }
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.is_task_linked_to_drive("task-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_task_linked_to_drive_false_no_id(self):
        """Test is_task_linked_to_drive returns False when no drive_file_id."""
        mock_client = AsyncMock()
        mock_client.get_task.return_value = {
            "id": "task-123",
            "properties": {
                "title": {"title": []},
                "drive_file_id": {"rich_text": []},
            },
        }
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.is_task_linked_to_drive("task-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_task_linked_to_drive_false_no_task(self):
        """Test is_task_linked_to_drive returns False when task not found."""
        mock_client = AsyncMock()
        mock_client.get_task.return_value = None
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.is_task_linked_to_drive("task-123")

        assert result is False


class TestDriveTaskLinkerRelink:
    """Tests for DriveTaskLinker.relink method."""

    @pytest.mark.asyncio
    async def test_relink_success(self):
        """Test relinking to a new drive file."""
        mock_client = AsyncMock()
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.relink(
            task_id="task-123",
            new_drive_file_id="new-drive-789",
            new_drive_file_url="https://drive.google.com/file/d/new-drive-789",
        )

        assert result.success is True
        assert result.drive_file_id == "new-drive-789"
        mock_client.update_task_drive_file.assert_called_once()


class TestExtractTaskInfo:
    """Tests for DriveTaskLinker._extract_task_info method."""

    def test_extract_full_info(self):
        """Test extracting all fields from Notion result."""
        linker = DriveTaskLinker()
        notion_result = {
            "id": "page-123",
            "properties": {
                "title": {"title": [{"plain_text": "Test "}, {"plain_text": "Task"}]},
                "drive_file_id": {"rich_text": [{"plain_text": "drive-abc"}]},
                "drive_file_url": {"url": "https://drive.google.com/file/d/drive-abc"},
                "status": {"select": {"name": "doing"}},
            },
        }

        result = linker._extract_task_info(notion_result)

        assert result.page_id == "page-123"
        assert result.title == "Test Task"
        assert result.drive_file_id == "drive-abc"
        assert result.drive_file_url == "https://drive.google.com/file/d/drive-abc"
        assert result.status == "doing"
        assert result.raw_data == notion_result

    def test_extract_empty_title(self):
        """Test extracting with empty title."""
        linker = DriveTaskLinker()
        notion_result = {
            "id": "page-123",
            "properties": {
                "title": {"title": []},
            },
        }

        result = linker._extract_task_info(notion_result)

        assert result.title == ""

    def test_extract_no_drive_fields(self):
        """Test extracting without drive fields."""
        linker = DriveTaskLinker()
        notion_result = {
            "id": "page-123",
            "properties": {
                "title": {"title": [{"plain_text": "Task"}]},
            },
        }

        result = linker._extract_task_info(notion_result)

        assert result.drive_file_id is None
        assert result.drive_file_url is None

    def test_extract_empty_drive_file_id(self):
        """Test extracting with empty drive_file_id rich_text."""
        linker = DriveTaskLinker()
        notion_result = {
            "id": "page-123",
            "properties": {
                "title": {"title": [{"plain_text": "Task"}]},
                "drive_file_id": {"rich_text": []},
            },
        }

        result = linker._extract_task_info(notion_result)

        assert result.drive_file_id is None


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_drive_task_linker_singleton(self):
        """Test singleton pattern."""
        with patch("assistant.services.drive_task_linker._linker", None):
            linker1 = get_drive_task_linker()
            linker2 = get_drive_task_linker()
            assert linker1 is linker2

    @pytest.mark.asyncio
    async def test_link_drive_to_task_function(self):
        """Test link_drive_to_task convenience function."""
        with patch("assistant.services.drive_task_linker.get_drive_task_linker") as mock_get:
            mock_linker = AsyncMock()
            mock_linker.link.return_value = LinkResult(success=True)
            mock_get.return_value = mock_linker

            result = await link_drive_to_task(
                task_id="task-123",
                drive_file_id="drive-456",
            )

            assert result.success is True
            mock_linker.link.assert_called_once_with("task-123", "drive-456", None)

    @pytest.mark.asyncio
    async def test_find_task_by_drive_file_function(self):
        """Test find_task_by_drive_file convenience function."""
        with patch("assistant.services.drive_task_linker.get_drive_task_linker") as mock_get:
            mock_linker = AsyncMock()
            mock_linker.find_task_by_drive_file.return_value = TaskInfo(
                page_id="task-123",
                title="Test",
            )
            mock_get.return_value = mock_linker

            result = await find_task_by_drive_file("drive-456")

            assert result is not None
            assert result.page_id == "task-123"

    @pytest.mark.asyncio
    async def test_is_drive_file_linked_function(self):
        """Test is_drive_file_linked convenience function."""
        with patch("assistant.services.drive_task_linker.get_drive_task_linker") as mock_get:
            mock_linker = AsyncMock()
            mock_linker.is_drive_file_linked.return_value = True
            mock_get.return_value = mock_linker

            result = await is_drive_file_linked("drive-456")

            assert result is True

    @pytest.mark.asyncio
    async def test_unlink_drive_from_task_function(self):
        """Test unlink_drive_from_task convenience function."""
        with patch("assistant.services.drive_task_linker.get_drive_task_linker") as mock_get:
            mock_linker = AsyncMock()
            mock_linker.unlink.return_value = LinkResult(success=True)
            mock_get.return_value = mock_linker

            result = await unlink_drive_from_task("task-123")

            assert result.success is True


class TestT167BidirectionalLinking:
    """Acceptance tests for T-167: Bidirectional Drive-Task linking."""

    @pytest.mark.asyncio
    async def test_forward_link_task_to_drive(self):
        """Test forward link: Task -> Drive file.

        Given: A Notion task exists
        When: We link a Drive file to it
        Then: Task.drive_file_id and drive_file_url are populated
        """
        mock_client = AsyncMock()
        linker = DriveTaskLinker(notion_client=mock_client)

        result = await linker.link(
            task_id="notion-task-id",
            drive_file_id="google-drive-file-id",
            drive_file_url="https://docs.google.com/document/d/google-drive-file-id",
        )

        # Forward link created
        assert result.success is True
        assert result.drive_file_id == "google-drive-file-id"
        mock_client.update_task_drive_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_reverse_lookup_drive_to_task(self):
        """Test reverse lookup: Drive file -> Task.

        Given: A Drive file is linked to a task
        When: We search by drive_file_id
        Then: We find the linked task
        """
        mock_client = AsyncMock()
        mock_client.query_task_by_drive_file.return_value = {
            "id": "notion-task-id",
            "properties": {
                "title": {"title": [{"plain_text": "Research Report"}]},
                "drive_file_id": {"rich_text": [{"plain_text": "google-drive-file-id"}]},
                "drive_file_url": {
                    "url": "https://docs.google.com/document/d/google-drive-file-id"
                },
                "status": {"select": {"name": "todo"}},
            },
        }
        linker = DriveTaskLinker(notion_client=mock_client)

        # Reverse lookup
        task = await linker.find_task_by_drive_file("google-drive-file-id")

        assert task is not None
        assert task.page_id == "notion-task-id"
        assert task.drive_file_id == "google-drive-file-id"
        assert task.title == "Research Report"

    @pytest.mark.asyncio
    async def test_full_bidirectional_workflow(self):
        """Test full bidirectional workflow.

        This tests the complete cycle of:
        1. Creating a link (forward)
        2. Looking up by Drive ID (reverse)
        3. Verifying link exists
        4. Unlinking
        5. Verifying link removed
        """
        mock_client = AsyncMock()
        linker = DriveTaskLinker(notion_client=mock_client)

        # Step 1: Create forward link
        link_result = await linker.link(
            task_id="task-123",
            drive_file_id="drive-456",
            drive_file_url="https://drive.google.com/file/d/drive-456",
        )
        assert link_result.success is True

        # Step 2: Reverse lookup
        mock_client.query_task_by_drive_file.return_value = {
            "id": "task-123",
            "properties": {
                "title": {"title": [{"plain_text": "Linked Task"}]},
                "drive_file_id": {"rich_text": [{"plain_text": "drive-456"}]},
            },
        }
        found_task = await linker.find_task_by_drive_file("drive-456")
        assert found_task is not None
        assert found_task.page_id == "task-123"

        # Step 3: Verify link exists
        is_linked = await linker.is_drive_file_linked("drive-456")
        assert is_linked is True

        # Step 4: Unlink
        unlink_result = await linker.unlink("task-123")
        assert unlink_result.success is True

        # Step 5: Verify link removed
        mock_client.query_task_by_drive_file.return_value = None
        is_linked_after = await linker.is_drive_file_linked("drive-456")
        assert is_linked_after is False

    @pytest.mark.asyncio
    async def test_integration_with_research_pipeline(self):
        """Test integration scenario with research pipeline.

        When research pipeline creates a Drive doc:
        1. Drive doc is created
        2. Task is created with drive_file_id
        3. Reverse lookup finds the task
        """
        mock_client = AsyncMock()

        # Simulate: Research pipeline created task with drive link
        mock_client.query_task_by_drive_file.return_value = {
            "id": "research-task-id",
            "properties": {
                "title": {"title": [{"plain_text": "Research: CRM Options"}]},
                "drive_file_id": {"rich_text": [{"plain_text": "research-doc-123"}]},
                "drive_file_url": {
                    "url": "https://docs.google.com/document/d/research-doc-123"
                },
                "status": {"select": {"name": "todo"}},
            },
        }
        linker = DriveTaskLinker(notion_client=mock_client)

        # Reverse lookup should find the research task
        task = await linker.find_task_by_drive_file("research-doc-123")

        assert task is not None
        assert task.title == "Research: CRM Options"
        assert task.drive_file_id == "research-doc-123"
        assert task.has_drive_link is True


class TestNotionClientMethods:
    """Tests for NotionClient methods added for T-167."""

    @pytest.mark.asyncio
    async def test_query_task_by_drive_file_returns_task(self):
        """Test query_task_by_drive_file finds a task."""
        from assistant.notion.client import NotionClient

        client = NotionClient()
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {
                "results": [{"id": "task-123", "properties": {}}]
            }

            result = await client.query_task_by_drive_file("drive-456")

            assert result is not None
            assert result["id"] == "task-123"

    @pytest.mark.asyncio
    async def test_query_task_by_drive_file_returns_none(self):
        """Test query_task_by_drive_file returns None when not found."""
        from assistant.notion.client import NotionClient

        client = NotionClient()
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {"results": []}

            result = await client.query_task_by_drive_file("drive-456")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_task_returns_task(self):
        """Test get_task retrieves a task."""
        from assistant.notion.client import NotionClient

        client = NotionClient()
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {"id": "task-123", "properties": {}}

            result = await client.get_task("task-123")

            assert result is not None
            assert result["id"] == "task-123"

    @pytest.mark.asyncio
    async def test_get_task_returns_none_on_error(self):
        """Test get_task returns None on error."""
        from assistant.notion.client import NotionClient

        client = NotionClient()
        with patch.object(client, "_request") as mock_request:
            mock_request.side_effect = Exception("Not found")

            result = await client.get_task("task-123")

            assert result is None
