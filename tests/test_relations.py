"""Tests for the relation linker service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.services.relations import (
    LinkedEntity,
    LinkedRelations,
    RelationLinker,
    get_relation_linker,
    link_entities,
    link_people_by_name,
    link_places_by_name,
    link_project_by_name,
)
from assistant.services.entities import (
    ExtractedEntities,
    ExtractedPerson,
    ExtractedPlace,
)
from assistant.services.people import LookupResult as PersonLookupResult, PersonMatch
from assistant.services.places import PlaceLookupResult, PlaceMatch
from assistant.services.projects import ProjectLookupResult, ProjectMatch


class TestLinkedEntity:
    """Tests for the LinkedEntity dataclass."""

    def test_linked_entity_creation(self):
        entity = LinkedEntity(
            entity_id="page-123",
            entity_type="person",
            name="Alice",
            confidence=0.95,
        )
        assert entity.entity_id == "page-123"
        assert entity.entity_type == "person"
        assert entity.name == "Alice"
        assert entity.confidence == 0.95
        assert entity.is_new is False
        assert entity.needs_disambiguation is False

    def test_linked_entity_with_flags(self):
        entity = LinkedEntity(
            entity_id="page-456",
            entity_type="place",
            name="Coffee Shop",
            confidence=0.8,
            is_new=True,
            needs_disambiguation=True,
        )
        assert entity.is_new is True
        assert entity.needs_disambiguation is True


class TestLinkedRelations:
    """Tests for the LinkedRelations dataclass."""

    def test_empty_relations(self):
        relations = LinkedRelations()
        assert relations.people == []
        assert relations.places == []
        assert relations.project is None
        assert relations.people_ids == []
        assert relations.project_id is None
        assert relations.place_ids == []
        assert relations.needs_review is False
        assert relations.new_entities_created == 0
        assert relations.summary == ""

    def test_people_ids_property(self):
        relations = LinkedRelations(
            people=[
                LinkedEntity("id1", "person", "Alice", 0.9),
                LinkedEntity("id2", "person", "Bob", 0.8),
            ]
        )
        assert relations.people_ids == ["id1", "id2"]

    def test_project_id_property(self):
        relations = LinkedRelations(
            project=LinkedEntity("proj-1", "project", "Alpha", 0.95)
        )
        assert relations.project_id == "proj-1"

    def test_place_ids_property(self):
        relations = LinkedRelations(
            places=[
                LinkedEntity("place1", "place", "Starbucks", 0.9),
                LinkedEntity("place2", "place", "Office", 0.85),
            ]
        )
        assert relations.place_ids == ["place1", "place2"]

    def test_needs_review_person(self):
        relations = LinkedRelations(
            people=[
                LinkedEntity("id1", "person", "Sarah", 0.6, needs_disambiguation=True),
            ]
        )
        assert relations.needs_review is True

    def test_needs_review_place(self):
        relations = LinkedRelations(
            places=[
                LinkedEntity("id1", "place", "Cafe", 0.5, needs_disambiguation=True),
            ]
        )
        assert relations.needs_review is True

    def test_needs_review_project(self):
        relations = LinkedRelations(
            project=LinkedEntity("id1", "project", "Beta", 0.6, needs_disambiguation=True)
        )
        assert relations.needs_review is True

    def test_needs_review_false_when_all_clear(self):
        relations = LinkedRelations(
            people=[
                LinkedEntity("id1", "person", "Alice", 0.95),
            ],
            places=[
                LinkedEntity("id2", "place", "Office", 0.9),
            ],
            project=LinkedEntity("id3", "project", "Alpha", 0.95),
        )
        assert relations.needs_review is False

    def test_new_entities_created_count(self):
        relations = LinkedRelations(
            people=[
                LinkedEntity("id1", "person", "Alice", 0.9, is_new=True),
                LinkedEntity("id2", "person", "Bob", 0.8, is_new=False),
            ],
            places=[
                LinkedEntity("id3", "place", "New Cafe", 0.9, is_new=True),
            ],
            project=LinkedEntity("id4", "project", "New Project", 0.95, is_new=True),
        )
        assert relations.new_entities_created == 3

    def test_summary_with_one_person(self):
        relations = LinkedRelations(
            people=[LinkedEntity("id1", "person", "Alice", 0.9)]
        )
        assert relations.summary == "with Alice"

    def test_summary_with_multiple_people(self):
        relations = LinkedRelations(
            people=[
                LinkedEntity("id1", "person", "Alice", 0.9),
                LinkedEntity("id2", "person", "Bob", 0.8),
            ]
        )
        assert relations.summary == "with Alice and Bob"

    def test_summary_with_three_people(self):
        relations = LinkedRelations(
            people=[
                LinkedEntity("id1", "person", "Alice", 0.9),
                LinkedEntity("id2", "person", "Bob", 0.8),
                LinkedEntity("id3", "person", "Carol", 0.7),
            ]
        )
        assert relations.summary == "with Alice, Bob and Carol"

    def test_summary_with_project(self):
        relations = LinkedRelations(
            project=LinkedEntity("id1", "project", "Alpha", 0.95)
        )
        assert relations.summary == "for Alpha"

    def test_summary_with_places(self):
        relations = LinkedRelations(
            places=[LinkedEntity("id1", "place", "Starbucks", 0.9)]
        )
        assert relations.summary == "at Starbucks"

    def test_summary_full(self):
        relations = LinkedRelations(
            people=[LinkedEntity("id1", "person", "Alice", 0.9)],
            project=LinkedEntity("id2", "project", "Beta", 0.95),
            places=[LinkedEntity("id3", "place", "Coffee Shop", 0.9)],
        )
        assert relations.summary == "with Alice for Beta at Coffee Shop"


class TestRelationLinker:
    """Tests for the RelationLinker class."""

    @pytest.fixture
    def mock_notion(self):
        return MagicMock()

    @pytest.fixture
    def mock_people_service(self):
        return MagicMock()

    @pytest.fixture
    def mock_places_service(self):
        return MagicMock()

    @pytest.fixture
    def mock_projects_service(self):
        return MagicMock()

    @pytest.fixture
    def linker(
        self, mock_notion, mock_people_service, mock_places_service, mock_projects_service
    ):
        return RelationLinker(
            notion_client=mock_notion,
            people_service=mock_people_service,
            places_service=mock_places_service,
            projects_service=mock_projects_service,
        )

    def test_init_creates_services_from_notion_client(self, mock_notion):
        linker = RelationLinker(notion_client=mock_notion)
        assert linker.notion is mock_notion
        assert linker.people is not None
        assert linker.places is not None
        assert linker.projects is not None

    def test_init_with_custom_services(
        self, mock_notion, mock_people_service, mock_places_service, mock_projects_service
    ):
        linker = RelationLinker(
            notion_client=mock_notion,
            people_service=mock_people_service,
            places_service=mock_places_service,
            projects_service=mock_projects_service,
        )
        assert linker.people is mock_people_service
        assert linker.places is mock_places_service
        assert linker.projects is mock_projects_service

    @pytest.mark.asyncio
    async def test_link_empty_entities(self, linker):
        entities = ExtractedEntities()
        result = await linker.link(entities)
        assert result.people == []
        assert result.places == []
        assert result.project is None

    @pytest.mark.asyncio
    async def test_link_person_found(self, linker, mock_people_service):
        mock_people_service.lookup_or_create = AsyncMock(
            return_value=PersonLookupResult(
                found=True,
                person_id="person-123",
                matches=[PersonMatch("person-123", "Alice Smith", 0.95)],
            )
        )

        entities = ExtractedEntities(
            people=[ExtractedPerson("Alice", 90)]
        )
        result = await linker.link(entities)

        assert len(result.people) == 1
        assert result.people[0].entity_id == "person-123"
        assert result.people[0].name == "Alice Smith"
        assert result.people[0].entity_type == "person"

    @pytest.mark.asyncio
    async def test_link_person_created(self, linker, mock_people_service):
        mock_people_service.lookup_or_create = AsyncMock(
            return_value=PersonLookupResult(
                found=True,
                person_id="new-person-id",
                matches=[PersonMatch("new-person-id", "Bob", 1.0)],
                is_new=True,
            )
        )

        entities = ExtractedEntities(
            people=[ExtractedPerson("Bob", 85)]
        )
        result = await linker.link(entities)

        assert len(result.people) == 1
        assert result.people[0].is_new is True

    @pytest.mark.asyncio
    async def test_link_person_needs_disambiguation(self, linker, mock_people_service):
        mock_people_service.lookup_or_create = AsyncMock(
            return_value=PersonLookupResult(
                found=True,
                person_id="sarah-1",
                matches=[
                    PersonMatch("sarah-1", "Sarah Jones", 0.7),
                    PersonMatch("sarah-2", "Sarah Smith", 0.7),
                ],
                needs_disambiguation=True,
            )
        )

        entities = ExtractedEntities(
            people=[ExtractedPerson("Sarah", 80)]
        )
        result = await linker.link(entities)

        assert len(result.people) == 1
        assert result.people[0].needs_disambiguation is True
        assert result.needs_review is True

    @pytest.mark.asyncio
    async def test_link_person_without_create(self, linker, mock_people_service):
        mock_people_service.lookup = AsyncMock(
            return_value=PersonLookupResult(found=False)
        )

        entities = ExtractedEntities(
            people=[ExtractedPerson("Unknown", 60)]
        )
        result = await linker.link(entities, create_missing=False)

        assert len(result.people) == 0
        mock_people_service.lookup.assert_called_once_with("Unknown")

    @pytest.mark.asyncio
    async def test_link_place_found(self, linker, mock_places_service):
        mock_places_service.lookup_or_create = AsyncMock(
            return_value=PlaceLookupResult(
                found=True,
                place_id="place-123",
                matches=[PlaceMatch("place-123", "Starbucks", 0.9)],
            )
        )

        entities = ExtractedEntities(
            places=[ExtractedPlace("Starbucks", 80)]
        )
        result = await linker.link(entities)

        assert len(result.places) == 1
        assert result.places[0].entity_id == "place-123"
        assert result.places[0].entity_type == "place"

    @pytest.mark.asyncio
    async def test_link_place_created(self, linker, mock_places_service):
        mock_places_service.lookup_or_create = AsyncMock(
            return_value=PlaceLookupResult(
                found=True,
                place_id="new-place-id",
                matches=[PlaceMatch("new-place-id", "New Cafe", 1.0)],
                is_new=True,
            )
        )

        entities = ExtractedEntities(
            places=[ExtractedPlace("New Cafe", 75)]
        )
        result = await linker.link(entities)

        assert len(result.places) == 1
        assert result.places[0].is_new is True

    @pytest.mark.asyncio
    async def test_link_project(self, linker, mock_projects_service):
        mock_projects_service.lookup_or_create = AsyncMock(
            return_value=ProjectLookupResult(
                found=True,
                project_id="project-123",
                matches=[ProjectMatch("project-123", "Alpha Project", 0.95)],
            )
        )

        entities = ExtractedEntities()
        result = await linker.link(entities, project_name="Alpha")

        assert result.project is not None
        assert result.project.entity_id == "project-123"
        assert result.project.name == "Alpha Project"
        assert result.project.entity_type == "project"

    @pytest.mark.asyncio
    async def test_link_multiple_entities(
        self, linker, mock_people_service, mock_places_service, mock_projects_service
    ):
        mock_people_service.lookup_or_create = AsyncMock(
            return_value=PersonLookupResult(
                found=True,
                person_id="person-1",
                matches=[PersonMatch("person-1", "Alice", 0.9)],
            )
        )
        mock_places_service.lookup_or_create = AsyncMock(
            return_value=PlaceLookupResult(
                found=True,
                place_id="place-1",
                matches=[PlaceMatch("place-1", "Office", 0.85)],
            )
        )
        mock_projects_service.lookup_or_create = AsyncMock(
            return_value=ProjectLookupResult(
                found=True,
                project_id="proj-1",
                matches=[ProjectMatch("proj-1", "Beta", 0.95)],
            )
        )

        entities = ExtractedEntities(
            people=[ExtractedPerson("Alice", 90)],
            places=[ExtractedPlace("Office", 80)],
        )
        result = await linker.link(entities, project_name="Beta")

        assert len(result.people) == 1
        assert len(result.places) == 1
        assert result.project is not None
        assert result.people_ids == ["person-1"]
        assert result.place_ids == ["place-1"]
        assert result.project_id == "proj-1"

    @pytest.mark.asyncio
    async def test_link_people_convenience_method(self, linker, mock_people_service):
        mock_people_service.lookup_or_create = AsyncMock(
            side_effect=[
                PersonLookupResult(
                    found=True,
                    person_id="p1",
                    matches=[PersonMatch("p1", "Alice", 0.95)],
                ),
                PersonLookupResult(
                    found=True,
                    person_id="p2",
                    matches=[PersonMatch("p2", "Bob", 0.9)],
                ),
            ]
        )

        result = await linker.link_people(["Alice", "Bob"])

        assert len(result) == 2
        assert result[0].entity_id == "p1"
        assert result[1].entity_id == "p2"

    @pytest.mark.asyncio
    async def test_link_places_convenience_method(self, linker, mock_places_service):
        mock_places_service.lookup_or_create = AsyncMock(
            return_value=PlaceLookupResult(
                found=True,
                place_id="pl1",
                matches=[PlaceMatch("pl1", "Coffee Shop", 0.9)],
            )
        )

        result = await linker.link_places(["Coffee Shop"])

        assert len(result) == 1
        assert result[0].entity_id == "pl1"

    @pytest.mark.asyncio
    async def test_link_project_convenience_method(self, linker, mock_projects_service):
        mock_projects_service.lookup_or_create = AsyncMock(
            return_value=ProjectLookupResult(
                found=True,
                project_id="prj1",
                matches=[ProjectMatch("prj1", "Delta", 0.9)],
            )
        )

        result = await linker.link_project("Delta")

        assert result is not None
        assert result.entity_id == "prj1"

    @pytest.mark.asyncio
    async def test_link_project_not_found_without_create(self, linker, mock_projects_service):
        mock_projects_service.lookup = AsyncMock(
            return_value=ProjectLookupResult(found=False)
        )

        result = await linker.link_project("Unknown", create_missing=False)

        assert result is None

    def test_person_result_to_linked_not_found(self, linker):
        result = PersonLookupResult(found=False)
        linked = linker._person_result_to_linked(result, "Alice", 90)
        assert linked is None

    def test_person_result_to_linked_no_id(self, linker):
        result = PersonLookupResult(found=True, person_id=None)
        linked = linker._person_result_to_linked(result, "Alice", 90)
        assert linked is None

    def test_person_result_to_linked_success(self, linker):
        result = PersonLookupResult(
            found=True,
            person_id="p123",
            matches=[PersonMatch("p123", "Alice Smith", 0.95)],
        )
        linked = linker._person_result_to_linked(result, "Alice", 90)

        assert linked is not None
        assert linked.entity_id == "p123"
        assert linked.name == "Alice Smith"
        assert linked.confidence == 0.9 * 0.95  # extraction * match

    def test_person_result_to_linked_combined_confidence(self, linker):
        result = PersonLookupResult(
            found=True,
            person_id="p123",
            matches=[PersonMatch("p123", "Bob", 0.8)],
        )
        # 80% extraction confidence * 80% match confidence = 64%
        linked = linker._person_result_to_linked(result, "Bob", 80)
        assert abs(linked.confidence - 0.64) < 0.001


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_global_linker(self):
        """Reset the global linker before each test."""
        import assistant.services.relations as relations_module
        relations_module._linker = None
        yield
        relations_module._linker = None

    def test_get_relation_linker_creates_instance(self):
        linker = get_relation_linker()
        assert linker is not None
        assert isinstance(linker, RelationLinker)

    def test_get_relation_linker_reuses_instance(self):
        linker1 = get_relation_linker()
        linker2 = get_relation_linker()
        assert linker1 is linker2

    def test_get_relation_linker_with_new_client(self):
        linker1 = get_relation_linker()
        mock_notion = MagicMock()
        linker2 = get_relation_linker(mock_notion)
        assert linker1 is not linker2
        assert linker2.notion is mock_notion

    @pytest.mark.asyncio
    async def test_link_entities_function(self):
        with patch.object(
            RelationLinker, "link", new_callable=AsyncMock
        ) as mock_link:
            mock_link.return_value = LinkedRelations()

            entities = ExtractedEntities()
            result = await link_entities(entities)

            assert isinstance(result, LinkedRelations)
            mock_link.assert_called_once()

    @pytest.mark.asyncio
    async def test_link_people_by_name_function(self):
        with patch.object(
            RelationLinker, "link_people", new_callable=AsyncMock
        ) as mock_link:
            mock_link.return_value = [
                LinkedEntity("p1", "person", "Alice", 0.9)
            ]

            result = await link_people_by_name(["Alice"])

            assert len(result) == 1
            mock_link.assert_called_once_with(["Alice"], True)

    @pytest.mark.asyncio
    async def test_link_places_by_name_function(self):
        with patch.object(
            RelationLinker, "link_places", new_callable=AsyncMock
        ) as mock_link:
            mock_link.return_value = [
                LinkedEntity("pl1", "place", "Office", 0.9)
            ]

            result = await link_places_by_name(["Office"])

            assert len(result) == 1
            mock_link.assert_called_once_with(["Office"], True)

    @pytest.mark.asyncio
    async def test_link_project_by_name_function(self):
        with patch.object(
            RelationLinker, "link_project", new_callable=AsyncMock
        ) as mock_link:
            mock_link.return_value = LinkedEntity("prj1", "project", "Alpha", 0.95)

            result = await link_project_by_name("Alpha")

            assert result is not None
            assert result.entity_id == "prj1"
            mock_link.assert_called_once_with("Alpha", True)

    @pytest.mark.asyncio
    async def test_link_project_by_name_not_found(self):
        with patch.object(
            RelationLinker, "link_project", new_callable=AsyncMock
        ) as mock_link:
            mock_link.return_value = None

            result = await link_project_by_name("Unknown", create_missing=False)

            assert result is None
            mock_link.assert_called_once_with("Unknown", False)
