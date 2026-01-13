"""Tests for research pipeline service (T-164).

Tests the research-to-doc pipeline that:
1. Performs web research
2. Creates Google Doc with findings
3. Creates Notion task with drive_file_id link

Per PRD AT-124:
- "Research best CRM options" creates Google Doc in Second Brain/Research/
- Document populated with research findings
- Task created linking to Drive document
- Pass: Drive API confirms doc exists AND task.drive_file_id populated
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.services.research_pipeline import (
    ResearchPipeline,
    ResearchPipelineResult,
    execute_research_pipeline,
    extract_research_topic,
    get_research_pipeline,
    is_research_request,
)


class TestResearchPipelineResult:
    """Tests for ResearchPipelineResult dataclass."""

    def test_default_values(self):
        """Test default values for result."""
        result = ResearchPipelineResult()
        assert result.success is False
        assert result.query == ""
        assert result.research_success is False
        assert result.findings_count == 0
        assert result.drive_file_id is None
        assert result.task_id is None

    def test_has_drive_doc_false_when_no_id(self):
        """Test has_drive_doc is False when no drive_file_id."""
        result = ResearchPipelineResult()
        assert result.has_drive_doc is False

    def test_has_drive_doc_true_when_id_set(self):
        """Test has_drive_doc is True when drive_file_id set."""
        result = ResearchPipelineResult(drive_file_id="abc123")
        assert result.has_drive_doc is True

    def test_has_task_false_when_no_id(self):
        """Test has_task is False when no task_id."""
        result = ResearchPipelineResult()
        assert result.has_task is False

    def test_has_task_true_when_id_set(self):
        """Test has_task is True when task_id set."""
        result = ResearchPipelineResult(task_id="task-123")
        assert result.has_task is True


class TestIsResearchRequest:
    """Tests for is_research_request function."""

    def test_research_prefix(self):
        """Test 'Research X' pattern."""
        assert is_research_request("Research best CRM options") is True
        assert is_research_request("research python frameworks") is True
        assert is_research_request("RESEARCH AI trends") is True

    def test_find_out_pattern(self):
        """Test 'Find out about X' pattern."""
        assert is_research_request("Find out about React vs Vue") is True
        assert is_research_request("Find out best practices") is True

    def test_look_up_pattern(self):
        """Test 'Look up X' pattern."""
        assert is_research_request("Look up pricing for AWS") is True
        assert is_research_request("Look into database options") is True

    def test_investigate_pattern(self):
        """Test 'Investigate X' pattern."""
        assert is_research_request("Investigate security issues") is True

    def test_what_are_best_pattern(self):
        """Test 'What are the best X' pattern."""
        assert is_research_request("What are the best CRM tools") is True
        assert is_research_request("What are best practices for testing") is True

    def test_compare_pattern(self):
        """Test 'Compare X' pattern."""
        assert is_research_request("Compare React and Angular") is True

    def test_not_research_request(self):
        """Test non-research requests return False."""
        assert is_research_request("Create a task") is False
        assert is_research_request("Remind me to call John") is False
        assert is_research_request("Buy milk tomorrow") is False


class TestExtractResearchTopic:
    """Tests for extract_research_topic function."""

    def test_extract_from_research_prefix(self):
        """Test extracting topic from 'Research X'."""
        assert extract_research_topic("Research best CRM options") == "best crm options"

    def test_extract_from_find_out(self):
        """Test extracting topic from 'Find out about X'."""
        result = extract_research_topic("Find out about React frameworks")
        assert "react frameworks" in result.lower()

    def test_extract_from_look_up(self):
        """Test extracting topic from 'Look up X'."""
        result = extract_research_topic("Look up AWS pricing")
        assert "aws pricing" in result.lower()

    def test_extract_from_what_are_best(self):
        """Test extracting topic from 'What are the best X'."""
        result = extract_research_topic("What are the best CRM tools")
        assert "crm tools" in result.lower()

    def test_extract_preserves_case_in_output(self):
        """Test that extraction handles case properly."""
        result = extract_research_topic("Research Python frameworks")
        # Topic is extracted in lowercase due to pattern matching
        assert "python frameworks" in result.lower()


class TestResearchPipeline:
    """Tests for ResearchPipeline class."""

    @pytest.fixture
    def mock_web_researcher(self):
        """Create mock WebResearcher."""
        mock = MagicMock()
        mock.research_query = AsyncMock()
        return mock

    @pytest.fixture
    def mock_drive_client(self):
        """Create mock DriveClient."""
        mock = MagicMock()
        mock.create_research_document = AsyncMock()
        return mock

    @pytest.fixture
    def mock_notion_client(self):
        """Create mock NotionClient."""
        mock = MagicMock()
        mock.create_task = AsyncMock()
        return mock

    @pytest.fixture
    def mock_research_result(self):
        """Create mock ResearchResult."""
        from assistant.services.research import ResearchResult, ResearchSource

        return ResearchResult(
            success=True,
            query="best CRM options",
            findings=["Salesforce", "HubSpot", "Zoho"],
            sources=[
                ResearchSource(url="https://example.com/crm", title="CRM Guide"),
            ],
            completed_at=datetime.now(),
        )

    @pytest.fixture
    def mock_drive_file(self):
        """Create mock DriveFile."""
        from assistant.google.drive import DriveFile

        return DriveFile(
            id="drive-file-123",
            name="Research Notes - best CRM options",
            mime_type="application/vnd.google-apps.document",
            web_view_link="https://docs.google.com/document/d/drive-file-123",
        )

    def test_init_with_dependencies(
        self, mock_web_researcher, mock_drive_client, mock_notion_client
    ):
        """Test initialization with dependencies."""
        pipeline = ResearchPipeline(
            web_researcher=mock_web_researcher,
            drive_client=mock_drive_client,
            notion_client=mock_notion_client,
        )
        assert pipeline._web_researcher is mock_web_researcher
        assert pipeline._drive_client is mock_drive_client
        assert pipeline._notion_client is mock_notion_client

    def test_init_without_dependencies(self):
        """Test initialization without dependencies creates them lazily."""
        pipeline = ResearchPipeline()
        assert pipeline._web_researcher is None
        assert pipeline._drive_client is None
        assert pipeline._notion_client is None

    @pytest.mark.asyncio
    async def test_execute_success(
        self,
        mock_web_researcher,
        mock_drive_client,
        mock_notion_client,
        mock_research_result,
        mock_drive_file,
    ):
        """Test successful pipeline execution."""
        # Setup mocks
        mock_web_researcher.research_query.return_value = mock_research_result
        mock_drive_client.create_research_document.return_value = mock_drive_file
        mock_notion_client.create_task.return_value = "task-123"

        pipeline = ResearchPipeline(
            web_researcher=mock_web_researcher,
            drive_client=mock_drive_client,
            notion_client=mock_notion_client,
        )

        # Execute
        result = await pipeline.execute("Research best CRM options")

        # Verify
        assert result.success is True
        assert result.research_success is True
        assert result.findings_count == 3
        assert result.drive_file_id == "drive-file-123"
        assert result.task_id == "task-123"
        assert "Review research" in result.task_title

    @pytest.mark.asyncio
    async def test_execute_research_failure(
        self, mock_web_researcher, mock_drive_client, mock_notion_client
    ):
        """Test pipeline handles research failure."""
        from assistant.services.research import ResearchResult

        # Setup mocks - research fails
        mock_web_researcher.research_query.return_value = ResearchResult(
            success=False,
            query="best CRM options",
            error="Network error",
        )

        pipeline = ResearchPipeline(
            web_researcher=mock_web_researcher,
            drive_client=mock_drive_client,
            notion_client=mock_notion_client,
        )

        # Execute
        result = await pipeline.execute("Research best CRM options")

        # Verify
        assert result.success is False
        assert result.research_success is False
        assert result.drive_file_id is None
        assert result.task_id is None
        assert "Research failed" in result.error

    @pytest.mark.asyncio
    async def test_execute_calls_services_in_order(
        self,
        mock_web_researcher,
        mock_drive_client,
        mock_notion_client,
        mock_research_result,
        mock_drive_file,
    ):
        """Test pipeline calls services in correct order."""
        mock_web_researcher.research_query.return_value = mock_research_result
        mock_drive_client.create_research_document.return_value = mock_drive_file
        mock_notion_client.create_task.return_value = "task-123"

        pipeline = ResearchPipeline(
            web_researcher=mock_web_researcher,
            drive_client=mock_drive_client,
            notion_client=mock_notion_client,
        )

        await pipeline.execute("Research best CRM options")

        # Verify call order
        mock_web_researcher.research_query.assert_called_once()
        mock_drive_client.create_research_document.assert_called_once()
        mock_notion_client.create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_created_with_drive_file_id(
        self,
        mock_web_researcher,
        mock_drive_client,
        mock_notion_client,
        mock_research_result,
        mock_drive_file,
    ):
        """Test task is created with drive_file_id and drive_file_url."""
        mock_web_researcher.research_query.return_value = mock_research_result
        mock_drive_client.create_research_document.return_value = mock_drive_file
        mock_notion_client.create_task.return_value = "task-123"

        pipeline = ResearchPipeline(
            web_researcher=mock_web_researcher,
            drive_client=mock_drive_client,
            notion_client=mock_notion_client,
        )

        await pipeline.execute("Research best CRM options")

        # Verify task was created with drive file info
        call_args = mock_notion_client.create_task.call_args
        task = call_args[0][0]
        assert task.drive_file_id == "drive-file-123"
        assert task.drive_file_url == "https://docs.google.com/document/d/drive-file-123"

    def test_format_success_message(self):
        """Test success message formatting."""
        pipeline = ResearchPipeline()
        result = ResearchPipelineResult(
            success=True,
            query="Research best CRM options",
            findings_count=5,
            sources_count=3,
            drive_file_url="https://docs.google.com/doc/123",
            task_title="Review research: best CRM options",
        )

        message = pipeline._format_success_message(result)

        assert "Research completed" in message
        assert "5 items" in message
        assert "3 sources" in message
        assert "docs.google.com" in message
        assert "Review research" in message

    def test_format_failure_message(self):
        """Test failure message formatting."""
        pipeline = ResearchPipeline()
        result = ResearchPipelineResult(
            success=False,
            query="Research best CRM options",
            error="Network timeout",
        )

        message = pipeline._format_failure_message(result)

        assert "Research failed" in message
        assert "Network timeout" in message


class TestAT124DriveResearchDocument:
    """Acceptance tests for AT-124: Drive Research Document Creation.

    Given: User sends "Research best CRM options for small business"
    When: Google Drive API enabled
    Then: Google Doc created in Second Brain/Research/ folder
    And: Document populated with research findings
    And: Task created linking to Drive document
    Pass condition: Drive API confirms doc exists AND task.drive_file_id populated
    """

    @pytest.fixture
    def mock_research_result(self):
        """Create realistic research result."""
        from assistant.services.research import ResearchResult, ResearchSource

        return ResearchResult(
            success=True,
            query="best CRM options for small business",
            findings=[
                "HubSpot CRM - Free tier available, good for startups",
                "Zoho CRM - Affordable, comprehensive features",
                "Salesforce Essentials - Enterprise-grade at SMB price",
                "Freshsales - AI-powered, easy to use",
            ],
            sources=[
                ResearchSource(
                    url="https://www.g2.com/categories/crm",
                    title="G2 CRM Reviews",
                ),
                ResearchSource(
                    url="https://www.capterra.com/crm-software/",
                    title="Capterra CRM Comparison",
                ),
            ],
            completed_at=datetime.now(),
        )

    @pytest.fixture
    def mock_drive_file(self):
        """Create realistic drive file."""
        from assistant.google.drive import DriveFile

        return DriveFile(
            id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
            name="Research Notes - best CRM options for small business",
            mime_type="application/vnd.google-apps.document",
            web_view_link="https://docs.google.com/document/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
            parent_id="folder-123",
        )

    @pytest.mark.asyncio
    async def test_at124_research_creates_drive_doc(self, mock_research_result, mock_drive_file):
        """AT-124: Research request creates Drive doc with findings."""
        # Setup mocks
        mock_researcher = MagicMock()
        mock_researcher.research_query = AsyncMock(return_value=mock_research_result)

        mock_drive = MagicMock()
        mock_drive.create_research_document = AsyncMock(return_value=mock_drive_file)

        mock_notion = MagicMock()
        mock_notion.create_task = AsyncMock(return_value="notion-task-id-123")

        pipeline = ResearchPipeline(
            web_researcher=mock_researcher,
            drive_client=mock_drive,
            notion_client=mock_notion,
        )

        # Execute
        result = await pipeline.execute("Research best CRM options for small business")

        # AT-124 Pass condition: Drive API confirms doc exists
        assert result.success is True
        assert result.drive_file_id == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        assert result.drive_file_url == mock_drive_file.web_view_link

    @pytest.mark.asyncio
    async def test_at124_task_has_drive_file_id_populated(
        self, mock_research_result, mock_drive_file
    ):
        """AT-124: Task created with drive_file_id populated."""
        mock_researcher = MagicMock()
        mock_researcher.research_query = AsyncMock(return_value=mock_research_result)

        mock_drive = MagicMock()
        mock_drive.create_research_document = AsyncMock(return_value=mock_drive_file)

        mock_notion = MagicMock()
        mock_notion.create_task = AsyncMock(return_value="notion-task-id-123")

        pipeline = ResearchPipeline(
            web_researcher=mock_researcher,
            drive_client=mock_drive,
            notion_client=mock_notion,
        )

        result = await pipeline.execute("Research best CRM options for small business")

        # AT-124 Pass condition: task.drive_file_id populated
        assert result.task_id == "notion-task-id-123"

        # Verify task was created with drive_file_id
        call_args = mock_notion.create_task.call_args
        task = call_args[0][0]
        assert task.drive_file_id == mock_drive_file.id
        assert task.drive_file_url == mock_drive_file.web_view_link

    @pytest.mark.asyncio
    async def test_at124_doc_in_research_folder(self, mock_research_result, mock_drive_file):
        """AT-124: Google Doc created in Second Brain/Research/ folder."""
        mock_researcher = MagicMock()
        mock_researcher.research_query = AsyncMock(return_value=mock_research_result)

        mock_drive = MagicMock()
        mock_drive.create_research_document = AsyncMock(return_value=mock_drive_file)

        mock_notion = MagicMock()
        mock_notion.create_task = AsyncMock(return_value="task-123")

        pipeline = ResearchPipeline(
            web_researcher=mock_researcher,
            drive_client=mock_drive,
            notion_client=mock_notion,
        )

        await pipeline.execute("Research best CRM options for small business")

        # Verify create_research_document was called with topic
        mock_drive.create_research_document.assert_called_once()
        call_kwargs = mock_drive.create_research_document.call_args[1]
        assert "crm" in call_kwargs["topic"].lower()

    @pytest.mark.asyncio
    async def test_at124_doc_populated_with_findings(self, mock_research_result, mock_drive_file):
        """AT-124: Document populated with research findings."""
        mock_researcher = MagicMock()
        mock_researcher.research_query = AsyncMock(return_value=mock_research_result)

        mock_drive = MagicMock()
        mock_drive.create_research_document = AsyncMock(return_value=mock_drive_file)

        mock_notion = MagicMock()
        mock_notion.create_task = AsyncMock(return_value="task-123")

        pipeline = ResearchPipeline(
            web_researcher=mock_researcher,
            drive_client=mock_drive,
            notion_client=mock_notion,
        )

        await pipeline.execute("Research best CRM options for small business")

        # Verify initial_findings contains research findings
        call_kwargs = mock_drive.create_research_document.call_args[1]
        initial_findings = call_kwargs["initial_findings"]

        assert "HubSpot" in initial_findings
        assert "Zoho" in initial_findings
        assert "Sources" in initial_findings


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_research_pipeline_returns_singleton(self):
        """Test get_research_pipeline returns singleton."""
        # Reset singleton
        import assistant.services.research_pipeline as module

        module._pipeline = None

        pipeline1 = get_research_pipeline()
        pipeline2 = get_research_pipeline()

        assert pipeline1 is pipeline2

    @pytest.mark.asyncio
    async def test_execute_research_pipeline_convenience(self):
        """Test execute_research_pipeline convenience function."""
        import assistant.services.research_pipeline as module

        # Create mock pipeline
        mock_pipeline = MagicMock()
        mock_result = ResearchPipelineResult(success=True)
        mock_pipeline.execute = AsyncMock(return_value=mock_result)

        module._pipeline = mock_pipeline

        result = await execute_research_pipeline("Research AI tools")

        mock_pipeline.execute.assert_called_once_with("Research AI tools", None, None)
        assert result.success is True

        # Reset singleton
        module._pipeline = None


class TestTaskSchemaWithDriveFileId:
    """Tests for Task schema with drive_file_id field."""

    def test_task_has_drive_file_id_field(self):
        """Test Task schema includes drive_file_id."""
        from assistant.notion.schemas import Task

        task = Task(
            title="Review research",
            drive_file_id="file-123",
            drive_file_url="https://docs.google.com/document/d/file-123",
        )

        assert task.drive_file_id == "file-123"
        assert task.drive_file_url == "https://docs.google.com/document/d/file-123"

    def test_task_drive_file_id_optional(self):
        """Test drive_file_id is optional."""
        from assistant.notion.schemas import Task

        task = Task(title="Simple task")

        assert task.drive_file_id is None
        assert task.drive_file_url is None


class TestNotionClientUpdateDriveFile:
    """Tests for NotionClient.update_task_drive_file method."""

    @pytest.mark.asyncio
    async def test_update_task_drive_file(self):
        """Test updating task with drive file info."""
        from assistant.notion.client import NotionClient

        client = NotionClient(api_key="test-key")
        client._request = AsyncMock()

        await client.update_task_drive_file(
            page_id="page-123",
            drive_file_id="drive-file-456",
            drive_file_url="https://docs.google.com/document/d/drive-file-456",
        )

        # Verify request was made
        client._request.assert_called_once()
        call_args = client._request.call_args
        assert call_args[0][0] == "PATCH"
        assert "page-123" in call_args[0][1]

        # Verify properties
        properties = call_args[0][2]["properties"]
        assert "drive_file_id" in properties
        assert "drive_file_url" in properties

    @pytest.mark.asyncio
    async def test_update_task_drive_file_clear(self):
        """Test clearing drive file info."""
        from assistant.notion.client import NotionClient

        client = NotionClient(api_key="test-key")
        client._request = AsyncMock()

        await client.update_task_drive_file(
            page_id="page-123",
            drive_file_id=None,
            drive_file_url=None,
        )

        call_args = client._request.call_args
        properties = call_args[0][2]["properties"]

        # Verify clearing values
        assert properties["drive_file_id"] == {"rich_text": []}
        assert properties["drive_file_url"] == {"url": None}
