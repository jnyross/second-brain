"""Relation linker service for Second Brain.

This service links tasks to people, places, and projects by:
1. Taking extracted entities from the entity extractor
2. Looking up or creating corresponding database records
3. Returning Notion relation IDs for task creation/update

The relation linker is the integration point between:
- Entity extraction (parser)
- Entity services (people, places, projects)
- Task creation (Notion client)
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from assistant.services.entities import ExtractedEntities, ExtractedPerson, ExtractedPlace
from assistant.services.people import PeopleService, LookupResult as PersonLookupResult
from assistant.services.places import PlacesService, PlaceLookupResult
from assistant.services.projects import ProjectsService, ProjectLookupResult

if TYPE_CHECKING:
    from assistant.notion.client import NotionClient


@dataclass
class LinkedEntity:
    """A linked entity with its Notion page ID and metadata."""

    entity_id: str
    entity_type: str  # "person", "place", "project"
    name: str
    confidence: float
    is_new: bool = False
    needs_disambiguation: bool = False


@dataclass
class LinkedRelations:
    """Container for all linked relations from extracted entities."""

    people: list[LinkedEntity] = field(default_factory=list)
    places: list[LinkedEntity] = field(default_factory=list)
    project: LinkedEntity | None = None

    # Aggregated IDs for task creation
    @property
    def people_ids(self) -> list[str]:
        """Get list of people page IDs for task relation."""
        return [p.entity_id for p in self.people if p.entity_id]

    @property
    def project_id(self) -> str | None:
        """Get project page ID for task relation."""
        return self.project.entity_id if self.project else None

    @property
    def place_ids(self) -> list[str]:
        """Get list of place page IDs."""
        return [p.entity_id for p in self.places if p.entity_id]

    @property
    def needs_review(self) -> bool:
        """Check if any linked entity needs disambiguation."""
        if any(p.needs_disambiguation for p in self.people):
            return True
        if any(p.needs_disambiguation for p in self.places):
            return True
        if self.project and self.project.needs_disambiguation:
            return True
        return False

    @property
    def new_entities_created(self) -> int:
        """Count of new entities created during linking."""
        count = sum(1 for p in self.people if p.is_new)
        count += sum(1 for p in self.places if p.is_new)
        if self.project and self.project.is_new:
            count += 1
        return count

    @property
    def summary(self) -> str:
        """Generate a human-readable summary of linked relations."""
        parts = []

        if self.people:
            names = [p.name for p in self.people]
            if len(names) == 1:
                parts.append(f"with {names[0]}")
            else:
                parts.append(f"with {', '.join(names[:-1])} and {names[-1]}")

        if self.project:
            parts.append(f"for {self.project.name}")

        if self.places:
            names = [p.name for p in self.places]
            parts.append(f"at {', '.join(names)}")

        return " ".join(parts) if parts else ""


class RelationLinker:
    """Links extracted entities to Notion database records.

    The relation linker takes extracted entities from parsed text and:
    1. Looks up existing records in Notion
    2. Creates new records when entities don't exist
    3. Returns structured relation IDs for task creation

    This enables the knowledge graph to grow automatically as the user
    mentions new people, places, and projects.
    """

    def __init__(
        self,
        notion_client: "NotionClient | None" = None,
        people_service: PeopleService | None = None,
        places_service: PlacesService | None = None,
        projects_service: ProjectsService | None = None,
    ):
        """Initialize the relation linker with services.

        Args:
            notion_client: Notion API client (services created from this)
            people_service: Optional custom PeopleService
            places_service: Optional custom PlacesService
            projects_service: Optional custom ProjectsService
        """
        self.notion = notion_client
        self.people = people_service or PeopleService(notion_client)
        self.places = places_service or PlacesService(notion_client)
        self.projects = projects_service or ProjectsService(notion_client)

    async def link(
        self,
        entities: ExtractedEntities,
        create_missing: bool = True,
        project_name: str | None = None,
    ) -> LinkedRelations:
        """Link all extracted entities to Notion records.

        Args:
            entities: Extracted entities from entity extractor
            create_missing: If True, create new records for unknown entities
            project_name: Optional explicit project name to link

        Returns:
            LinkedRelations with all Notion page IDs
        """
        result = LinkedRelations()

        # Link people
        for person in entities.people:
            linked = await self._link_person(person, create_missing)
            if linked:
                result.people.append(linked)

        # Link places
        for place in entities.places:
            linked = await self._link_place(place, create_missing)
            if linked:
                result.places.append(linked)

        # Link project if specified
        if project_name:
            linked = await self._link_project(project_name, create_missing)
            if linked:
                result.project = linked

        return result

    async def link_people(
        self,
        names: list[str],
        create_missing: bool = True,
    ) -> list[LinkedEntity]:
        """Link a list of person names to Notion records.

        Args:
            names: List of person names to link
            create_missing: If True, create new records for unknown people

        Returns:
            List of LinkedEntity objects
        """
        results = []
        for name in names:
            person = ExtractedPerson(name=name, confidence=100)
            linked = await self._link_person(person, create_missing)
            if linked:
                results.append(linked)
        return results

    async def link_places(
        self,
        names: list[str],
        create_missing: bool = True,
    ) -> list[LinkedEntity]:
        """Link a list of place names to Notion records.

        Args:
            names: List of place names to link
            create_missing: If True, create new records for unknown places

        Returns:
            List of LinkedEntity objects
        """
        results = []
        for name in names:
            place = ExtractedPlace(name=name, confidence=100)
            linked = await self._link_place(place, create_missing)
            if linked:
                results.append(linked)
        return results

    async def link_project(
        self,
        name: str,
        create_missing: bool = True,
    ) -> LinkedEntity | None:
        """Link a project name to a Notion record.

        Args:
            name: Project name to link
            create_missing: If True, create new record if not found

        Returns:
            LinkedEntity or None if not found and create_missing=False
        """
        return await self._link_project(name, create_missing)

    async def _link_person(
        self,
        person: ExtractedPerson,
        create_missing: bool,
    ) -> LinkedEntity | None:
        """Link a single person entity.

        Args:
            person: Extracted person entity
            create_missing: If True, create if not found

        Returns:
            LinkedEntity or None
        """
        if create_missing:
            result = await self.people.lookup_or_create(
                name=person.name,
                context=person.context,
            )
        else:
            result = await self.people.lookup(person.name)
            if not result.found:
                return None

        return self._person_result_to_linked(result, person.name, person.confidence)

    async def _link_place(
        self,
        place: ExtractedPlace,
        create_missing: bool,
    ) -> LinkedEntity | None:
        """Link a single place entity.

        Args:
            place: Extracted place entity
            create_missing: If True, create if not found

        Returns:
            LinkedEntity or None
        """
        if create_missing:
            result = await self.places.lookup_or_create(
                name=place.name,
                address=place.address,
                context=place.context,
            )
        else:
            result = await self.places.lookup(place.name)
            if not result.found:
                return None

        return self._place_result_to_linked(result, place.name, place.confidence)

    async def _link_project(
        self,
        name: str,
        create_missing: bool,
    ) -> LinkedEntity | None:
        """Link a project by name.

        Args:
            name: Project name
            create_missing: If True, create if not found

        Returns:
            LinkedEntity or None
        """
        if create_missing:
            result = await self.projects.lookup_or_create(name=name)
        else:
            result = await self.projects.lookup(name)
            if not result.found:
                return None

        return self._project_result_to_linked(result, name)

    def _person_result_to_linked(
        self,
        result: PersonLookupResult,
        name: str,
        extraction_confidence: int,
    ) -> LinkedEntity | None:
        """Convert a person lookup result to a LinkedEntity.

        Args:
            result: Person lookup result
            name: Original name searched for
            extraction_confidence: Confidence from entity extraction (0-100)

        Returns:
            LinkedEntity or None if no match
        """
        if not result.found or not result.person_id:
            return None

        # Get the best match name from results
        match_name = name
        match_confidence = 1.0
        if result.matches:
            best_match = result.matches[0]
            match_name = best_match.name
            match_confidence = best_match.confidence

        # Combine extraction and match confidence
        combined_confidence = (extraction_confidence / 100) * match_confidence

        return LinkedEntity(
            entity_id=result.person_id,
            entity_type="person",
            name=match_name,
            confidence=combined_confidence,
            is_new=result.is_new,
            needs_disambiguation=result.needs_disambiguation,
        )

    def _place_result_to_linked(
        self,
        result: PlaceLookupResult,
        name: str,
        extraction_confidence: int,
    ) -> LinkedEntity | None:
        """Convert a place lookup result to a LinkedEntity.

        Args:
            result: Place lookup result
            name: Original name searched for
            extraction_confidence: Confidence from entity extraction (0-100)

        Returns:
            LinkedEntity or None if no match
        """
        if not result.found or not result.place_id:
            return None

        # Get the best match name from results
        match_name = name
        match_confidence = 1.0
        if result.matches:
            best_match = result.matches[0]
            match_name = best_match.name
            match_confidence = best_match.confidence

        # Combine extraction and match confidence
        combined_confidence = (extraction_confidence / 100) * match_confidence

        return LinkedEntity(
            entity_id=result.place_id,
            entity_type="place",
            name=match_name,
            confidence=combined_confidence,
            is_new=result.is_new,
            needs_disambiguation=result.needs_disambiguation,
        )

    def _project_result_to_linked(
        self,
        result: ProjectLookupResult,
        name: str,
    ) -> LinkedEntity | None:
        """Convert a project lookup result to a LinkedEntity.

        Args:
            result: Project lookup result
            name: Original name searched for

        Returns:
            LinkedEntity or None if no match
        """
        if not result.found or not result.project_id:
            return None

        # Get the best match name from results
        match_name = name
        match_confidence = 1.0
        if result.matches:
            best_match = result.matches[0]
            match_name = best_match.name
            match_confidence = best_match.confidence

        return LinkedEntity(
            entity_id=result.project_id,
            entity_type="project",
            name=match_name,
            confidence=match_confidence,
            is_new=result.is_new,
            needs_disambiguation=result.needs_disambiguation,
        )


# Module-level service instance
_linker: RelationLinker | None = None


def get_relation_linker(
    notion_client: "NotionClient | None" = None,
) -> RelationLinker:
    """Get or create a RelationLinker instance.

    Args:
        notion_client: Optional Notion client to use

    Returns:
        RelationLinker instance
    """
    global _linker
    if _linker is None or notion_client is not None:
        _linker = RelationLinker(notion_client)
    return _linker


async def link_entities(
    entities: ExtractedEntities,
    create_missing: bool = True,
    project_name: str | None = None,
) -> LinkedRelations:
    """Convenience function to link extracted entities.

    Args:
        entities: Extracted entities from entity extractor
        create_missing: If True, create new records for unknown entities
        project_name: Optional explicit project name

    Returns:
        LinkedRelations with all Notion page IDs
    """
    return await get_relation_linker().link(
        entities, create_missing, project_name
    )


async def link_people_by_name(
    names: list[str],
    create_missing: bool = True,
) -> list[LinkedEntity]:
    """Convenience function to link people by names.

    Args:
        names: List of person names to link
        create_missing: If True, create new records for unknown people

    Returns:
        List of LinkedEntity objects
    """
    return await get_relation_linker().link_people(names, create_missing)


async def link_places_by_name(
    names: list[str],
    create_missing: bool = True,
) -> list[LinkedEntity]:
    """Convenience function to link places by names.

    Args:
        names: List of place names to link
        create_missing: If True, create new records for unknown places

    Returns:
        List of LinkedEntity objects
    """
    return await get_relation_linker().link_places(names, create_missing)


async def link_project_by_name(
    name: str,
    create_missing: bool = True,
) -> LinkedEntity | None:
    """Convenience function to link a project by name.

    Args:
        name: Project name to link
        create_missing: If True, create new record if not found

    Returns:
        LinkedEntity or None
    """
    return await get_relation_linker().link_project(name, create_missing)
