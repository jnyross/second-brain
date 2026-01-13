"""Places service for lookup, creation, and matching.

This service handles:
- Looking up existing places by name or type
- Creating new places when they don't exist
- Matching places from extracted text to database entries
- Ranking matches by recency and confidence
- Geocoding places via Google Maps API (T-153)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from assistant.notion.schemas import Place

if TYPE_CHECKING:
    from assistant.google.maps import MapsClient
    from assistant.notion.client import NotionClient

logger = logging.getLogger(__name__)


class PlaceType(str, Enum):
    """Enumeration of place types."""

    RESTAURANT = "restaurant"
    CINEMA = "cinema"
    OFFICE = "office"
    HOME = "home"
    VENUE = "venue"
    OTHER = "other"


@dataclass
class PlaceMatch:
    """A potential match from the Places database."""

    place_id: str
    name: str
    confidence: float  # 0.0 to 1.0
    place_type: str | None = None
    address: str | None = None
    last_visit: datetime | None = None
    rating: int | None = None
    matched_by: str = "name"  # "name", "address", "type"

    def __lt__(self, other: "PlaceMatch") -> bool:
        """Sort by confidence descending, then recency."""
        if self.confidence != other.confidence:
            return self.confidence > other.confidence
        # If both have last_visit, more recent first
        if self.last_visit and other.last_visit:
            return self.last_visit > other.last_visit
        # Having last_visit is better than not
        if self.last_visit and not other.last_visit:
            return True
        # Higher rating preferred
        if self.rating is not None and other.rating is not None:
            return self.rating > other.rating
        return False


@dataclass
class PlaceLookupResult:
    """Result of a place lookup operation."""

    found: bool
    place_id: str | None = None
    place: Place | None = None
    matches: list[PlaceMatch] = field(default_factory=list)
    needs_disambiguation: bool = False
    is_new: bool = False

    @property
    def has_single_match(self) -> bool:
        return self.found and len(self.matches) == 1


# Type priority for disambiguation (higher = prefer)
TYPE_PRIORITY = {
    PlaceType.HOME: 100,
    PlaceType.OFFICE: 80,
    PlaceType.RESTAURANT: 60,
    PlaceType.CINEMA: 50,
    PlaceType.VENUE: 40,
    PlaceType.OTHER: 20,
}


@dataclass
class EnrichmentResult:
    """Result of place enrichment via Maps API."""

    success: bool
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    google_place_id: str | None = None
    phone: str | None = None
    website: str | None = None
    error: str | None = None

    @property
    def is_geocoded(self) -> bool:
        """Check if geocoding succeeded."""
        return self.lat is not None and self.lng is not None


class PlacesService:
    """Service for managing place entities."""

    def __init__(
        self,
        notion_client: "NotionClient | None" = None,
        maps_client: "MapsClient | None" = None,
    ):
        self.notion = notion_client
        self.maps = maps_client

    async def lookup(
        self,
        name: str,
        place_type: str | None = None,
    ) -> PlaceLookupResult:
        """Look up a place by name and optionally type.

        Args:
            name: The place name to search for
            place_type: Optional type filter (restaurant, cinema, etc.)

        Returns:
            PlaceLookupResult with matches and disambiguation info
        """
        if not self.notion:
            return PlaceLookupResult(found=False)

        # Query Notion for places matching name
        results = await self.notion.query_places(name=name, place_type=place_type)

        if not results:
            return PlaceLookupResult(found=False)

        matches = self._parse_results(results, name)

        if len(matches) == 0:
            return PlaceLookupResult(found=False)

        if len(matches) == 1:
            match = matches[0]
            return PlaceLookupResult(
                found=True,
                place_id=match.place_id,
                matches=matches,
                needs_disambiguation=False,
            )

        # Multiple matches - check if one is clearly better
        sorted_matches = sorted(matches)  # Uses __lt__ for sorting
        best = sorted_matches[0]

        # If best match has much higher confidence, use it
        if best.confidence >= 0.9:
            return PlaceLookupResult(
                found=True,
                place_id=best.place_id,
                matches=sorted_matches,
                needs_disambiguation=False,
            )

        # Check if one is home or office (high-priority places)
        for match in sorted_matches:
            if match.place_type in ("home", "office"):
                return PlaceLookupResult(
                    found=True,
                    place_id=match.place_id,
                    matches=sorted_matches,
                    needs_disambiguation=False,
                )

        # Multiple similar matches - needs disambiguation
        return PlaceLookupResult(
            found=True,
            place_id=best.place_id,  # Use best match as default
            matches=sorted_matches,
            needs_disambiguation=True,
        )

    async def lookup_or_create(
        self,
        name: str,
        place_type: str | None = None,
        address: str | None = None,
        context: str | None = None,
    ) -> PlaceLookupResult:
        """Look up a place, creating it if not found.

        Args:
            name: The place name to search for
            place_type: Optional type (restaurant, cinema, etc.)
            address: Optional address for new place
            context: Optional context about where this place was mentioned

        Returns:
            PlaceLookupResult with place info (found=True always)
        """
        result = await self.lookup(name, place_type)

        if result.found:
            return result

        # Create new place
        place = await self.create(name, place_type, address, context)

        return PlaceLookupResult(
            found=True,
            place_id=place.id if hasattr(place, "id") else None,
            place=place if isinstance(place, Place) else None,
            matches=[
                PlaceMatch(
                    place_id=place.id if hasattr(place, "id") else "",
                    name=name,
                    confidence=1.0,
                    place_type=place_type,
                    address=address,
                    matched_by="created",
                )
            ],
            is_new=True,
        )

    async def create(
        self,
        name: str,
        place_type: str | None = None,
        address: str | None = None,
        context: str | None = None,
    ) -> Place:
        """Create a new place.

        Args:
            name: Place name
            place_type: Type (restaurant, cinema, office, home, venue, other)
            address: Optional address
            context: Optional context for notes field

        Returns:
            Created Place object with ID from Notion
        """
        place = Place(
            name=name,
            place_type=place_type or "other",
            address=address,
            notes=context,
        )

        if self.notion:
            place_id = await self.notion.create_place(place)
            # Update the place object with the Notion-assigned ID
            place.id = place_id

        return place

    async def enrich(self, place: Place) -> EnrichmentResult:
        """Enrich a place with geocoding data from Google Maps API.

        Args:
            place: Place object to enrich (must have id for Notion update)

        Returns:
            EnrichmentResult with geocoding data or error
        """
        if not self.maps:
            return EnrichmentResult(success=False, error="Maps client not configured")

        # Build search query from name and address
        search_query = place.name
        if place.address:
            search_query = f"{place.name}, {place.address}"

        try:
            # Use enrich_place which does search + detailed lookup
            place_details = await self.maps.enrich_place(search_query)

            if not place_details:
                return EnrichmentResult(
                    success=False,
                    error=f"No results found for '{search_query}'",
                )

            result = EnrichmentResult(
                success=True,
                address=place_details.address,
                lat=place_details.lat,
                lng=place_details.lng,
                google_place_id=place_details.place_id,
                phone=place_details.phone,
                website=place_details.website,
            )

            # Update Notion if we have a place ID and client
            if place.id and self.notion:
                await self.notion.update_place(
                    place_id=place.id,
                    address=result.address,
                    lat=result.lat,
                    lng=result.lng,
                    google_place_id=result.google_place_id,
                    phone=result.phone,
                    website=result.website,
                )
                logger.info(f"Enriched place '{place.name}' with geocoding data")

            return result

        except Exception as e:
            logger.error(f"Failed to enrich place '{place.name}': {e}")
            return EnrichmentResult(success=False, error=str(e))

    async def create_enriched(
        self,
        name: str,
        place_type: str | None = None,
        address: str | None = None,
        context: str | None = None,
    ) -> tuple[Place, EnrichmentResult | None]:
        """Create a new place and enrich with Maps API data.

        Args:
            name: Place name
            place_type: Type (restaurant, cinema, office, home, venue, other)
            address: Optional address
            context: Optional context for notes field

        Returns:
            Tuple of (Place, EnrichmentResult or None if Maps not configured)
        """
        # Create the place first
        place = await self.create(name, place_type, address, context)

        # Enrich if Maps client is available
        enrichment = None
        if self.maps:
            enrichment = await self.enrich(place)
            # Update local place object with enriched data
            if enrichment.success:
                place.address = enrichment.address or place.address
                place.lat = enrichment.lat
                place.lng = enrichment.lng
                place.google_place_id = enrichment.google_place_id
                place.phone = enrichment.phone
                place.website = enrichment.website

        return place, enrichment

    async def lookup_or_create_enriched(
        self,
        name: str,
        place_type: str | None = None,
        address: str | None = None,
        context: str | None = None,
    ) -> tuple[PlaceLookupResult, EnrichmentResult | None]:
        """Look up a place, creating and enriching it if not found.

        This is the main entry point for AT-121 - when a place is mentioned,
        geocode via Maps API and store enriched data in Notion.

        Args:
            name: The place name to search for
            place_type: Optional type (restaurant, cinema, etc.)
            address: Optional address for new place
            context: Optional context about where this place was mentioned

        Returns:
            Tuple of (PlaceLookupResult, EnrichmentResult or None)
        """
        result = await self.lookup(name, place_type)

        if result.found:
            # Check if existing place needs enrichment
            enrichment = None
            if self.maps and result.place_id:
                # TODO: Check if place already has coordinates before enriching
                # For now, we don't re-enrich existing places
                pass
            return result, enrichment

        # Create and enrich new place
        place, enrichment = await self.create_enriched(name, place_type, address, context)

        lookup_result = PlaceLookupResult(
            found=True,
            place_id=place.id if hasattr(place, "id") else None,
            place=place,
            matches=[
                PlaceMatch(
                    place_id=place.id if hasattr(place, "id") else "",
                    name=name,
                    confidence=1.0,
                    place_type=place_type,
                    address=enrichment.address if enrichment and enrichment.success else address,
                    matched_by="created",
                )
            ],
            is_new=True,
        )

        return lookup_result, enrichment

    async def lookup_multiple(
        self,
        names: list[str],
    ) -> dict[str, PlaceLookupResult]:
        """Look up multiple places.

        Args:
            names: List of place names to search for

        Returns:
            Dict mapping name to PlaceLookupResult
        """
        results = {}
        for name in names:
            results[name] = await self.lookup(name)
        return results

    async def lookup_by_type(
        self,
        place_type: str,
    ) -> list[PlaceMatch]:
        """Look up all places of a specific type.

        Args:
            place_type: Type to filter by (restaurant, cinema, etc.)

        Returns:
            List of PlaceMatch objects
        """
        if not self.notion:
            return []

        results = await self.notion.query_places(place_type=place_type)
        return self._parse_results(results, "")

    async def get_by_id(self, place_id: str) -> Place | None:
        """Get a place by its Notion page ID.

        Args:
            place_id: Notion page ID

        Returns:
            Place object or None if not found
        """
        if not self.notion:
            return None

        # TODO: Implement direct page fetch in NotionClient
        return None

    async def update_last_visit(self, place_id: str) -> None:
        """Update the last_visit timestamp for a place.

        Args:
            place_id: Notion page ID of the place
        """
        if not self.notion:
            return

        # TODO: Implement page update in NotionClient
        pass

    def _parse_results(
        self,
        results: list[dict],
        search_name: str,
    ) -> list[PlaceMatch]:
        """Parse Notion query results into PlaceMatch objects.

        Args:
            results: Raw Notion API results
            search_name: Original search term

        Returns:
            List of PlaceMatch objects
        """
        matches = []
        search_lower = search_name.lower()

        for result in results:
            props = result.get("properties", {})

            # Extract name
            name_prop = props.get("name", {})
            title_list = name_prop.get("title", [])
            name = title_list[0]["text"]["content"] if title_list else ""

            # Extract place_type
            type_prop = props.get("place_type", {})
            type_select = type_prop.get("select")
            place_type = type_select["name"] if type_select else None

            # Extract address
            address_prop = props.get("address", {})
            address_text = address_prop.get("rich_text", [])
            address = address_text[0]["text"]["content"] if address_text else None

            # Extract last_visit
            last_visit_prop = props.get("last_visit", {})
            last_visit_date = last_visit_prop.get("date")
            last_visit = None
            if last_visit_date and last_visit_date.get("start"):
                try:
                    last_visit = datetime.fromisoformat(
                        last_visit_date["start"].replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            # Extract rating
            rating_prop = props.get("rating", {})
            rating = rating_prop.get("number")

            # Calculate confidence
            confidence, matched_by = self._calculate_match_confidence(
                search_lower, name, address, place_type
            )

            matches.append(
                PlaceMatch(
                    place_id=result["id"],
                    name=name,
                    confidence=confidence,
                    place_type=place_type,
                    address=address,
                    last_visit=last_visit,
                    rating=rating,
                    matched_by=matched_by,
                )
            )

        return matches

    def _calculate_match_confidence(
        self,
        search: str,
        name: str,
        address: str | None,
        place_type: str | None,
    ) -> tuple[float, str]:
        """Calculate match confidence score.

        Args:
            search: Lowercase search term
            name: Place name
            address: Place address
            place_type: Place type

        Returns:
            Tuple of (confidence score, matched_by field)
        """
        if not search:
            # No search term, return base confidence
            return 0.5, "type"

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
        # Check address
        elif address and search in address.lower():
            confidence = 0.6
            matched_by = "address"
        else:
            # Fuzzy match - search word appears somewhere
            confidence = 0.5
            matched_by = "partial"

        # Boost for frequent place types
        if place_type:
            try:
                type_enum = PlaceType(place_type)
                if type_enum in TYPE_PRIORITY:
                    boost = TYPE_PRIORITY[type_enum] / 1000  # Small boost
                    confidence = min(1.0, confidence + boost)
            except ValueError:
                pass

        return confidence, matched_by


# Convenience functions for module-level access
_service: PlacesService | None = None


def get_places_service(
    notion_client: "NotionClient | None" = None,
    maps_client: "MapsClient | None" = None,
) -> PlacesService:
    """Get or create a PlacesService instance."""
    global _service
    if _service is None or notion_client is not None or maps_client is not None:
        _service = PlacesService(notion_client, maps_client)
    return _service


async def lookup_place(
    name: str,
    place_type: str | None = None,
) -> PlaceLookupResult:
    """Look up a place by name."""
    return await get_places_service().lookup(name, place_type)


async def lookup_or_create_place(
    name: str,
    place_type: str | None = None,
    address: str | None = None,
    context: str | None = None,
) -> PlaceLookupResult:
    """Look up a place, creating it if not found."""
    return await get_places_service().lookup_or_create(name, place_type, address, context)


async def lookup_or_create_place_enriched(
    name: str,
    place_type: str | None = None,
    address: str | None = None,
    context: str | None = None,
) -> tuple[PlaceLookupResult, EnrichmentResult | None]:
    """Look up a place, creating and enriching it if not found."""
    return await get_places_service().lookup_or_create_enriched(name, place_type, address, context)


async def create_place(
    name: str,
    place_type: str | None = None,
    address: str | None = None,
    context: str | None = None,
) -> Place:
    """Create a new place."""
    return await get_places_service().create(name, place_type, address, context)


async def create_place_enriched(
    name: str,
    place_type: str | None = None,
    address: str | None = None,
    context: str | None = None,
) -> tuple[Place, EnrichmentResult | None]:
    """Create a new place and enrich with Maps API data."""
    return await get_places_service().create_enriched(name, place_type, address, context)


async def enrich_place(place: Place) -> EnrichmentResult:
    """Enrich a place with geocoding data from Google Maps API."""
    return await get_places_service().enrich(place)
