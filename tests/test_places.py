"""Tests for the Places service.

Covers T-071: Implement Places lookup/create service
- Look up existing places by name/type
- Create new entries when needed
- Handle disambiguation for similar places
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import pytest

from assistant.services.places import (
    PlacesService,
    PlaceMatch,
    PlaceLookupResult,
    PlaceType,
    TYPE_PRIORITY,
    get_places_service,
    lookup_place,
    lookup_or_create_place,
    create_place,
)
from assistant.notion.schemas import Place


class TestPlaceMatch:
    """Tests for PlaceMatch dataclass."""

    def test_sort_by_confidence_descending(self):
        """Higher confidence should sort first."""
        match1 = PlaceMatch(place_id="1", name="Restaurant A", confidence=0.8)
        match2 = PlaceMatch(place_id="2", name="Restaurant B", confidence=0.9)

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Restaurant B"  # 0.9 confidence
        assert sorted_matches[1].name == "Restaurant A"  # 0.8 confidence

    def test_sort_by_recency_when_same_confidence(self):
        """When confidence is equal, more recent last_visit sorts first."""
        now = datetime.now()
        match1 = PlaceMatch(
            place_id="1",
            name="Cafe A",
            confidence=0.8,
            last_visit=now - timedelta(days=7),
        )
        match2 = PlaceMatch(
            place_id="2",
            name="Cafe B",
            confidence=0.8,
            last_visit=now - timedelta(days=1),
        )

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Cafe B"  # More recent visit

    def test_having_last_visit_beats_not_having(self):
        """Having last_visit is better than not having one."""
        match1 = PlaceMatch(place_id="1", name="Cafe A", confidence=0.8)
        match2 = PlaceMatch(
            place_id="2",
            name="Cafe B",
            confidence=0.8,
            last_visit=datetime.now(),
        )

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Cafe B"  # Has last_visit

    def test_higher_rating_preferred(self):
        """When confidence and last_visit are equal, higher rating wins."""
        match1 = PlaceMatch(place_id="1", name="Cafe A", confidence=0.8, rating=3)
        match2 = PlaceMatch(place_id="2", name="Cafe B", confidence=0.8, rating=5)

        sorted_matches = sorted([match1, match2])
        assert sorted_matches[0].name == "Cafe B"  # Higher rating


class TestPlaceLookupResult:
    """Tests for PlaceLookupResult dataclass."""

    def test_has_single_match_true(self):
        """has_single_match should be True for exactly one match."""
        result = PlaceLookupResult(
            found=True,
            place_id="123",
            matches=[PlaceMatch(place_id="123", name="The Coffee Shop", confidence=1.0)],
        )
        assert result.has_single_match is True

    def test_has_single_match_false_when_multiple(self):
        """has_single_match should be False for multiple matches."""
        result = PlaceLookupResult(
            found=True,
            place_id="123",
            matches=[
                PlaceMatch(place_id="123", name="Coffee Shop A", confidence=0.9),
                PlaceMatch(place_id="456", name="Coffee Shop B", confidence=0.7),
            ],
        )
        assert result.has_single_match is False

    def test_has_single_match_false_when_not_found(self):
        """has_single_match should be False when not found."""
        result = PlaceLookupResult(found=False)
        assert result.has_single_match is False


class TestPlacesService:
    """Tests for PlacesService class."""

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock Notion client."""
        client = AsyncMock()
        client.query_places = AsyncMock(return_value=[])
        client.create_place = AsyncMock(return_value="new-place-id")
        return client

    @pytest.fixture
    def service(self, mock_notion_client):
        """Create a PlacesService with mocked client."""
        return PlacesService(mock_notion_client)

    # -------------------------------------------
    # Lookup Tests
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_finds_existing_place_by_name(self, service, mock_notion_client):
        """When place exists, lookup returns the match."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "everyman-id-123",
                "properties": {
                    "name": {"title": [{"text": {"content": "Everyman Cinema"}}]},
                    "place_type": {"select": {"name": "cinema"}},
                    "address": {"rich_text": [{"text": {"content": "123 Main St"}}]},
                    "last_visit": {"date": None},
                    "rating": {"number": 4},
                },
            }
        ]

        result = await service.lookup("Everyman")

        assert result.found is True
        assert result.place_id == "everyman-id-123"
        assert len(result.matches) == 1
        assert result.matches[0].name == "Everyman Cinema"
        assert result.needs_disambiguation is False

    @pytest.mark.asyncio
    async def test_lookup_filters_by_type(self, service, mock_notion_client):
        """Lookup can filter by place type."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "pizza-place-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Joe's Pizza"}}]},
                    "place_type": {"select": {"name": "restaurant"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            }
        ]

        result = await service.lookup("Joe's", place_type="restaurant")

        assert result.found is True
        mock_notion_client.query_places.assert_called_once_with(
            name="Joe's", place_type="restaurant"
        )

    @pytest.mark.asyncio
    async def test_lookup_returns_not_found_when_no_match(self, service, mock_notion_client):
        """When no matches, lookup returns not found."""
        mock_notion_client.query_places.return_value = []

        result = await service.lookup("Nonexistent Place")

        assert result.found is False
        assert result.place_id is None
        assert len(result.matches) == 0

    @pytest.mark.asyncio
    async def test_lookup_exact_name_match_high_confidence(self, service, mock_notion_client):
        """Exact name match should have confidence 1.0."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "starbucks-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Starbucks"}}]},
                    "place_type": {"select": None},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            }
        ]

        result = await service.lookup("Starbucks")

        assert result.matches[0].confidence >= 0.99  # 1.0 + possible boost

    @pytest.mark.asyncio
    async def test_lookup_partial_name_match_lower_confidence(self, service, mock_notion_client):
        """Partial name match should have lower confidence."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "coffee-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Starbucks Coffee House"}}]},
                    "place_type": {"select": None},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            }
        ]

        result = await service.lookup("Starbucks")

        # Name starts with search term, should be ~0.9
        assert 0.85 <= result.matches[0].confidence <= 0.95

    @pytest.mark.asyncio
    async def test_lookup_address_match(self, service, mock_notion_client):
        """Can match by address content."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "office-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "WeWork"}}]},
                    "place_type": {"select": {"name": "office"}},
                    "address": {"rich_text": [{"text": {"content": "123 Market Street"}}]},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            }
        ]

        # Searching for address content
        result = await service.lookup("Market Street")

        assert result.found is True
        assert result.matches[0].matched_by == "address"

    # -------------------------------------------
    # Create Tests
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_or_create_creates_when_not_found(self, service, mock_notion_client):
        """When place not found, create new entry."""
        mock_notion_client.query_places.return_value = []

        result = await service.lookup_or_create("New Restaurant")

        assert result.found is True
        assert result.is_new is True
        mock_notion_client.create_place.assert_called_once()
        # Verify the place object was passed
        call_args = mock_notion_client.create_place.call_args
        place = call_args[0][0]
        assert place.name == "New Restaurant"

    @pytest.mark.asyncio
    async def test_lookup_or_create_with_type_and_address(self, service, mock_notion_client):
        """Created place should have type and address set."""
        mock_notion_client.query_places.return_value = []

        result = await service.lookup_or_create(
            "Mario's Pizzeria",
            place_type="restaurant",
            address="456 Oak Avenue",
            context="Great Italian food",
        )

        assert result.is_new is True
        call_args = mock_notion_client.create_place.call_args
        place = call_args[0][0]
        assert place.name == "Mario's Pizzeria"
        assert place.place_type == "restaurant"
        assert place.address == "456 Oak Avenue"
        assert place.notes == "Great Italian food"

    @pytest.mark.asyncio
    async def test_lookup_or_create_returns_existing_when_found(self, service, mock_notion_client):
        """When place exists, lookup_or_create returns existing."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "existing-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Existing Place"}}]},
                    "place_type": {"select": {"name": "venue"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            }
        ]

        result = await service.lookup_or_create("Existing Place")

        assert result.found is True
        assert result.is_new is False
        assert result.place_id == "existing-id"
        mock_notion_client.create_place.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_place(self, service, mock_notion_client):
        """create() should create a new place in Notion."""
        place = await service.create(
            "New Venue", "venue", "789 Concert Hall Drive", "Great acoustics"
        )

        assert place.name == "New Venue"
        assert place.place_type == "venue"
        assert place.address == "789 Concert Hall Drive"
        assert place.notes == "Great acoustics"
        assert place.id == "new-place-id"
        mock_notion_client.create_place.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_place_defaults_to_other_type(self, service, mock_notion_client):
        """create() should default to 'other' type when not specified."""
        place = await service.create("Mystery Location")

        assert place.place_type == "other"

    # -------------------------------------------
    # Disambiguation Tests
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_disambiguation_required_for_multiple_similar_matches(
        self, service, mock_notion_client
    ):
        """Multiple places with same name and similar confidence trigger disambiguation."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "coffee-1-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Downtown Coffee Shop"}}]},
                    "place_type": {"select": {"name": "restaurant"}},
                    "address": {"rich_text": [{"text": {"content": "123 Main St"}}]},
                    "last_visit": {"date": {"start": "2024-01-01T10:00:00Z"}},
                    "rating": {"number": 4},
                },
            },
            {
                "id": "coffee-2-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Uptown Coffee Shop"}}]},
                    "place_type": {"select": {"name": "restaurant"}},
                    "address": {"rich_text": [{"text": {"content": "456 Oak Ave"}}]},
                    "last_visit": {"date": {"start": "2024-01-05T10:00:00Z"}},
                    "rating": {"number": 5},
                },
            },
        ]

        result = await service.lookup("Coffee Shop")

        assert result.found is True
        assert len(result.matches) == 2
        # With lower confidence matches (~0.7), disambiguation should be triggered
        assert result.needs_disambiguation is True

    @pytest.mark.asyncio
    async def test_disambiguation_not_needed_for_home_or_office(
        self, service, mock_notion_client
    ):
        """Home/office places don't need disambiguation."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "home-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Home"}}]},
                    "place_type": {"select": {"name": "home"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            },
            {
                "id": "other-home-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Hometown Restaurant"}}]},
                    "place_type": {"select": {"name": "restaurant"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            },
        ]

        result = await service.lookup("Home")

        assert result.found is True
        assert result.needs_disambiguation is False
        assert result.place_id == "home-id"

    @pytest.mark.asyncio
    async def test_disambiguation_not_needed_for_office(self, service, mock_notion_client):
        """Office places don't need disambiguation."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "office-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "My Office"}}]},
                    "place_type": {"select": {"name": "office"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            },
            {
                "id": "other-office-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Other Office Building"}}]},
                    "place_type": {"select": {"name": "other"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            },
        ]

        result = await service.lookup("Office")

        assert result.found is True
        assert result.needs_disambiguation is False
        assert result.place_id == "office-id"

    @pytest.mark.asyncio
    async def test_disambiguation_not_needed_for_high_confidence_match(
        self, service, mock_notion_client
    ):
        """High confidence exact match doesn't need disambiguation."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "exact-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Everyman"}}]},
                    "place_type": {"select": {"name": "cinema"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            },
            {
                "id": "partial-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Everyman Cinema Maida Vale"}}]},
                    "place_type": {"select": {"name": "cinema"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            },
        ]

        result = await service.lookup("Everyman")

        assert result.found is True
        # Exact match "Everyman" should have very high confidence
        assert result.needs_disambiguation is False
        assert result.place_id == "exact-id"

    @pytest.mark.asyncio
    async def test_matches_sorted_by_confidence_and_recency(self, service, mock_notion_client):
        """Matches should be sorted by confidence then recency."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "old-visit-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Coffee A"}}]},
                    "place_type": {"select": {"name": "restaurant"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": {"start": "2023-01-01T10:00:00Z"}},
                    "rating": {"number": None},
                },
            },
            {
                "id": "recent-visit-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Coffee B"}}]},
                    "place_type": {"select": {"name": "restaurant"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": {"start": "2024-12-01T10:00:00Z"}},
                    "rating": {"number": None},
                },
            },
        ]

        result = await service.lookup("Coffee")

        # Matches should be sorted (most recent visit first for same confidence)
        assert len(result.matches) == 2
        # The more recently visited should come first
        assert result.matches[0].place_id == "recent-visit-id"

    # -------------------------------------------
    # Type Priority Tests
    # -------------------------------------------

    def test_type_priority_ordering(self):
        """Home should have highest priority, other lowest."""
        assert TYPE_PRIORITY[PlaceType.HOME] > TYPE_PRIORITY[PlaceType.OFFICE]
        assert TYPE_PRIORITY[PlaceType.OFFICE] > TYPE_PRIORITY[PlaceType.RESTAURANT]
        assert TYPE_PRIORITY[PlaceType.RESTAURANT] > TYPE_PRIORITY[PlaceType.CINEMA]
        assert TYPE_PRIORITY[PlaceType.CINEMA] > TYPE_PRIORITY[PlaceType.VENUE]
        assert TYPE_PRIORITY[PlaceType.VENUE] > TYPE_PRIORITY[PlaceType.OTHER]

    @pytest.mark.asyncio
    async def test_type_gives_confidence_boost(self, service, mock_notion_client):
        """High-priority types should get a confidence boost."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "home-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "My Home"}}]},
                    "place_type": {"select": {"name": "home"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            }
        ]

        result = await service.lookup("My")

        # Home type should boost confidence
        # Base partial match is ~0.7, home boost is +0.1
        assert result.matches[0].confidence > 0.7

    # -------------------------------------------
    # Edge Cases
    # -------------------------------------------

    @pytest.mark.asyncio
    async def test_lookup_without_notion_client(self):
        """Lookup without Notion client returns not found."""
        service = PlacesService(notion_client=None)

        result = await service.lookup("Anywhere")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_lookup_multiple_places(self, service, mock_notion_client):
        """lookup_multiple should look up each place."""
        mock_notion_client.query_places.side_effect = [
            [
                {
                    "id": "starbucks-id",
                    "properties": {
                        "name": {"title": [{"text": {"content": "Starbucks"}}]},
                        "place_type": {"select": None},
                        "address": {"rich_text": []},
                        "last_visit": {"date": None},
                        "rating": {"number": None},
                    },
                }
            ],
            [],  # Cafe not found
            [
                {
                    "id": "cinema-id",
                    "properties": {
                        "name": {"title": [{"text": {"content": "Everyman Cinema"}}]},
                        "place_type": {"select": {"name": "cinema"}},
                        "address": {"rich_text": []},
                        "last_visit": {"date": None},
                        "rating": {"number": None},
                    },
                }
            ],
        ]

        results = await service.lookup_multiple(["Starbucks", "Unknown Cafe", "Everyman"])

        assert len(results) == 3
        assert results["Starbucks"].found is True
        assert results["Unknown Cafe"].found is False
        assert results["Everyman"].found is True

    @pytest.mark.asyncio
    async def test_lookup_by_type(self, service, mock_notion_client):
        """lookup_by_type should return all places of that type."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "restaurant-1",
                "properties": {
                    "name": {"title": [{"text": {"content": "Pizza Place"}}]},
                    "place_type": {"select": {"name": "restaurant"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": 4},
                },
            },
            {
                "id": "restaurant-2",
                "properties": {
                    "name": {"title": [{"text": {"content": "Sushi Bar"}}]},
                    "place_type": {"select": {"name": "restaurant"}},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": 5},
                },
            },
        ]

        matches = await service.lookup_by_type("restaurant")

        assert len(matches) == 2
        mock_notion_client.query_places.assert_called_with(place_type="restaurant")

    @pytest.mark.asyncio
    async def test_parse_results_handles_missing_fields(self, service, mock_notion_client):
        """parse_results should handle missing optional fields."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "minimal-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Minimal Place"}}]},
                    # Missing place_type, address, last_visit, rating
                },
            }
        ]

        result = await service.lookup("Minimal")

        assert result.found is True
        assert result.matches[0].name == "Minimal Place"
        assert result.matches[0].place_type is None
        assert result.matches[0].address is None
        assert result.matches[0].last_visit is None
        assert result.matches[0].rating is None

    @pytest.mark.asyncio
    async def test_parse_results_handles_empty_title(self, service, mock_notion_client):
        """parse_results should handle empty title list."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "empty-name-id",
                "properties": {
                    "name": {"title": []},
                    "place_type": {"select": None},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
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
        client.query_places = AsyncMock(return_value=[])
        client.create_place = AsyncMock(return_value="new-id")
        return client

    def test_get_places_service_creates_instance(self, mock_notion_client):
        """get_places_service should create and cache a service instance."""
        service = get_places_service(mock_notion_client)
        assert isinstance(service, PlacesService)
        assert service.notion == mock_notion_client

    @pytest.mark.asyncio
    async def test_lookup_place_function(self, mock_notion_client):
        """lookup_place convenience function should work."""
        # Initialize the service with our mock
        get_places_service(mock_notion_client)
        mock_notion_client.query_places.return_value = [
            {
                "id": "test-id",
                "properties": {
                    "name": {"title": [{"text": {"content": "Test Place"}}]},
                    "place_type": {"select": None},
                    "address": {"rich_text": []},
                    "last_visit": {"date": None},
                    "rating": {"number": None},
                },
            }
        ]

        result = await lookup_place("Test")

        assert result.found is True

    @pytest.mark.asyncio
    async def test_lookup_or_create_place_function(self, mock_notion_client):
        """lookup_or_create_place convenience function should work."""
        get_places_service(mock_notion_client)
        mock_notion_client.query_places.return_value = []

        result = await lookup_or_create_place("NewPlace")

        assert result.found is True
        assert result.is_new is True

    @pytest.mark.asyncio
    async def test_create_place_function(self, mock_notion_client):
        """create_place convenience function should work."""
        get_places_service(mock_notion_client)

        place = await create_place("Created Place", "restaurant", "123 Main St")

        assert place.name == "Created Place"
        assert place.place_type == "restaurant"
        assert place.address == "123 Main St"
