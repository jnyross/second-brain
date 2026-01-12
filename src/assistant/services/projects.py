"""Projects service for lookup, creation, and matching.

This service handles:
- Looking up existing projects by name or status
- Creating new projects when they don't exist
- Matching projects from extracted text to database entries
- Ranking matches by recency and confidence
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from assistant.notion.schemas import Project

if TYPE_CHECKING:
    from assistant.notion.client import NotionClient


class ProjectStatus(str, Enum):
    """Enumeration of project statuses."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProjectType(str, Enum):
    """Enumeration of project types."""

    WORK = "work"
    PERSONAL = "personal"


@dataclass
class ProjectMatch:
    """A potential match from the Projects database."""

    project_id: str
    name: str
    confidence: float  # 0.0 to 1.0
    status: str | None = None
    project_type: str | None = None
    deadline: datetime | None = None
    next_action: str | None = None
    matched_by: str = "name"  # "name", "context", "partial"

    def __lt__(self, other: "ProjectMatch") -> bool:
        """Sort by confidence descending, then by active status, then recency."""
        if self.confidence != other.confidence:
            return self.confidence > other.confidence
        # Active projects preferred over inactive
        self_active = self.status == "active"
        other_active = other.status == "active"
        if self_active != other_active:
            return self_active
        # If both have deadline, sooner deadline first (more urgent)
        if self.deadline and other.deadline:
            return self.deadline < other.deadline
        # Having deadline is better than not (shows project is defined)
        if self.deadline and not other.deadline:
            return True
        return False


@dataclass
class ProjectLookupResult:
    """Result of a project lookup operation."""

    found: bool
    project_id: str | None = None
    project: Project | None = None
    matches: list[ProjectMatch] = field(default_factory=list)
    needs_disambiguation: bool = False
    is_new: bool = False

    @property
    def has_single_match(self) -> bool:
        return self.found and len(self.matches) == 1


# Status priority for disambiguation (higher = prefer)
STATUS_PRIORITY = {
    ProjectStatus.ACTIVE: 100,
    ProjectStatus.PAUSED: 50,
    ProjectStatus.COMPLETED: 20,
    ProjectStatus.CANCELLED: 10,
}


class ProjectsService:
    """Service for managing project entities."""

    def __init__(self, notion_client: "NotionClient | None" = None):
        self.notion = notion_client

    async def lookup(
        self,
        name: str,
        status: str | None = None,
    ) -> ProjectLookupResult:
        """Look up a project by name and optionally status.

        Args:
            name: The project name to search for
            status: Optional status filter (active, paused, completed, cancelled)

        Returns:
            ProjectLookupResult with matches and disambiguation info
        """
        if not self.notion:
            return ProjectLookupResult(found=False)

        # Query Notion for projects matching name
        results = await self.notion.query_projects(name=name, status=status)

        if not results:
            return ProjectLookupResult(found=False)

        matches = self._parse_results(results, name)

        if len(matches) == 0:
            return ProjectLookupResult(found=False)

        if len(matches) == 1:
            match = matches[0]
            return ProjectLookupResult(
                found=True,
                project_id=match.project_id,
                matches=matches,
                needs_disambiguation=False,
            )

        # Multiple matches - check if one is clearly better
        sorted_matches = sorted(matches)  # Uses __lt__ for sorting
        best = sorted_matches[0]

        # If best match has much higher confidence, use it
        if best.confidence >= 0.9:
            return ProjectLookupResult(
                found=True,
                project_id=best.project_id,
                matches=sorted_matches,
                needs_disambiguation=False,
            )

        # Check if one is active (prefer active over inactive)
        for match in sorted_matches:
            if match.status == "active" and match.confidence >= 0.7:
                return ProjectLookupResult(
                    found=True,
                    project_id=match.project_id,
                    matches=sorted_matches,
                    needs_disambiguation=False,
                )

        # Multiple similar matches - needs disambiguation
        return ProjectLookupResult(
            found=True,
            project_id=best.project_id,  # Use best match as default
            matches=sorted_matches,
            needs_disambiguation=True,
        )

    async def lookup_or_create(
        self,
        name: str,
        project_type: str | None = None,
        status: str | None = None,
        context: str | None = None,
    ) -> ProjectLookupResult:
        """Look up a project, creating it if not found.

        Args:
            name: The project name to search for
            project_type: Optional type (work, personal)
            status: Optional status for lookup filtering
            context: Optional context for new project

        Returns:
            ProjectLookupResult with project info (found=True always)
        """
        result = await self.lookup(name, status)

        if result.found:
            return result

        # Create new project
        project = await self.create(name, project_type, context)

        return ProjectLookupResult(
            found=True,
            project_id=project.id if hasattr(project, "id") else None,
            project=project if isinstance(project, Project) else None,
            matches=[
                ProjectMatch(
                    project_id=project.id if hasattr(project, "id") else "",
                    name=name,
                    confidence=1.0,
                    project_type=project_type,
                    status="active",
                    matched_by="created",
                )
            ],
            is_new=True,
        )

    async def create(
        self,
        name: str,
        project_type: str | None = None,
        context: str | None = None,
        deadline: datetime | None = None,
    ) -> Project:
        """Create a new project.

        Args:
            name: Project name
            project_type: Type (work, personal)
            context: Optional context/notes field
            deadline: Optional deadline date

        Returns:
            Created Project object with ID from Notion
        """
        project = Project(
            name=name,
            project_type=project_type or "personal",
            context=context,
            deadline=deadline,
            status="active",
        )

        if self.notion:
            project_id = await self.notion.create_project(project)
            # Update the project object with the Notion-assigned ID
            project.id = project_id

        return project

    async def lookup_multiple(
        self,
        names: list[str],
    ) -> dict[str, ProjectLookupResult]:
        """Look up multiple projects.

        Args:
            names: List of project names to search for

        Returns:
            Dict mapping name to ProjectLookupResult
        """
        results = {}
        for name in names:
            results[name] = await self.lookup(name)
        return results

    async def lookup_by_status(
        self,
        status: str,
    ) -> list[ProjectMatch]:
        """Look up all projects with a specific status.

        Args:
            status: Status to filter by (active, paused, completed, cancelled)

        Returns:
            List of ProjectMatch objects
        """
        if not self.notion:
            return []

        results = await self.notion.query_projects(status=status)
        return self._parse_results(results, "")

    async def lookup_active(self) -> list[ProjectMatch]:
        """Look up all active projects.

        Returns:
            List of ProjectMatch objects for active projects
        """
        return await self.lookup_by_status("active")

    async def get_by_id(self, project_id: str) -> Project | None:
        """Get a project by its Notion page ID.

        Args:
            project_id: Notion page ID

        Returns:
            Project object or None if not found
        """
        if not self.notion:
            return None

        # TODO: Implement direct page fetch in NotionClient
        return None

    async def update_status(self, project_id: str, status: str) -> None:
        """Update the status of a project.

        Args:
            project_id: Notion page ID of the project
            status: New status (active, paused, completed, cancelled)
        """
        if not self.notion:
            return

        # TODO: Implement page update in NotionClient
        pass

    async def update_next_action(self, project_id: str, next_action: str) -> None:
        """Update the next action for a project.

        Args:
            project_id: Notion page ID of the project
            next_action: Description of the next action
        """
        if not self.notion:
            return

        # TODO: Implement page update in NotionClient
        pass

    def _parse_results(
        self,
        results: list[dict],
        search_name: str,
    ) -> list[ProjectMatch]:
        """Parse Notion query results into ProjectMatch objects.

        Args:
            results: Raw Notion API results
            search_name: Original search term

        Returns:
            List of ProjectMatch objects
        """
        matches = []
        search_lower = search_name.lower()

        for result in results:
            props = result.get("properties", {})

            # Extract name
            name_prop = props.get("name", {})
            title_list = name_prop.get("title", [])
            name = title_list[0]["text"]["content"] if title_list else ""

            # Extract status
            status_prop = props.get("status", {})
            status_select = status_prop.get("select")
            status = status_select["name"] if status_select else None

            # Extract project_type
            type_prop = props.get("project_type", {})
            type_select = type_prop.get("select")
            project_type = type_select["name"] if type_select else None

            # Extract deadline
            deadline_prop = props.get("deadline", {})
            deadline_date = deadline_prop.get("date")
            deadline = None
            if deadline_date and deadline_date.get("start"):
                try:
                    deadline = datetime.fromisoformat(deadline_date["start"].replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Extract next_action
            next_action_prop = props.get("next_action", {})
            next_action_text = next_action_prop.get("rich_text", [])
            next_action = next_action_text[0]["text"]["content"] if next_action_text else None

            # Calculate confidence
            confidence, matched_by = self._calculate_match_confidence(search_lower, name, status)

            matches.append(
                ProjectMatch(
                    project_id=result["id"],
                    name=name,
                    confidence=confidence,
                    status=status,
                    project_type=project_type,
                    deadline=deadline,
                    next_action=next_action,
                    matched_by=matched_by,
                )
            )

        return matches

    def _calculate_match_confidence(
        self,
        search: str,
        name: str,
        status: str | None,
    ) -> tuple[float, str]:
        """Calculate match confidence score.

        Args:
            search: Lowercase search term
            name: Project name
            status: Project status

        Returns:
            Tuple of (confidence score, matched_by field)
        """
        if not search:
            # No search term, return base confidence
            return 0.5, "status"

        name_lower = name.lower()

        # Exact name match
        if search == name_lower:
            confidence = 1.0
            matched_by = "name"
        # Name starts with search
        elif name_lower.startswith(search):
            confidence = 0.9
            matched_by = "name"
        # Search is part of name
        elif search in name_lower:
            confidence = 0.7
            matched_by = "name"
        # Name contains search as a word boundary
        elif any(word.startswith(search) for word in name_lower.split()):
            confidence = 0.65
            matched_by = "partial"
        else:
            # Fuzzy match - search word appears somewhere
            confidence = 0.5
            matched_by = "partial"

        # Boost for active status
        if status:
            try:
                status_enum = ProjectStatus(status)
                if status_enum in STATUS_PRIORITY:
                    boost = STATUS_PRIORITY[status_enum] / 1000  # Small boost
                    confidence = min(1.0, confidence + boost)
            except ValueError:
                pass

        return confidence, matched_by


# Convenience functions for module-level access
_service: ProjectsService | None = None


def get_projects_service(
    notion_client: "NotionClient | None" = None,
) -> ProjectsService:
    """Get or create a ProjectsService instance."""
    global _service
    if _service is None or notion_client is not None:
        _service = ProjectsService(notion_client)
    return _service


async def lookup_project(
    name: str,
    status: str | None = None,
) -> ProjectLookupResult:
    """Look up a project by name."""
    return await get_projects_service().lookup(name, status)


async def lookup_or_create_project(
    name: str,
    project_type: str | None = None,
    status: str | None = None,
    context: str | None = None,
) -> ProjectLookupResult:
    """Look up a project, creating it if not found."""
    return await get_projects_service().lookup_or_create(name, project_type, status, context)


async def create_project(
    name: str,
    project_type: str | None = None,
    context: str | None = None,
    deadline: datetime | None = None,
) -> Project:
    """Create a new project."""
    return await get_projects_service().create(name, project_type, context, deadline)


async def lookup_active_projects() -> list[ProjectMatch]:
    """Look up all active projects."""
    return await get_projects_service().lookup_active()
