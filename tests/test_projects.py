"""Tests for the Projects service.

Covers T-072: Implement Projects lookup/create service
- Look up existing projects by name or context
- Create new entries when needed
- Handle disambiguation for similar projects
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import pytest

from assistant.services.projects import (
    ProjectsService,
    ProjectMatch,
    ProjectLookupResult,
    ProjectStatus,
    ProjectType,
    STATUS_PRIORITY,
    get_projects_service,
    lookup_project,
    lookup_or_create_project,
    create_project,
    lookup_active_projects,
)
from assistant.notion.schemas import Project


class TestProjectMatch:
    """Tests for ProjectMatch dataclass."""

    def test_sort_by_confidence_descending(self):
        """Higher confidence should sort first."""
        match1 = ProjectMatch(project_id="1", name="Project A", confidence=0.8)
        match2 = ProjectMatch(project_id="2", name="Project B", confidence=0.9)

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Project B"  # 0.9 confidence
        assert sorted_matches[1].name == "Project A"  # 0.8 confidence

    def test_sort_active_before_inactive_when_same_confidence(self):
        """When confidence is equal, active projects sort first."""
        match1 = ProjectMatch(
            project_id="1",
            name="Project A",
            confidence=0.8,
            status="paused",
        )
        match2 = ProjectMatch(
            project_id="2",
            name="Project B",
            confidence=0.8,
            status="active",
        )

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Project B"  # Active status

    def test_sort_by_deadline_when_same_confidence_and_status(self):
        """When confidence and active status equal, sooner deadline sorts first."""
        now = datetime.now()
        match1 = ProjectMatch(
            project_id="1",
            name="Project A",
            confidence=0.8,
            status="active",
            deadline=now + timedelta(days=30),
        )
        match2 = ProjectMatch(
            project_id="2",
            name="Project B",
            confidence=0.8,
            status="active",
            deadline=now + timedelta(days=7),
        )

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Project B"  # Sooner deadline

    def test_having_deadline_beats_not_having(self):
        """Having deadline is better than not having one."""
        match1 = ProjectMatch(
            project_id="1", name="Project A", confidence=0.8, status="active"
        )
        match2 = ProjectMatch(
            project_id="2",
            name="Project B",
            confidence=0.8,
            status="active",
            deadline=datetime.now() + timedelta(days=30),
        )

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Project B"  # Has deadline


class TestProjectLookupResult:
    """Tests for ProjectLookupResult dataclass."""

    def test_has_single_match_true(self):
        """has_single_match should be True for exactly one match."""
        result = ProjectLookupResult(
            found=True,
            project_id="123",
            matches=[ProjectMatch(project_id="123", name="Website Redesign", confidence=1.0)],
        )
        assert result.has_single_match is True

    def test_has_single_match_false_when_multiple(self):
        """has_single_match should be False for multiple matches."""
        result = ProjectLookupResult(
            found=True,
            project_id="123",
            matches=[
                ProjectMatch(project_id="123", name="Website v1", confidence=0.9),
                ProjectMatch(project_id="456", name="Website v2", confidence=0.7),
            ],
        )
        assert result.has_single_match is False

    def test_has_single_match_false_when_not_found(self):
        """has_single_match should be False when not found."""
        result = ProjectLookupResult(found=False)
        assert result.has_single_match is False


class TestProjectsService:
    """Tests for ProjectsService class."""

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock Notion client."""
        client = AsyncMock()
        client.query_projects = AsyncMock(return_value=[])
        client.create_project = AsyncMock(return_value="new-project-id")
        return client

    @pytest.fixture
    def service(self, mock_notion_client):
        """Create a ProjectsService with mocked client."""
        return ProjectsService(mock_notion_client)

    # -------------------------------------------
    # Lookup Tests
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_finds_existing_project_by_name(self, service, mock_notion_client):
        """When project exists, lookup returns the match."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "website-id-123",
                "properties": {
                    "name": {"title": [{"text": {"content": "Website Redesign"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": {"name": "work"}},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": [{"text": {"content": "Review mockups"}}]},
                },
            }
        ]

        result = await service.lookup("Website")

        assert result.found is True
        assert result.project_id == "website-id-123"
        assert len(result.matches) == 1
        assert result.matches[0].name == "Website Redesign"
        assert result.needs_disambiguation is False

    @pytest.mark.asyncio
    async def test_lookup_filters_by_status(self, service, mock_notion_client):
        """Lookup can filter by project status."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "active-project-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Active Project"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        result = await service.lookup("Active", status="active")

        assert result.found is True
        mock_notion_client.query_projects.assert_called_once_with(
            name="Active", status="active"
        )

    @pytest.mark.asyncio
    async def test_lookup_returns_not_found_when_no_match(self, service, mock_notion_client):
        """When no matches, lookup returns not found."""
        mock_notion_client.query_projects.return_value = []

        result = await service.lookup("Nonexistent Project")

        assert result.found is False
        assert result.project_id is None
        assert len(result.matches) == 0

    @pytest.mark.asyncio
    async def test_lookup_exact_name_match_high_confidence(self, service, mock_notion_client):
        """Exact name match should have confidence 1.0."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "website-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Website"}}]},
                    "status": {"select": None},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        result = await service.lookup("Website")

        assert result.matches[0].confidence >= 0.99  # 1.0 + possible boost

    @pytest.mark.asyncio
    async def test_lookup_partial_name_match_lower_confidence(self, service, mock_notion_client):
        """Partial name match should have lower confidence."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "project-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Website Redesign Project"}}]},
                    "status": {"select": None},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        result = await service.lookup("Website")

        # Name starts with search term, should be ~0.9
        assert 0.85 <= result.matches[0].confidence <= 0.95

    @pytest.mark.asyncio
    async def test_lookup_word_boundary_match(self, service, mock_notion_client):
        """Can match if search appears as a word in the name."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "project-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Q4 Marketing Campaign"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        result = await service.lookup("Marketing")

        assert result.found is True
        # Contains search term, should be ~0.7
        assert result.matches[0].confidence >= 0.6

    # -------------------------------------------
    # Create Tests
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_or_create_creates_when_not_found(self, service, mock_notion_client):
        """When project not found, create new entry."""
        mock_notion_client.query_projects.return_value = []

        result = await service.lookup_or_create("New Project")

        assert result.found is True
        assert result.is_new is True
        mock_notion_client.create_project.assert_called_once()
        # Verify the project object was passed
        call_args = mock_notion_client.create_project.call_args
        project = call_args[0][0]
        assert project.name == "New Project"

    @pytest.mark.asyncio
    async def test_lookup_or_create_with_type_and_context(self, service, mock_notion_client):
        """Created project should have type and context set."""
        mock_notion_client.query_projects.return_value = []

        result = await service.lookup_or_create(
            "Client Website",
            project_type="work",
            context="Website redesign for XYZ Corp",
        )

        assert result.is_new is True
        call_args = mock_notion_client.create_project.call_args
        project = call_args[0][0]
        assert project.name == "Client Website"
        assert project.project_type == "work"
        assert project.context == "Website redesign for XYZ Corp"
        assert project.status == "active"  # Default status

    @pytest.mark.asyncio
    async def test_lookup_or_create_returns_existing_when_found(self, service, mock_notion_client):
        """When project exists, lookup_or_create returns existing."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "existing-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Existing Project"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": {"name": "personal"}},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        result = await service.lookup_or_create("Existing Project")

        assert result.found is True
        assert result.is_new is False
        assert result.project_id == "existing-id"
        mock_notion_client.create_project.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_project(self, service, mock_notion_client):
        """create() should create a new project in Notion."""
        project = await service.create(
            "New Website", "work", "Client project for ABC Inc"
        )

        assert project.name == "New Website"
        assert project.project_type == "work"
        assert project.context == "Client project for ABC Inc"
        assert project.status == "active"
        assert project.id == "new-project-id"
        mock_notion_client.create_project.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_project_defaults_to_personal_type(self, service, mock_notion_client):
        """create() should default to 'personal' type when not specified."""
        project = await service.create("Side Project")

        assert project.project_type == "personal"

    @pytest.mark.asyncio
    async def test_create_project_with_deadline(self, service, mock_notion_client):
        """create() should support setting a deadline."""
        deadline = datetime.now() + timedelta(days=30)
        project = await service.create(
            "Q1 Goals", "work", deadline=deadline
        )

        assert project.name == "Q1 Goals"
        assert project.deadline == deadline

    # -------------------------------------------
    # Disambiguation Tests
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_disambiguation_required_for_multiple_similar_matches(
        self, service, mock_notion_client
    ):
        """Multiple projects with similar confidence and no active status trigger disambiguation."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "website-1-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Old Website Project"}}]},
                    "status": {"select": {"name": "completed"}},
                    "project_type": {"select": {"name": "work"}},
                    "deadline": {"date": {"start": "2023-12-31T00:00:00Z"}},
                    "next_action": {"rich_text": []},
                },
            },
            {
                "id": "website-2-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "New Website Project"}}]},
                    "status": {"select": {"name": "paused"}},
                    "project_type": {"select": {"name": "work"}},
                    "deadline": {"date": {"start": "2024-06-30T00:00:00Z"}},
                    "next_action": {"rich_text": []},
                },
            },
        ]

        # Searching for "Website" - contains match (~0.7) for both, neither active
        result = await service.lookup("Website")

        assert result.found is True
        assert len(result.matches) == 2
        # With partial matches (~0.7) and no active project, disambiguation should be triggered
        assert result.needs_disambiguation is True

    @pytest.mark.asyncio
    async def test_disambiguation_not_needed_for_active_project(
        self, service, mock_notion_client
    ):
        """Active projects with decent confidence don't need disambiguation."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "active-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Website Project"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": {"name": "work"}},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            },
            {
                "id": "completed-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Old Website Project"}}]},
                    "status": {"select": {"name": "completed"}},
                    "project_type": {"select": {"name": "work"}},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            },
        ]

        result = await service.lookup("Website")

        assert result.found is True
        # First match has confidence >= 0.7 and is active
        assert result.needs_disambiguation is False
        assert result.project_id == "active-id"

    @pytest.mark.asyncio
    async def test_disambiguation_not_needed_for_high_confidence_match(
        self, service, mock_notion_client
    ):
        """High confidence exact match doesn't need disambiguation."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "exact-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Website"}}]},
                    "status": {"select": {"name": "paused"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            },
            {
                "id": "partial-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Old Website Redesign"}}]},
                    "status": {"select": {"name": "completed"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            },
        ]

        result = await service.lookup("Website")

        assert result.found is True
        # Exact match "Website" should have very high confidence (>= 0.9)
        assert result.needs_disambiguation is False
        # With no active matches, the highest confidence match wins
        assert result.project_id == "exact-id"

    @pytest.mark.asyncio
    async def test_matches_sorted_by_confidence_and_status(self, service, mock_notion_client):
        """Matches should be sorted by confidence then status."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "paused-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Project Alpha"}}]},
                    "status": {"select": {"name": "paused"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            },
            {
                "id": "active-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Project Alpha"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            },
        ]

        result = await service.lookup("Project Alpha")

        # Matches should be sorted (active status first for same confidence)
        assert len(result.matches) == 2
        # The active project should come first
        assert result.matches[0].project_id == "active-id"

    # -------------------------------------------
    # Status Priority Tests
    # -------------------------------------------

    def test_status_priority_ordering(self):
        """Active should have highest priority, cancelled lowest."""
        assert STATUS_PRIORITY[ProjectStatus.ACTIVE] > STATUS_PRIORITY[ProjectStatus.PAUSED]
        assert STATUS_PRIORITY[ProjectStatus.PAUSED] > STATUS_PRIORITY[ProjectStatus.COMPLETED]
        assert STATUS_PRIORITY[ProjectStatus.COMPLETED] > STATUS_PRIORITY[ProjectStatus.CANCELLED]

    @pytest.mark.asyncio
    async def test_active_status_gives_confidence_boost(self, service, mock_notion_client):
        """Active status should get a confidence boost."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "active-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "My Project"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        result = await service.lookup("My")

        # Active status should boost confidence
        # Base partial match is ~0.65, active boost is +0.1
        assert result.matches[0].confidence > 0.6

    # -------------------------------------------
    # Lookup by Status Tests
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_by_status(self, service, mock_notion_client):
        """lookup_by_status should return all projects with that status."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "active-1",
                "properties": {
                    "name": {"title": [{"text": {"content": "Project One"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            },
            {
                "id": "active-2",
                "properties": {
                    "name": {"title": [{"text": {"content": "Project Two"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            },
        ]

        matches = await service.lookup_by_status("active")

        assert len(matches) == 2
        mock_notion_client.query_projects.assert_called_with(status="active")

    @pytest.mark.asyncio
    async def test_lookup_active_convenience_method(self, service, mock_notion_client):
        """lookup_active should return only active projects."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "active-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Active Project"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        matches = await service.lookup_active()

        assert len(matches) == 1
        mock_notion_client.query_projects.assert_called_with(status="active")

    # -------------------------------------------
    # Edge Cases
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_without_notion_client(self):
        """Lookup without Notion client returns not found."""
        service = ProjectsService(notion_client=None)

        result = await service.lookup("Any Project")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_lookup_multiple_projects(self, service, mock_notion_client):
        """lookup_multiple should look up each project."""
        mock_notion_client.query_projects.side_effect = [
            [
                {
                    "id": "website-id",
                    "properties": {
                        "name": {"title": [{"text": {"content": "Website"}}]},
                        "status": {"select": None},
                        "project_type": {"select": None},
                        "deadline": {"date": None},
                        "next_action": {"rich_text": []},
                    },
                }
            ],
            [],  # API Integration not found
            [
                {
                    "id": "marketing-id",
                    "properties": {
                        "name": {"title": [{"text": {"content": "Marketing Campaign"}}]},
                        "status": {"select": {"name": "active"}},
                        "project_type": {"select": None},
                        "deadline": {"date": None},
                        "next_action": {"rich_text": []},
                    },
                }
            ],
        ]

        results = await service.lookup_multiple(
            ["Website", "API Integration", "Marketing"]
        )

        assert len(results) == 3
        assert results["Website"].found is True
        assert results["API Integration"].found is False
        assert results["Marketing"].found is True

    @pytest.mark.asyncio
    async def test_parse_results_handles_missing_fields(self, service, mock_notion_client):
        """parse_results should handle missing optional fields."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "minimal-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Minimal Project"}}]},
                    # Missing status, project_type, deadline, next_action
                },
            }
        ]

        result = await service.lookup("Minimal")

        assert result.found is True
        assert result.matches[0].name == "Minimal Project"
        assert result.matches[0].status is None
        assert result.matches[0].project_type is None
        assert result.matches[0].deadline is None
        assert result.matches[0].next_action is None

    @pytest.mark.asyncio
    async def test_parse_results_handles_empty_title(self, service, mock_notion_client):
        """parse_results should handle empty title list."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "empty-name-id",
                "properties": {
                    "name": {"title": []},
                    "status": {"select": None},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        result = await service.lookup("Empty")

        # Should still return result but with empty name
        assert result.found is True
        assert result.matches[0].name == ""

    @pytest.mark.asyncio
    async def test_parse_results_handles_deadline(self, service, mock_notion_client):
        """parse_results should correctly parse deadline dates."""
        mock_notion_client.query_projects.return_value = [
            {
                "id": "deadline-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Q1 Goals"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": {"name": "work"}},
                    "deadline": {"date": {"start": "2024-03-31T00:00:00Z"}},
                    "next_action": {"rich_text": [{"text": {"content": "Review metrics"}}]},
                },
            }
        ]

        result = await service.lookup("Q1")

        assert result.found is True
        assert result.matches[0].deadline is not None
        assert result.matches[0].deadline.year == 2024
        assert result.matches[0].deadline.month == 3
        assert result.matches[0].deadline.day == 31

    @pytest.mark.asyncio
    async def test_create_without_notion_client(self):
        """create() without Notion client should still create Project object."""
        service = ProjectsService(notion_client=None)

        project = await service.create("Offline Project", "personal")

        assert project.name == "Offline Project"
        assert project.project_type == "personal"
        # ID should be a generated UUID, not from Notion
        assert project.id is not None


class TestProjectStatusEnum:
    """Tests for ProjectStatus enum."""

    def test_status_values(self):
        """Status enum should have expected values."""
        assert ProjectStatus.ACTIVE.value == "active"
        assert ProjectStatus.PAUSED.value == "paused"
        assert ProjectStatus.COMPLETED.value == "completed"
        assert ProjectStatus.CANCELLED.value == "cancelled"


class TestProjectTypeEnum:
    """Tests for ProjectType enum."""

    def test_type_values(self):
        """Type enum should have expected values."""
        assert ProjectType.WORK.value == "work"
        assert ProjectType.PERSONAL.value == "personal"


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock Notion client."""
        client = AsyncMock()
        client.query_projects = AsyncMock(return_value=[])
        client.create_project = AsyncMock(return_value="new-id")
        return client

    def test_get_projects_service_creates_instance(self, mock_notion_client):
        """get_projects_service should create and cache a service instance."""
        service = get_projects_service(mock_notion_client)
        assert isinstance(service, ProjectsService)
        assert service.notion == mock_notion_client

    @pytest.mark.asyncio
    async def test_lookup_project_function(self, mock_notion_client):
        """lookup_project convenience function should work."""
        # Initialize the service with our mock
        get_projects_service(mock_notion_client)
        mock_notion_client.query_projects.return_value = [
            {
                "id": "test-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Test Project"}}]},
                    "status": {"select": None},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        result = await lookup_project("Test")

        assert result.found is True

    @pytest.mark.asyncio
    async def test_lookup_or_create_project_function(self, mock_notion_client):
        """lookup_or_create_project convenience function should work."""
        get_projects_service(mock_notion_client)
        mock_notion_client.query_projects.return_value = []

        result = await lookup_or_create_project("NewProject")

        assert result.found is True
        assert result.is_new is True

    @pytest.mark.asyncio
    async def test_create_project_function(self, mock_notion_client):
        """create_project convenience function should work."""
        get_projects_service(mock_notion_client)

        project = await create_project("Created Project", "work", "Test context")

        assert project.name == "Created Project"
        assert project.project_type == "work"
        assert project.context == "Test context"

    @pytest.mark.asyncio
    async def test_lookup_active_projects_function(self, mock_notion_client):
        """lookup_active_projects convenience function should work."""
        get_projects_service(mock_notion_client)
        mock_notion_client.query_projects.return_value = [
            {
                "id": "active-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Active Project"}}]},
                    "status": {"select": {"name": "active"}},
                    "project_type": {"select": None},
                    "deadline": {"date": None},
                    "next_action": {"rich_text": []},
                },
            }
        ]

        matches = await lookup_active_projects()

        assert len(matches) == 1
        assert matches[0].name == "Active Project"
