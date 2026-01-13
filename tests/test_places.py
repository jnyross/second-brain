"""Tests for the Places service.

Covers T-071: Implement Places lookup/create service
- Look up existing places by name/type
- Create new entries when needed
- Handle disambiguation for similar places

Covers T-153: Integrate Maps with Places database
- Geocode places via Google Maps API
- Store enriched data (lat/lng, address, phone, website) in Notion
- AT-121: Place enrichment via Maps API
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.services.places import (
    TYPE_PRIORITY,
    EnrichmentResult,
    PlaceLookupResult,
    PlaceMatch,
    PlacesService,
    PlaceType,
    create_place,
    get_places_service,
    lookup_or_create_place,
    lookup_place,
)


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
    async def test_disambiguation_not_needed_for_home_or_office(self, service, mock_notion_client):
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


# =============================================================================
# T-153: Maps Integration Tests
# =============================================================================


class TestEnrichmentResult:
    """Tests for EnrichmentResult dataclass."""

    def test_is_geocoded_true_when_coordinates_present(self):
        """is_geocoded should be True when lat/lng are set."""
        result = EnrichmentResult(
            success=True,
            lat=37.7749,
            lng=-122.4194,
        )
        assert result.is_geocoded is True

    def test_is_geocoded_false_when_no_lat(self):
        """is_geocoded should be False when lat is missing."""
        result = EnrichmentResult(
            success=True,
            lng=-122.4194,
        )
        assert result.is_geocoded is False

    def test_is_geocoded_false_when_no_lng(self):
        """is_geocoded should be False when lng is missing."""
        result = EnrichmentResult(
            success=True,
            lat=37.7749,
        )
        assert result.is_geocoded is False

    def test_is_geocoded_false_when_failed(self):
        """is_geocoded should be False when enrichment failed."""
        result = EnrichmentResult(success=False, error="No results found")
        assert result.is_geocoded is False

    def test_enrichment_result_with_all_fields(self):
        """EnrichmentResult should store all Maps API fields."""
        result = EnrichmentResult(
            success=True,
            address="315 Linden St, San Francisco, CA 94102",
            lat=37.7749,
            lng=-122.4194,
            google_place_id="ChIJrTLr-GyuEmsRBfy61i59si0",
            phone="+1 415-555-1234",
            website="https://bluebottlecoffee.com",
        )
        assert result.success is True
        assert result.address == "315 Linden St, San Francisco, CA 94102"
        assert result.lat == 37.7749
        assert result.lng == -122.4194
        assert result.google_place_id == "ChIJrTLr-GyuEmsRBfy61i59si0"
        assert result.phone == "+1 415-555-1234"
        assert result.website == "https://bluebottlecoffee.com"


class TestPlacesServiceMapsIntegration:
    """Tests for PlacesService with Maps API integration (T-153)."""

    @pytest.fixture
    def mock_maps_client(self):
        """Create a mock MapsClient."""
        from assistant.google.maps import PlaceDetails

        client = MagicMock()
        client.enrich_place = AsyncMock(
            return_value=PlaceDetails(
                name="Blue Bottle Coffee",
                address="315 Linden St, San Francisco, CA 94102",
                lat=37.7749,
                lng=-122.4194,
                place_id="ChIJrTLr-GyuEmsRBfy61i59si0",
                phone="+1 415-555-1234",
                website="https://bluebottlecoffee.com",
            )
        )
        return client

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock NotionClient."""
        client = AsyncMock()
        client.create_place = AsyncMock(return_value="place-123")
        client.update_place = AsyncMock()
        client.query_places = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_enrich_without_maps_client(self, mock_notion_client):
        """enrich should return error when Maps client not configured."""
        from assistant.notion.schemas import Place

        service = PlacesService(notion_client=mock_notion_client, maps_client=None)
        place = Place(id="place-123", name="Test Place")

        result = await service.enrich(place)

        assert result.success is False
        assert result.error == "Maps client not configured"

    @pytest.mark.asyncio
    async def test_enrich_calls_maps_api(self, mock_notion_client, mock_maps_client):
        """enrich should call Maps API with place name."""
        from assistant.notion.schemas import Place

        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)
        place = Place(id="place-123", name="Blue Bottle Coffee")

        result = await service.enrich(place)

        mock_maps_client.enrich_place.assert_called_once_with("Blue Bottle Coffee")
        assert result.success is True
        assert result.lat == 37.7749
        assert result.lng == -122.4194

    @pytest.mark.asyncio
    async def test_enrich_uses_address_in_query(self, mock_notion_client, mock_maps_client):
        """enrich should include address in Maps API query when available."""
        from assistant.notion.schemas import Place

        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)
        place = Place(id="place-123", name="Blue Bottle Coffee", address="Hayes Valley, SF")

        await service.enrich(place)

        mock_maps_client.enrich_place.assert_called_once_with(
            "Blue Bottle Coffee, Hayes Valley, SF"
        )

    @pytest.mark.asyncio
    async def test_enrich_updates_notion(self, mock_notion_client, mock_maps_client):
        """enrich should update Notion with geocoding data."""
        from assistant.notion.schemas import Place

        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)
        place = Place(id="place-123", name="Blue Bottle Coffee")

        await service.enrich(place)

        mock_notion_client.update_place.assert_called_once_with(
            place_id="place-123",
            address="315 Linden St, San Francisco, CA 94102",
            lat=37.7749,
            lng=-122.4194,
            google_place_id="ChIJrTLr-GyuEmsRBfy61i59si0",
            phone="+1 415-555-1234",
            website="https://bluebottlecoffee.com",
        )

    @pytest.mark.asyncio
    async def test_enrich_handles_no_results(self, mock_notion_client, mock_maps_client):
        """enrich should handle when Maps API returns no results."""
        from assistant.notion.schemas import Place

        mock_maps_client.enrich_place.return_value = None

        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)
        place = Place(id="place-123", name="Nonexistent Place XYZ123")

        result = await service.enrich(place)

        assert result.success is False
        assert "No results found" in result.error

    @pytest.mark.asyncio
    async def test_enrich_handles_api_error(self, mock_notion_client, mock_maps_client):
        """enrich should handle Maps API errors gracefully."""
        from assistant.notion.schemas import Place

        mock_maps_client.enrich_place.side_effect = Exception("API quota exceeded")

        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)
        place = Place(id="place-123", name="Blue Bottle Coffee")

        result = await service.enrich(place)

        assert result.success is False
        assert "API quota exceeded" in result.error


class TestCreateEnriched:
    """Tests for create_enriched method."""

    @pytest.fixture
    def mock_maps_client(self):
        """Create a mock MapsClient."""
        from assistant.google.maps import PlaceDetails

        client = MagicMock()
        client.enrich_place = AsyncMock(
            return_value=PlaceDetails(
                name="Blue Bottle Coffee",
                address="315 Linden St, San Francisco, CA 94102",
                lat=37.7749,
                lng=-122.4194,
                place_id="ChIJrTLr-GyuEmsRBfy61i59si0",
                phone=None,
                website=None,
            )
        )
        return client

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock NotionClient."""
        client = AsyncMock()
        client.create_place = AsyncMock(return_value="place-456")
        client.update_place = AsyncMock()
        client.query_places = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_create_enriched_creates_and_enriches(self, mock_notion_client, mock_maps_client):
        """create_enriched should create place and enrich it."""
        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)

        place, enrichment = await service.create_enriched(
            name="Blue Bottle Coffee",
            place_type="restaurant",
        )

        assert place.name == "Blue Bottle Coffee"
        assert place.id == "place-456"
        assert enrichment is not None
        assert enrichment.success is True
        assert place.lat == 37.7749
        assert place.lng == -122.4194

    @pytest.mark.asyncio
    async def test_create_enriched_without_maps(self, mock_notion_client):
        """create_enriched should create place without enrichment when Maps not configured."""
        service = PlacesService(notion_client=mock_notion_client, maps_client=None)

        place, enrichment = await service.create_enriched(
            name="Test Place",
            place_type="other",
        )

        assert place.name == "Test Place"
        assert enrichment is None
        assert place.lat is None
        assert place.lng is None


class TestLookupOrCreateEnriched:
    """Tests for lookup_or_create_enriched method."""

    @pytest.fixture
    def mock_maps_client(self):
        """Create a mock MapsClient."""
        from assistant.google.maps import PlaceDetails

        client = MagicMock()
        client.enrich_place = AsyncMock(
            return_value=PlaceDetails(
                name="Blue Bottle Coffee",
                address="315 Linden St, San Francisco, CA 94102",
                lat=37.7749,
                lng=-122.4194,
                place_id="ChIJrTLr-GyuEmsRBfy61i59si0",
                phone=None,
                website=None,
            )
        )
        return client

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock NotionClient."""
        client = AsyncMock()
        client.create_place = AsyncMock(return_value="place-789")
        client.update_place = AsyncMock()
        client.query_places = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_lookup_or_create_enriched_creates_new(
        self, mock_notion_client, mock_maps_client
    ):
        """Should create and enrich when place not found."""
        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)

        result, enrichment = await service.lookup_or_create_enriched(
            name="Blue Bottle Coffee",
            place_type="restaurant",
        )

        assert result.found is True
        assert result.is_new is True
        assert result.place_id == "place-789"
        assert enrichment is not None
        assert enrichment.success is True
        assert enrichment.lat == 37.7749

    @pytest.mark.asyncio
    async def test_lookup_or_create_enriched_finds_existing(
        self, mock_notion_client, mock_maps_client
    ):
        """Should return existing place without enrichment."""
        mock_notion_client.query_places.return_value = [
            {
                "id": "existing-place-123",
                "properties": {
                    "name": {"title": [{"text": {"content": "Blue Bottle Coffee"}}]},
                    "place_type": {"select": {"name": "restaurant"}},
                    "address": {"rich_text": [{"text": {"content": "315 Linden St, SF"}}]},
                },
            }
        ]

        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)

        result, enrichment = await service.lookup_or_create_enriched(name="Blue Bottle Coffee")

        assert result.found is True
        assert result.is_new is False
        assert result.place_id == "existing-place-123"
        assert enrichment is None  # No enrichment for existing places


# =============================================================================
# AT-121: Place Enrichment via Maps API
# =============================================================================


class TestAT121PlaceEnrichmentViaMapsAPI:
    """Acceptance tests for AT-121: Place Enrichment via Maps API.

    Given: User sends "Meet Dave at Blue Bottle Coffee tomorrow"
    When: Google Maps API enabled
    Then: Place geocoded and enriched with address, lat/lng
    """

    @pytest.fixture
    def mock_maps_client(self):
        """Create a mock MapsClient with realistic response."""
        from assistant.google.maps import PlaceDetails

        client = MagicMock()
        client.enrich_place = AsyncMock(
            return_value=PlaceDetails(
                name="Blue Bottle Coffee",
                address="315 Linden St, San Francisco, CA 94102, USA",
                lat=37.7765,
                lng=-122.4216,
                place_id="ChIJrTLr-GyuEmsRBfy61i59si0",
                phone="+1 415-653-3394",
                website="https://bluebottlecoffee.com/cafes/hayes-valley",
            )
        )
        return client

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock NotionClient."""
        client = AsyncMock()
        client.create_place = AsyncMock(return_value="notion-place-id-abc")
        client.update_place = AsyncMock()
        client.query_places = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_at121_place_geocoded_when_maps_enabled(
        self, mock_notion_client, mock_maps_client
    ):
        """AT-121: Place should be geocoded when Maps API is enabled."""
        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)

        # Simulate: User mentioned "Blue Bottle Coffee" in a message
        result, enrichment = await service.lookup_or_create_enriched(
            name="Blue Bottle Coffee",
            place_type="restaurant",
            context="Meet Dave at Blue Bottle Coffee tomorrow",
        )

        # Verify place was created and geocoded
        assert result.found is True
        assert result.is_new is True
        assert enrichment is not None
        assert enrichment.success is True

    @pytest.mark.asyncio
    async def test_at121_enriched_with_address(self, mock_notion_client, mock_maps_client):
        """AT-121: Place should have formatted address from Maps API."""
        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)

        _, enrichment = await service.lookup_or_create_enriched(name="Blue Bottle Coffee")

        assert enrichment.address == "315 Linden St, San Francisco, CA 94102, USA"

    @pytest.mark.asyncio
    async def test_at121_enriched_with_coordinates(self, mock_notion_client, mock_maps_client):
        """AT-121: Place should have lat/lng coordinates from Maps API."""
        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)

        _, enrichment = await service.lookup_or_create_enriched(name="Blue Bottle Coffee")

        assert enrichment.lat == 37.7765
        assert enrichment.lng == -122.4216
        assert enrichment.is_geocoded is True

    @pytest.mark.asyncio
    async def test_at121_notion_updated_with_enrichment(self, mock_notion_client, mock_maps_client):
        """AT-121: Notion should be updated with geocoding data."""
        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)

        await service.lookup_or_create_enriched(name="Blue Bottle Coffee")

        # Verify Notion update was called with enriched data
        mock_notion_client.update_place.assert_called_once()
        call_kwargs = mock_notion_client.update_place.call_args.kwargs
        assert call_kwargs["lat"] == 37.7765
        assert call_kwargs["lng"] == -122.4216
        assert call_kwargs["google_place_id"] == "ChIJrTLr-GyuEmsRBfy61i59si0"

    @pytest.mark.asyncio
    async def test_at121_phone_and_website_stored(self, mock_notion_client, mock_maps_client):
        """AT-121: Phone and website should be stored if available."""
        service = PlacesService(notion_client=mock_notion_client, maps_client=mock_maps_client)

        _, enrichment = await service.lookup_or_create_enriched(name="Blue Bottle Coffee")

        assert enrichment.phone == "+1 415-653-3394"
        assert enrichment.website == "https://bluebottlecoffee.com/cafes/hayes-valley"

        # Verify Notion update includes phone and website
        call_kwargs = mock_notion_client.update_place.call_args.kwargs
        assert call_kwargs["phone"] == "+1 415-653-3394"
        assert call_kwargs["website"] == "https://bluebottlecoffee.com/cafes/hayes-valley"


class TestPlaceSchemaCoordinates:
    """Tests for Place schema coordinate properties."""

    def test_place_coordinates_property(self):
        """Place.coordinates should return (lat, lng) tuple."""
        from assistant.notion.schemas import Place

        place = Place(name="Test", lat=37.7749, lng=-122.4194)
        assert place.coordinates == (37.7749, -122.4194)

    def test_place_coordinates_none_when_missing_lat(self):
        """Place.coordinates should be None when lat is missing."""
        from assistant.notion.schemas import Place

        place = Place(name="Test", lng=-122.4194)
        assert place.coordinates is None

    def test_place_coordinates_none_when_missing_lng(self):
        """Place.coordinates should be None when lng is missing."""
        from assistant.notion.schemas import Place

        place = Place(name="Test", lat=37.7749)
        assert place.coordinates is None

    def test_place_is_geocoded_true(self):
        """Place.is_geocoded should be True when both coordinates set."""
        from assistant.notion.schemas import Place

        place = Place(name="Test", lat=37.7749, lng=-122.4194)
        assert place.is_geocoded is True

    def test_place_is_geocoded_false(self):
        """Place.is_geocoded should be False when coordinates missing."""
        from assistant.notion.schemas import Place

        place = Place(name="Test")
        assert place.is_geocoded is False

    def test_place_google_place_id_field(self):
        """Place should have google_place_id field."""
        from assistant.notion.schemas import Place

        place = Place(
            name="Blue Bottle Coffee",
            google_place_id="ChIJrTLr-GyuEmsRBfy61i59si0",
        )
        assert place.google_place_id == "ChIJrTLr-GyuEmsRBfy61i59si0"

    def test_place_phone_and_website_fields(self):
        """Place should have phone and website fields."""
        from assistant.notion.schemas import Place

        place = Place(
            name="Blue Bottle Coffee",
            phone="+1 415-555-1234",
            website="https://bluebottlecoffee.com",
        )
        assert place.phone == "+1 415-555-1234"
        assert place.website == "https://bluebottlecoffee.com"
