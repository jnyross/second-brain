"""Proximity task suggestions service.

This service answers "What can I do near X?" queries by:
1. Geocoding the query location
2. Finding tasks that have associated places
3. Calculating distances from query location to task places
4. Returning tasks sorted by distance

Implements AT-127: Proximity Task Suggestions.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from assistant.google.maps import MapsClient, TravelTime
    from assistant.notion.client import NotionClient

logger = logging.getLogger(__name__)

# Pattern matchers for proximity queries
PROXIMITY_PATTERNS = [
    "what can i do near",
    "what tasks near",
    "tasks near",
    "things to do near",
    "errands near",
    "what's nearby",
    "what is nearby",
    "nearby tasks",
]

# Maximum distance in meters to consider "nearby" (5km default)
MAX_NEARBY_DISTANCE_METERS = 5000


@dataclass
class NearbyTask:
    """A task with distance information."""

    task_id: str
    title: str
    status: str
    priority: str | None
    due_date: str | None
    place_id: str
    place_name: str
    place_address: str | None
    distance_meters: int
    duration_seconds: int | None = None

    @property
    def distance_km(self) -> float:
        """Distance in kilometers."""
        return self.distance_meters / 1000

    @property
    def distance_display(self) -> str:
        """Human-readable distance string."""
        km = self.distance_km
        if km < 1:
            return f"{self.distance_meters}m"
        return f"{km:.1f}km"

    @property
    def duration_display(self) -> str | None:
        """Human-readable duration string."""
        if self.duration_seconds is None:
            return None
        mins = self.duration_seconds // 60
        if mins < 60:
            return f"{mins} min"
        hours = mins // 60
        remaining = mins % 60
        if remaining == 0:
            return f"{hours} hr"
        return f"{hours} hr {remaining} min"


@dataclass
class ProximityResult:
    """Result of a proximity query."""

    success: bool
    query_location: str
    query_lat: float | None = None
    query_lng: float | None = None
    tasks: list[NearbyTask] = field(default_factory=list)
    error: str | None = None

    @property
    def task_count(self) -> int:
        """Number of nearby tasks found."""
        return len(self.tasks)

    @property
    def has_tasks(self) -> bool:
        """Whether any nearby tasks were found."""
        return len(self.tasks) > 0

    def format_response(self) -> str:
        """Format the result as a user-friendly message."""
        if not self.success:
            return f"Sorry, I couldn't find that location: {self.error}"

        if not self.has_tasks:
            return f"No tasks found near {self.query_location}."

        lines = [f"📍 Tasks near {self.query_location}:"]
        lines.append("")

        for task in self.tasks:
            # Priority indicator
            priority_icon = ""
            if task.priority in ("urgent", "high"):
                priority_icon = "🔴 "

            # Distance info
            distance_info = f"({task.distance_display}"
            if task.duration_display:
                distance_info += f", {task.duration_display}"
            distance_info += ")"

            lines.append(f"• {priority_icon}{task.title} {distance_info}")
            if task.place_name:
                lines.append(f"  📍 {task.place_name}")

        return "\n".join(lines)


def is_proximity_query(text: str) -> bool:
    """Check if text is a proximity query.

    Args:
        text: User input text

    Returns:
        True if this looks like a proximity query
    """
    text_lower = text.lower().strip()
    return any(pattern in text_lower for pattern in PROXIMITY_PATTERNS)


def extract_location_from_query(text: str) -> str | None:
    """Extract the location from a proximity query.

    Args:
        text: User input like "What can I do near Union Square?"

    Returns:
        Location string or None if not found
    """
    text_lower = text.lower().strip()

    for pattern in PROXIMITY_PATTERNS:
        if pattern in text_lower:
            # Find where the pattern ends and extract the rest
            idx = text_lower.find(pattern)
            location = text[idx + len(pattern) :].strip()

            # Remove trailing punctuation
            location = location.rstrip("?!.,")

            if location:
                return location

    return None


def haversine_distance(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> float:
    """Calculate the great-circle distance between two points in meters.

    Uses the Haversine formula for accuracy on Earth's surface.

    Args:
        lat1, lng1: First point coordinates
        lat2, lng2: Second point coordinates

    Returns:
        Distance in meters
    """
    R = 6371000  # Earth's radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


class ProximityTaskService:
    """Service for finding tasks near a location."""

    def __init__(
        self,
        notion_client: "NotionClient | None" = None,
        maps_client: "MapsClient | None" = None,
        max_distance_meters: int = MAX_NEARBY_DISTANCE_METERS,
    ):
        self.notion = notion_client
        self.maps = maps_client
        self.max_distance = max_distance_meters

    async def find_tasks_near(
        self,
        location: str,
        max_results: int = 10,
        include_travel_time: bool = True,
    ) -> ProximityResult:
        """Find tasks near a location.

        Args:
            location: Location query (e.g., "Union Square" or "123 Main St")
            max_results: Maximum number of tasks to return
            include_travel_time: Whether to calculate travel times (requires Maps API)

        Returns:
            ProximityResult with nearby tasks sorted by distance
        """
        if not self.maps:
            return ProximityResult(
                success=False,
                query_location=location,
                error="Maps client not configured",
            )

        if not self.notion:
            return ProximityResult(
                success=False,
                query_location=location,
                error="Notion client not configured",
            )

        # Step 1: Geocode the query location
        query_place = await self.maps.geocode(location)
        if not query_place:
            return ProximityResult(
                success=False,
                query_location=location,
                error=f"Could not find location: {location}",
            )

        query_lat = query_place.lat
        query_lng = query_place.lng
        logger.info(f"Geocoded '{location}' to ({query_lat}, {query_lng})")

        # Step 2: Query all active tasks
        tasks = await self.notion.query_tasks(
            exclude_statuses=["done", "cancelled", "deleted"],
            include_deleted=False,
        )

        # Step 3: Find tasks with places and calculate distances
        nearby_tasks: list[NearbyTask] = []

        for task_data in tasks:
            props = task_data.get("properties", {})
            task_id = task_data.get("id", "")

            # Extract task details
            title_prop = props.get("title", {})
            title_list = title_prop.get("title", [])
            title = title_list[0]["text"]["content"] if title_list else "Untitled"

            status_prop = props.get("status", {})
            status_select = status_prop.get("select")
            status = status_select["name"] if status_select else "todo"

            priority_prop = props.get("priority", {})
            priority_select = priority_prop.get("select")
            priority = priority_select["name"] if priority_select else None

            due_date_prop = props.get("due_date", {})
            due_date_data = due_date_prop.get("date")
            due_date = due_date_data.get("start") if due_date_data else None

            # Extract place_ids (relation property)
            place_ids_prop = props.get("place_ids", {})
            place_relations = place_ids_prop.get("relation", [])
            place_ids = [rel["id"] for rel in place_relations if "id" in rel]

            if not place_ids:
                # Task has no associated place
                continue

            # Get place details for the first place (primary location)
            # TODO: Handle multiple places per task
            place_id = place_ids[0]
            place_data = await self.notion.get_place(place_id)

            if not place_data:
                logger.warning(f"Could not fetch place {place_id} for task {task_id}")
                continue

            place_props = place_data.get("properties", {})

            # Extract place name
            place_name_prop = place_props.get("name", {})
            place_name_list = place_name_prop.get("title", [])
            place_name = place_name_list[0]["text"]["content"] if place_name_list else ""

            # Extract place address
            place_address_prop = place_props.get("address", {})
            place_address_text = place_address_prop.get("rich_text", [])
            place_address = (
                place_address_text[0]["text"]["content"] if place_address_text else None
            )

            # Extract place coordinates
            lat_prop = place_props.get("lat", {})
            place_lat = lat_prop.get("number")

            lng_prop = place_props.get("lng", {})
            place_lng = lng_prop.get("number")

            if place_lat is None or place_lng is None:
                # Place not geocoded - try to geocode it now
                if place_address:
                    place_details = await self.maps.geocode(place_address)
                    if place_details:
                        place_lat = place_details.lat
                        place_lng = place_details.lng
                elif place_name:
                    place_details = await self.maps.search_place(place_name)
                    if place_details:
                        place_lat = place_details.lat
                        place_lng = place_details.lng

            if place_lat is None or place_lng is None:
                logger.warning(
                    f"Place {place_name} has no coordinates and could not be geocoded"
                )
                continue

            # Calculate distance using Haversine (fast, no API call)
            distance_meters = int(
                haversine_distance(query_lat, query_lng, place_lat, place_lng)
            )

            # Skip if too far
            if distance_meters > self.max_distance:
                continue

            # Optionally get travel time via Maps API
            duration_seconds = None
            if include_travel_time:
                travel_time = await self.maps.get_travel_time(
                    origin=(query_lat, query_lng),
                    destination=(place_lat, place_lng),
                )
                if travel_time:
                    duration_seconds = travel_time.duration_seconds

            nearby_tasks.append(
                NearbyTask(
                    task_id=task_id,
                    title=title,
                    status=status,
                    priority=priority,
                    due_date=due_date,
                    place_id=place_id,
                    place_name=place_name,
                    place_address=place_address,
                    distance_meters=distance_meters,
                    duration_seconds=duration_seconds,
                )
            )

        # Step 4: Sort by distance and limit results
        nearby_tasks.sort(key=lambda t: t.distance_meters)
        nearby_tasks = nearby_tasks[:max_results]

        return ProximityResult(
            success=True,
            query_location=location,
            query_lat=query_lat,
            query_lng=query_lng,
            tasks=nearby_tasks,
        )

    async def handle_proximity_query(self, text: str) -> ProximityResult | None:
        """Handle a user's proximity query.

        Args:
            text: User input text

        Returns:
            ProximityResult if this is a proximity query, None otherwise
        """
        if not is_proximity_query(text):
            return None

        location = extract_location_from_query(text)
        if not location:
            return ProximityResult(
                success=False,
                query_location="",
                error="Could not extract location from query",
            )

        return await self.find_tasks_near(location)


# Module-level singleton
_service: ProximityTaskService | None = None


def get_proximity_service(
    notion_client: "NotionClient | None" = None,
    maps_client: "MapsClient | None" = None,
) -> ProximityTaskService:
    """Get or create a ProximityTaskService instance."""
    global _service
    if _service is None or notion_client is not None or maps_client is not None:
        _service = ProximityTaskService(notion_client, maps_client)
    return _service


async def find_tasks_near(
    location: str,
    max_results: int = 10,
) -> ProximityResult:
    """Find tasks near a location.

    Args:
        location: Location query string
        max_results: Maximum tasks to return

    Returns:
        ProximityResult with nearby tasks
    """
    return await get_proximity_service().find_tasks_near(location, max_results)


async def handle_proximity_query(text: str) -> ProximityResult | None:
    """Handle a potential proximity query.

    Args:
        text: User input text

    Returns:
        ProximityResult if this is a proximity query, None otherwise
    """
    return await get_proximity_service().handle_proximity_query(text)
