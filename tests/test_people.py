"""Tests for the People service.

Covers acceptance tests:
- AT-104: Person Extraction and Linking (existing person found)
- AT-105: Person Creation (new person created when not found)
- AT-117: Person Disambiguation (multiple matches handled)
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest

from assistant.services.people import (
    PeopleService,
    PersonMatch,
    LookupResult,
    RELATIONSHIP_PRIORITY,
    get_people_service,
    lookup_person,
    lookup_or_create_person,
    create_person,
)
from assistant.notion.schemas import Person, Relationship


class TestPersonMatch:
    """Tests for PersonMatch dataclass."""

    def test_sort_by_confidence_descending(self):
        """Higher confidence should sort first."""
        match1 = PersonMatch(person_id="1", name="Alice", confidence=0.8)
        match2 = PersonMatch(person_id="2", name="Bob", confidence=0.9)

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Bob"  # 0.9 confidence
        assert sorted_matches[1].name == "Alice"  # 0.8 confidence

    def test_sort_by_recency_when_same_confidence(self):
        """When confidence is equal, more recent last_contact sorts first."""
        now = datetime.now()
        match1 = PersonMatch(
            person_id="1",
            name="Alice",
            confidence=0.8,
            last_contact=now - timedelta(days=7),
        )
        match2 = PersonMatch(
            person_id="2",
            name="Bob",
            confidence=0.8,
            last_contact=now - timedelta(days=1),
        )

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Bob"  # More recent contact

    def test_having_last_contact_beats_not_having(self):
        """Having last_contact is better than not having one."""
        match1 = PersonMatch(person_id="1", name="Alice", confidence=0.8)
        match2 = PersonMatch(
            person_id="2",
            name="Bob",
            confidence=0.8,
            last_contact=datetime.now(),
        )

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Bob"  # Has last_contact


class TestLookupResult:
    """Tests for LookupResult dataclass."""

    def test_has_single_match_true(self):
        """has_single_match should be True for exactly one match."""
        result = LookupResult(
            found=True,
            person_id="123",
            matches=[PersonMatch(person_id="123", name="Alice", confidence=1.0)],
        )
        assert result.has_single_match is True

    def test_has_single_match_false_when_multiple(self):
        """has_single_match should be False for multiple matches."""
        result = LookupResult(
            found=True,
            person_id="123",
            matches=[
                PersonMatch(person_id="123", name="Alice", confidence=0.9),
                PersonMatch(person_id="456", name="Alice B", confidence=0.7),
            ],
        )
        assert result.has_single_match is False

    def test_has_single_match_false_when_not_found(self):
        """has_single_match should be False when not found."""
        result = LookupResult(found=False)
        assert result.has_single_match is False


class TestPeopleService:
    """Tests for PeopleService class."""

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock Notion client."""
        client = AsyncMock()
        client.query_people = AsyncMock(return_value=[])
        client.create_person = AsyncMock(return_value="new-person-id")
        return client

    @pytest.fixture
    def service(self, mock_notion_client):
        """Create a PeopleService with mocked client."""
        return PeopleService(mock_notion_client)

    # -------------------------------------------
    # AT-104: Person Extraction and Linking
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_finds_existing_person_by_name(self, service, mock_notion_client):
        """AT-104: When person exists, lookup returns the match."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "sarah-id-123",
                "properties": {
                    "name": {"title": [{"text": {"content": "Sarah"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "friend"}},
                    "last_contact": {"date": None},
                },
            }
        ]

        result = await service.lookup("Sarah")

        assert result.found is True
        assert result.person_id == "sarah-id-123"
        assert len(result.matches) == 1
        assert result.matches[0].name == "Sarah"
        assert result.needs_disambiguation is False

    @pytest.mark.asyncio
    async def test_lookup_finds_person_by_alias(self, service, mock_notion_client):
        """Person can be found by alias when name doesn't match."""
        # Use a name that won't match the search term "Jess"
        mock_notion_client.query_people.return_value = [
            {
                "id": "jessica-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "J. Smith"}}]},
                    "aliases": {"rich_text": [{"text": {"content": "Jess, JS"}}]},
                    "relationship": {"select": {"name": "colleague"}},
                    "last_contact": {"date": None},
                },
            }
        ]

        result = await service.lookup("Jess")

        assert result.found is True
        assert result.matches[0].matched_by == "alias"
        assert "Jess" in result.matches[0].aliases

    @pytest.mark.asyncio
    async def test_lookup_returns_not_found_when_no_match(self, service, mock_notion_client):
        """When no matches, lookup returns not found."""
        mock_notion_client.query_people.return_value = []

        result = await service.lookup("NonexistentPerson")

        assert result.found is False
        assert result.person_id is None
        assert len(result.matches) == 0

    @pytest.mark.asyncio
    async def test_lookup_exact_name_match_high_confidence(self, service, mock_notion_client):
        """Exact name match should have confidence 1.0."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "mike-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Mike"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": None},
                    "last_contact": {"date": None},
                },
            }
        ]

        result = await service.lookup("Mike")

        assert result.matches[0].confidence >= 0.99  # 1.0 + possible boost

    @pytest.mark.asyncio
    async def test_lookup_partial_name_match_lower_confidence(self, service, mock_notion_client):
        """Partial name match should have lower confidence."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "michael-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Michael Johnson"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": None},
                    "last_contact": {"date": None},
                },
            }
        ]

        result = await service.lookup("Michael")

        # Name starts with search term, should be ~0.9
        assert 0.85 <= result.matches[0].confidence <= 0.95

    # -------------------------------------------
    # AT-105: Person Creation
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_or_create_creates_when_not_found(self, service, mock_notion_client):
        """AT-105: When person not found, create new entry."""
        mock_notion_client.query_people.return_value = []

        result = await service.lookup_or_create("Bob")

        assert result.found is True
        assert result.is_new is True
        mock_notion_client.create_person.assert_called_once()
        # Verify the person object was passed
        call_args = mock_notion_client.create_person.call_args
        person = call_args[0][0]
        assert person.name == "Bob"

    @pytest.mark.asyncio
    async def test_lookup_or_create_with_relationship(self, service, mock_notion_client):
        """Created person should have relationship set."""
        mock_notion_client.query_people.return_value = []

        result = await service.lookup_or_create(
            "Alice",
            relationship=Relationship.COLLEAGUE,
            context="Met at work conference",
        )

        assert result.is_new is True
        call_args = mock_notion_client.create_person.call_args
        person = call_args[0][0]
        assert person.name == "Alice"
        assert person.relationship == Relationship.COLLEAGUE
        assert person.notes == "Met at work conference"

    @pytest.mark.asyncio
    async def test_lookup_or_create_returns_existing_when_found(self, service, mock_notion_client):
        """When person exists, lookup_or_create returns existing."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "bob-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Bob"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "friend"}},
                    "last_contact": {"date": None},
                },
            }
        ]

        result = await service.lookup_or_create("Bob")

        assert result.found is True
        assert result.is_new is False
        assert result.person_id == "bob-id"
        mock_notion_client.create_person.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_person(self, service, mock_notion_client):
        """create() should create a new person in Notion."""
        person = await service.create("Dave", Relationship.FRIEND, "From volleyball")

        assert person.name == "Dave"
        assert person.relationship == Relationship.FRIEND
        assert person.notes == "From volleyball"
        assert person.id == "new-person-id"
        mock_notion_client.create_person.assert_called_once()

    # -------------------------------------------
    # AT-117: Person Disambiguation
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_disambiguation_required_for_multiple_similar_matches(
        self, service, mock_notion_client
    ):
        """AT-117: Multiple people with same name and similar confidence trigger disambiguation.

        Note: When both matches have high confidence (>=0.9), the system uses the best match
        by default. Disambiguation is flagged when confidence is lower and no clear winner.
        For 0.9 confidence matches without partner/family relationship, disambiguation is still
        triggered if both are colleagues with similar names.
        """
        # Use partial matches (contained in name) which give lower confidence (~0.7)
        mock_notion_client.query_people.return_value = [
            {
                "id": "sarah-chen-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Chen, Sarah Lee"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "colleague"}},
                    "last_contact": {"date": {"start": "2024-01-01T10:00:00Z"}},
                },
            },
            {
                "id": "sarah-jones-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Jones, Sarah May"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "colleague"}},
                    "last_contact": {"date": {"start": "2024-01-05T10:00:00Z"}},
                },
            },
        ]

        result = await service.lookup("Sarah")

        assert result.found is True
        assert len(result.matches) == 2
        # With lower confidence matches (~0.7), disambiguation should be triggered
        assert result.needs_disambiguation is True
        # Best match is still selected as default (most recent contact)
        assert result.person_id == "sarah-jones-id"

    @pytest.mark.asyncio
    async def test_disambiguation_not_needed_for_partner_or_family(
        self, service, mock_notion_client
    ):
        """Partner/family relationships don't need disambiguation."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "sarah-wife-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Sarah"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "partner"}},
                    "last_contact": {"date": None},
                },
            },
            {
                "id": "sarah-colleague-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Sarah Miller"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "colleague"}},
                    "last_contact": {"date": None},
                },
            },
        ]

        result = await service.lookup("Sarah")

        assert result.found is True
        assert result.needs_disambiguation is False
        assert result.person_id == "sarah-wife-id"

    @pytest.mark.asyncio
    async def test_disambiguation_not_needed_for_family(self, service, mock_notion_client):
        """Family relationships don't need disambiguation."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "mom-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Sarah"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "family"}},
                    "last_contact": {"date": None},
                },
            },
            {
                "id": "sarah-friend-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Sarah Brown"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "friend"}},
                    "last_contact": {"date": None},
                },
            },
        ]

        result = await service.lookup("Sarah")

        assert result.found is True
        assert result.needs_disambiguation is False
        assert result.person_id == "mom-id"

    @pytest.mark.asyncio
    async def test_disambiguation_not_needed_for_high_confidence_match(
        self, service, mock_notion_client
    ):
        """High confidence exact match doesn't need disambiguation."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "mike-exact-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Mike"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "friend"}},
                    "last_contact": {"date": None},
                },
            },
            {
                "id": "michael-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Michael Smith"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "colleague"}},
                    "last_contact": {"date": None},
                },
            },
        ]

        result = await service.lookup("Mike")

        assert result.found is True
        # Exact match "Mike" should have very high confidence
        assert result.needs_disambiguation is False
        assert result.person_id == "mike-exact-id"

    @pytest.mark.asyncio
    async def test_matches_sorted_by_confidence_and_recency(self, service, mock_notion_client):
        """Matches should be sorted by confidence then recency."""
        now = datetime.now()
        mock_notion_client.query_people.return_value = [
            {
                "id": "old-contact-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Sarah A"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "colleague"}},
                    "last_contact": {"date": {"start": "2023-01-01T10:00:00Z"}},
                },
            },
            {
                "id": "recent-contact-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Sarah B"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "colleague"}},
                    "last_contact": {"date": {"start": "2024-12-01T10:00:00Z"}},
                },
            },
        ]

        result = await service.lookup("Sarah")

        # Matches should be sorted (most recent contact first for same confidence)
        assert len(result.matches) == 2
        # The more recently contacted should come first
        assert result.matches[0].person_id == "recent-contact-id"

    # -------------------------------------------
    # Relationship Priority Tests
    # -------------------------------------------

    def test_relationship_priority_ordering(self):
        """Partner should have highest priority, acquaintance lowest."""
        assert RELATIONSHIP_PRIORITY[Relationship.PARTNER] > RELATIONSHIP_PRIORITY[Relationship.FAMILY]
        assert RELATIONSHIP_PRIORITY[Relationship.FAMILY] > RELATIONSHIP_PRIORITY[Relationship.FRIEND]
        assert RELATIONSHIP_PRIORITY[Relationship.FRIEND] > RELATIONSHIP_PRIORITY[Relationship.COLLEAGUE]
        assert RELATIONSHIP_PRIORITY[Relationship.COLLEAGUE] > RELATIONSHIP_PRIORITY[Relationship.ACQUAINTANCE]

    @pytest.mark.asyncio
    async def test_relationship_gives_confidence_boost(self, service, mock_notion_client):
        """Close relationships should get a confidence boost."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "partner-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Alex Partner"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": {"name": "partner"}},
                    "last_contact": {"date": None},
                },
            }
        ]

        result = await service.lookup("Alex")

        # Partner relationship should boost confidence
        # Base partial match is ~0.7, partner boost is +0.1
        assert result.matches[0].confidence > 0.7

    # -------------------------------------------
    # Edge Cases
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_without_notion_client(self):
        """Lookup without Notion client returns not found."""
        service = PeopleService(notion_client=None)

        result = await service.lookup("Anyone")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_lookup_multiple_names(self, service, mock_notion_client):
        """lookup_multiple should look up each name."""
        mock_notion_client.query_people.side_effect = [
            [
                {
                    "id": "alice-id",
                    "properties": {
                        "name": {"title": [{"text": {"content": "Alice"}}]},
                        "aliases": {"rich_text": []},
                        "relationship": {"select": None},
                        "last_contact": {"date": None},
                    },
                }
            ],
            [],  # Bob not found
            [
                {
                    "id": "charlie-id",
                    "properties": {
                        "name": {"title": [{"text": {"content": "Charlie"}}]},
                        "aliases": {"rich_text": []},
                        "relationship": {"select": {"name": "friend"}},
                        "last_contact": {"date": None},
                    },
                }
            ],
        ]

        results = await service.lookup_multiple(["Alice", "Bob", "Charlie"])

        assert len(results) == 3
        assert results["Alice"].found is True
        assert results["Bob"].found is False
        assert results["Charlie"].found is True

    @pytest.mark.asyncio
    async def test_parse_results_handles_missing_fields(self, service, mock_notion_client):
        """parse_results should handle missing optional fields."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "minimal-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Minimal Person"}}]},
                    # Missing aliases, relationship, last_contact
                },
            }
        ]

        result = await service.lookup("Minimal")

        assert result.found is True
        assert result.matches[0].name == "Minimal Person"
        assert result.matches[0].aliases == []
        assert result.matches[0].relationship is None
        assert result.matches[0].last_contact is None

    @pytest.mark.asyncio
    async def test_parse_results_handles_empty_title(self, service, mock_notion_client):
        """parse_results should handle empty title list."""
        mock_notion_client.query_people.return_value = [
            {
                "id": "empty-name-id",
                "properties": {
                    "name": {"title": []},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": None},
                    "last_contact": {"date": None},
                },
            }
        ]

        result = await service.lookup("Empty")

        # Should still return result but with empty name
        assert result.found is True
        assert result.matches[0].name == ""


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock Notion client."""
        client = AsyncMock()
        client.query_people = AsyncMock(return_value=[])
        client.create_person = AsyncMock(return_value="new-id")
        return client

    def test_get_people_service_creates_instance(self, mock_notion_client):
        """get_people_service should create and cache a service instance."""
        service = get_people_service(mock_notion_client)
        assert isinstance(service, PeopleService)
        assert service.notion == mock_notion_client

    @pytest.mark.asyncio
    async def test_lookup_person_function(self, mock_notion_client):
        """lookup_person convenience function should work."""
        # Initialize the service with our mock
        get_people_service(mock_notion_client)
        mock_notion_client.query_people.return_value = [
            {
                "id": "test-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Test Person"}}]},
                    "aliases": {"rich_text": []},
                    "relationship": {"select": None},
                    "last_contact": {"date": None},
                },
            }
        ]

        result = await lookup_person("Test")

        assert result.found is True

    @pytest.mark.asyncio
    async def test_lookup_or_create_person_function(self, mock_notion_client):
        """lookup_or_create_person convenience function should work."""
        get_people_service(mock_notion_client)
        mock_notion_client.query_people.return_value = []

        result = await lookup_or_create_person("NewPerson")

        assert result.found is True
        assert result.is_new is True

    @pytest.mark.asyncio
    async def test_create_person_function(self, mock_notion_client):
        """create_person convenience function should work."""
        get_people_service(mock_notion_client)

        person = await create_person("Created", Relationship.FRIEND)

        assert person.name == "Created"
        assert person.relationship == Relationship.FRIEND
