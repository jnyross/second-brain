"""Tests for proximity task suggestions service (T-157).

Tests cover:
- Pattern matching for proximity queries
- Location extraction from queries
- Haversine distance calculations
- Task filtering by place associations
- Distance sorting and formatting
- AT-127 acceptance test
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.services.proximity import (
    MAX_NEARBY_DISTANCE_METERS,
    PROXIMITY_PATTERNS,
    NearbyTask,
    ProximityResult,
    ProximityTaskService,
    extract_location_from_query,
    haversine_distance,
    is_proximity_query,
)


class TestNearbyTask:
    """Tests for NearbyTask dataclass."""

    def test_distance_km(self):
        """Test distance conversion to kilometers."""
        task = NearbyTask(
            task_id="1",
            title="Test",
            status="todo",
            priority="medium",
            due_date=None,
            place_id="p1",
            place_name="Place",
            place_address=None,
            distance_meters=1500,
        )
        assert task.distance_km == 1.5

    def test_distance_display_meters(self):
        """Test distance display for short distances."""
        task = NearbyTask(
            task_id="1",
            title="Test",
            status="todo",
            priority="medium",
            due_date=None,
            place_id="p1",
            place_name="Place",
            place_address=None,
            distance_meters=500,
        )
        assert task.distance_display == "500m"

    def test_distance_display_kilometers(self):
        """Test distance display for longer distances."""
        task = NearbyTask(
            task_id="1",
            title="Test",
            status="todo",
            priority="medium",
            due_date=None,
            place_id="p1",
            place_name="Place",
            place_address=None,
            distance_meters=2500,
        )
        assert task.distance_display == "2.5km"

    def test_duration_display_minutes(self):
        """Test duration display for short durations."""
        task = NearbyTask(
            task_id="1",
            title="Test",
            status="todo",
            priority="medium",
            due_date=None,
            place_id="p1",
            place_name="Place",
            place_address=None,
            distance_meters=1000,
            duration_seconds=600,  # 10 minutes
        )
        assert task.duration_display == "10 min"

    def test_duration_display_hours(self):
        """Test duration display for hour durations."""
        task = NearbyTask(
            task_id="1",
            title="Test",
            status="todo",
            priority="medium",
            due_date=None,
            place_id="p1",
            place_name="Place",
            place_address=None,
            distance_meters=10000,
            duration_seconds=3600,  # 1 hour
        )
        assert task.duration_display == "1 hr"

    def test_duration_display_hours_and_minutes(self):
        """Test duration display for mixed durations."""
        task = NearbyTask(
            task_id="1",
            title="Test",
            status="todo",
            priority="medium",
            due_date=None,
            place_id="p1",
            place_name="Place",
            place_address=None,
            distance_meters=15000,
            duration_seconds=5400,  # 1 hr 30 min
        )
        assert task.duration_display == "1 hr 30 min"

    def test_duration_display_none(self):
        """Test duration display when not set."""
        task = NearbyTask(
            task_id="1",
            title="Test",
            status="todo",
            priority="medium",
            due_date=None,
            place_id="p1",
            place_name="Place",
            place_address=None,
            distance_meters=1000,
            duration_seconds=None,
        )
        assert task.duration_display is None


class TestProximityResult:
    """Tests for ProximityResult dataclass."""

    def test_task_count(self):
        """Test task count property."""
        result = ProximityResult(
            success=True,
            query_location="Union Square",
            tasks=[
                NearbyTask("1", "Task 1", "todo", "medium", None, "p1", "Place 1", None, 500),
                NearbyTask("2", "Task 2", "todo", "medium", None, "p2", "Place 2", None, 1000),
            ],
        )
        assert result.task_count == 2

    def test_has_tasks_true(self):
        """Test has_tasks when tasks exist."""
        result = ProximityResult(
            success=True,
            query_location="Union Square",
            tasks=[NearbyTask("1", "Task", "todo", None, None, "p1", "Place", None, 500)],
        )
        assert result.has_tasks is True

    def test_has_tasks_false(self):
        """Test has_tasks when no tasks."""
        result = ProximityResult(
            success=True,
            query_location="Union Square",
            tasks=[],
        )
        assert result.has_tasks is False

    def test_format_response_error(self):
        """Test format_response for error case."""
        result = ProximityResult(
            success=False,
            query_location="Unknown Place",
            error="Could not find location",
        )
        response = result.format_response()
        assert "Sorry" in response
        assert "Could not find location" in response

    def test_format_response_no_tasks(self):
        """Test format_response when no tasks found."""
        result = ProximityResult(
            success=True,
            query_location="Remote Area",
            tasks=[],
        )
        response = result.format_response()
        assert "No tasks found" in response
        assert "Remote Area" in response

    def test_format_response_with_tasks(self):
        """Test format_response with nearby tasks."""
        result = ProximityResult(
            success=True,
            query_location="Union Square",
            tasks=[
                NearbyTask(
                    "1",
                    "Pick up dry cleaning",
                    "todo",
                    "high",
                    None,
                    "p1",
                    "Dry Cleaners",
                    "123 Main St",
                    500,
                    duration_seconds=180,
                ),
            ],
        )
        response = result.format_response()
        assert "📍 Tasks near Union Square" in response
        assert "Pick up dry cleaning" in response
        assert "500m" in response
        assert "3 min" in response
        assert "🔴" in response  # High priority indicator
        assert "Dry Cleaners" in response


class TestIsProximityQuery:
    """Tests for is_proximity_query function."""

    def test_what_can_i_do_near(self):
        """Test 'what can I do near' pattern."""
        assert is_proximity_query("What can I do near Union Square?") is True

    def test_what_tasks_near(self):
        """Test 'what tasks near' pattern."""
        assert is_proximity_query("What tasks near downtown?") is True

    def test_tasks_near(self):
        """Test 'tasks near' pattern."""
        assert is_proximity_query("Tasks near the office") is True

    def test_things_to_do_near(self):
        """Test 'things to do near' pattern."""
        assert is_proximity_query("Things to do near here") is True

    def test_errands_near(self):
        """Test 'errands near' pattern."""
        assert is_proximity_query("What errands near me?") is True

    def test_whats_nearby(self):
        """Test 'what's nearby' pattern."""
        assert is_proximity_query("What's nearby?") is True

    def test_nearby_tasks(self):
        """Test 'nearby tasks' pattern."""
        assert is_proximity_query("Show me nearby tasks") is True

    def test_case_insensitive(self):
        """Test case insensitivity."""
        assert is_proximity_query("WHAT CAN I DO NEAR THE MALL?") is True

    def test_not_proximity_query(self):
        """Test non-proximity queries return false."""
        assert is_proximity_query("Create a task for tomorrow") is False
        assert is_proximity_query("What is my schedule today?") is False
        assert is_proximity_query("Near miss at work") is False


class TestExtractLocationFromQuery:
    """Tests for extract_location_from_query function."""

    def test_union_square(self):
        """Test extracting Union Square."""
        location = extract_location_from_query("What can I do near Union Square?")
        assert location == "Union Square"

    def test_the_mall(self):
        """Test extracting 'the mall'."""
        location = extract_location_from_query("Tasks near the mall")
        assert location == "the mall"

    def test_address(self):
        """Test extracting an address."""
        location = extract_location_from_query("What tasks near 123 Main Street?")
        assert location == "123 Main Street"

    def test_strips_punctuation(self):
        """Test stripping trailing punctuation."""
        location = extract_location_from_query("Errands near downtown!!!")
        assert location == "downtown"

    def test_no_location(self):
        """Test when no location can be extracted."""
        location = extract_location_from_query("What can I do near")
        assert location is None or location == ""

    def test_preserves_case(self):
        """Test that location case is preserved."""
        location = extract_location_from_query("what can i do near UNION SQUARE")
        assert location == "UNION SQUARE"


class TestHaversineDistance:
    """Tests for haversine_distance function."""

    def test_same_point(self):
        """Test distance between same point is zero."""
        distance = haversine_distance(37.7749, -122.4194, 37.7749, -122.4194)
        assert distance < 1  # Allow for floating point error

    def test_known_distance(self):
        """Test a known distance (SF to LA is ~560km)."""
        # San Francisco (37.7749, -122.4194) to Los Angeles (34.0522, -118.2437)
        distance = haversine_distance(37.7749, -122.4194, 34.0522, -118.2437)
        # Should be approximately 560km
        assert 550000 < distance < 570000

    def test_short_distance(self):
        """Test short distance calculation."""
        # Two points about 1km apart
        # Using points in SF
        lat1, lng1 = 37.7749, -122.4194
        lat2 = lat1 + 0.009  # ~1km north
        lng2 = lng1

        distance = haversine_distance(lat1, lng1, lat2, lng2)
        assert 900 < distance < 1100  # Approximately 1km

    def test_symmetric(self):
        """Test that distance is symmetric."""
        d1 = haversine_distance(37.7749, -122.4194, 34.0522, -118.2437)
        d2 = haversine_distance(34.0522, -118.2437, 37.7749, -122.4194)
        assert abs(d1 - d2) < 1  # Should be identical


class TestProximityTaskService:
    """Tests for ProximityTaskService class."""

    @pytest.mark.asyncio
    async def test_find_tasks_near_no_maps_client(self):
        """Test error when maps client not configured."""
        service = ProximityTaskService(notion_client=None, maps_client=None)
        result = await service.find_tasks_near("Union Square")

        assert result.success is False
        assert "Maps client not configured" in result.error

    @pytest.mark.asyncio
    async def test_find_tasks_near_no_notion_client(self):
        """Test error when notion client not configured."""
        maps_mock = MagicMock()
        service = ProximityTaskService(notion_client=None, maps_client=maps_mock)
        result = await service.find_tasks_near("Union Square")

        assert result.success is False
        assert "Notion client not configured" in result.error

    @pytest.mark.asyncio
    async def test_find_tasks_near_geocode_failure(self):
        """Test handling of geocoding failure."""
        maps_mock = MagicMock()
        maps_mock.geocode = AsyncMock(return_value=None)

        notion_mock = MagicMock()

        service = ProximityTaskService(notion_client=notion_mock, maps_client=maps_mock)
        result = await service.find_tasks_near("Unknown Place XYZ")

        assert result.success is False
        assert "Could not find location" in result.error

    @pytest.mark.asyncio
    async def test_find_tasks_near_no_tasks_with_places(self):
        """Test when no tasks have associated places."""
        # Mock maps client
        maps_mock = MagicMock()
        maps_mock.geocode = AsyncMock(
            return_value=MagicMock(lat=37.7879, lng=-122.4074)  # Union Square coords
        )

        # Mock notion client with tasks that have no places
        notion_mock = MagicMock()
        notion_mock.query_tasks = AsyncMock(
            return_value=[
                {
                    "id": "task-1",
                    "properties": {
                        "title": {"title": [{"text": {"content": "Task without place"}}]},
                        "status": {"select": {"name": "todo"}},
                        "priority": {"select": {"name": "medium"}},
                        "due_date": {"date": None},
                        "place_ids": {"relation": []},  # No places
                    },
                }
            ]
        )

        service = ProximityTaskService(notion_client=notion_mock, maps_client=maps_mock)
        result = await service.find_tasks_near("Union Square")

        assert result.success is True
        assert result.has_tasks is False

    @pytest.mark.asyncio
    async def test_find_tasks_near_filters_by_distance(self):
        """Test that tasks beyond max distance are filtered out."""
        # Mock maps client
        maps_mock = MagicMock()
        maps_mock.geocode = AsyncMock(return_value=MagicMock(lat=37.7879, lng=-122.4074))
        maps_mock.get_travel_time = AsyncMock(return_value=MagicMock(duration_seconds=300))

        # Mock notion client with task that has a distant place
        notion_mock = MagicMock()
        notion_mock.query_tasks = AsyncMock(
            return_value=[
                {
                    "id": "task-1",
                    "properties": {
                        "title": {"title": [{"text": {"content": "Far task"}}]},
                        "status": {"select": {"name": "todo"}},
                        "priority": {"select": None},
                        "due_date": {"date": None},
                        "place_ids": {"relation": [{"id": "place-1"}]},
                    },
                }
            ]
        )
        # Far away place (Los Angeles)
        notion_mock.get_place = AsyncMock(
            return_value={
                "properties": {
                    "name": {"title": [{"text": {"content": "LA Office"}}]},
                    "address": {"rich_text": []},
                    "lat": {"number": 34.0522},  # Los Angeles
                    "lng": {"number": -118.2437},
                }
            }
        )

        service = ProximityTaskService(notion_client=notion_mock, maps_client=maps_mock)
        result = await service.find_tasks_near("Union Square")

        assert result.success is True
        assert result.has_tasks is False  # LA is beyond 5km from SF

    @pytest.mark.asyncio
    async def test_find_tasks_near_sorts_by_distance(self):
        """Test that results are sorted by distance."""
        maps_mock = MagicMock()
        maps_mock.geocode = AsyncMock(return_value=MagicMock(lat=37.7879, lng=-122.4074))
        maps_mock.get_travel_time = AsyncMock(return_value=MagicMock(duration_seconds=300))

        notion_mock = MagicMock()
        notion_mock.query_tasks = AsyncMock(
            return_value=[
                {
                    "id": "task-far",
                    "properties": {
                        "title": {"title": [{"text": {"content": "Far task"}}]},
                        "status": {"select": {"name": "todo"}},
                        "priority": {"select": None},
                        "due_date": {"date": None},
                        "place_ids": {"relation": [{"id": "place-far"}]},
                    },
                },
                {
                    "id": "task-near",
                    "properties": {
                        "title": {"title": [{"text": {"content": "Near task"}}]},
                        "status": {"select": {"name": "todo"}},
                        "priority": {"select": None},
                        "due_date": {"date": None},
                        "place_ids": {"relation": [{"id": "place-near"}]},
                    },
                },
            ]
        )

        # Return different places for different IDs
        async def get_place_mock(place_id):
            if place_id == "place-near":
                return {
                    "properties": {
                        "name": {"title": [{"text": {"content": "Near Place"}}]},
                        "address": {"rich_text": []},
                        "lat": {"number": 37.7880},  # Very close
                        "lng": {"number": -122.4075},
                    }
                }
            else:
                return {
                    "properties": {
                        "name": {"title": [{"text": {"content": "Far Place"}}]},
                        "address": {"rich_text": []},
                        "lat": {"number": 37.7600},  # 3km away
                        "lng": {"number": -122.4500},
                    }
                }

        notion_mock.get_place = AsyncMock(side_effect=get_place_mock)

        service = ProximityTaskService(notion_client=notion_mock, maps_client=maps_mock)
        result = await service.find_tasks_near("Union Square")

        assert result.success is True
        assert len(result.tasks) == 2
        assert result.tasks[0].title == "Near task"  # Nearest first
        assert result.tasks[1].title == "Far task"

    @pytest.mark.asyncio
    async def test_handle_proximity_query_not_proximity(self):
        """Test handle_proximity_query returns None for non-proximity queries."""
        service = ProximityTaskService()
        result = await service.handle_proximity_query("Create a task for tomorrow")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_proximity_query_no_location(self):
        """Test handle_proximity_query with no extractable location."""
        service = ProximityTaskService()
        result = await service.handle_proximity_query("What can I do near")

        # Should return error result since location is empty
        assert result is not None
        assert result.success is False


class TestAT127ProximityTaskSuggestions:
    """Acceptance tests for AT-127: Proximity Task Suggestions.

    Given: User has 3 tasks with places in downtown SF
    When: User asks "What can I do near Union Square?"
    Then: Response lists nearby tasks with distances
    Pass condition: Response includes all 3 tasks with distance estimates
    """

    @pytest.mark.asyncio
    async def test_at127_three_tasks_near_union_square(self):
        """AT-127: Response includes all 3 tasks with distance estimates."""
        # Union Square coordinates
        union_square_lat = 37.7879
        union_square_lng = -122.4074

        # Mock maps client
        maps_mock = MagicMock()
        maps_mock.geocode = AsyncMock(
            return_value=MagicMock(lat=union_square_lat, lng=union_square_lng)
        )
        maps_mock.get_travel_time = AsyncMock(
            return_value=MagicMock(duration_seconds=300)  # 5 min
        )

        # Mock notion client with 3 tasks in downtown SF
        sf_tasks = [
            {
                "id": "task-1",
                "properties": {
                    "title": {"title": [{"text": {"content": "Pick up prescription"}}]},
                    "status": {"select": {"name": "todo"}},
                    "priority": {"select": {"name": "high"}},
                    "due_date": {"date": None},
                    "place_ids": {"relation": [{"id": "place-1"}]},
                },
            },
            {
                "id": "task-2",
                "properties": {
                    "title": {"title": [{"text": {"content": "Return library book"}}]},
                    "status": {"select": {"name": "todo"}},
                    "priority": {"select": {"name": "medium"}},
                    "due_date": {"date": None},
                    "place_ids": {"relation": [{"id": "place-2"}]},
                },
            },
            {
                "id": "task-3",
                "properties": {
                    "title": {"title": [{"text": {"content": "Get dry cleaning"}}]},
                    "status": {"select": {"name": "todo"}},
                    "priority": {"select": {"name": "low"}},
                    "due_date": {"date": None},
                    "place_ids": {"relation": [{"id": "place-3"}]},
                },
            },
        ]

        # Places data - all within 5km of Union Square
        places_data = {
            "place-1": {
                "properties": {
                    "name": {"title": [{"text": {"content": "Walgreens"}}]},
                    "address": {"rich_text": [{"text": {"content": "135 Powell St"}}]},
                    "lat": {"number": 37.7865},  # ~150m from Union Square
                    "lng": {"number": -122.4078},
                }
            },
            "place-2": {
                "properties": {
                    "name": {"title": [{"text": {"content": "SF Public Library"}}]},
                    "address": {"rich_text": [{"text": {"content": "100 Larkin St"}}]},
                    "lat": {"number": 37.7797},  # ~1km from Union Square
                    "lng": {"number": -122.4158},
                }
            },
            "place-3": {
                "properties": {
                    "name": {"title": [{"text": {"content": "Dry Cleaners"}}]},
                    "address": {"rich_text": [{"text": {"content": "500 Sutter St"}}]},
                    "lat": {"number": 37.7890},  # ~200m from Union Square
                    "lng": {"number": -122.4100},
                }
            },
        }

        notion_mock = MagicMock()
        notion_mock.query_tasks = AsyncMock(return_value=sf_tasks)
        notion_mock.get_place = AsyncMock(side_effect=lambda pid: places_data.get(pid))

        # Execute
        service = ProximityTaskService(notion_client=notion_mock, maps_client=maps_mock)
        result = await service.find_tasks_near("Union Square")

        # Verify AT-127 pass conditions
        assert result.success is True, "Query should succeed"
        assert result.task_count == 3, "Should find all 3 tasks"

        # All tasks should have distance estimates
        for task in result.tasks:
            assert task.distance_meters > 0, f"Task '{task.title}' should have distance"
            assert task.distance_display, f"Task '{task.title}' should have distance display"

        # Verify tasks are sorted by distance
        distances = [t.distance_meters for t in result.tasks]
        assert distances == sorted(distances), "Tasks should be sorted by distance"

        # Format response and verify content
        response = result.format_response()
        assert "Union Square" in response
        assert "Pick up prescription" in response
        assert "Return library book" in response
        assert "Get dry cleaning" in response

    @pytest.mark.asyncio
    async def test_at127_response_format(self):
        """AT-127: Response lists nearby tasks with distances in proper format."""
        maps_mock = MagicMock()
        maps_mock.geocode = AsyncMock(return_value=MagicMock(lat=37.7879, lng=-122.4074))
        maps_mock.get_travel_time = AsyncMock(return_value=MagicMock(duration_seconds=300))

        notion_mock = MagicMock()
        notion_mock.query_tasks = AsyncMock(
            return_value=[
                {
                    "id": "task-1",
                    "properties": {
                        "title": {"title": [{"text": {"content": "Task 1"}}]},
                        "status": {"select": {"name": "todo"}},
                        "priority": {"select": {"name": "high"}},
                        "due_date": {"date": None},
                        "place_ids": {"relation": [{"id": "place-1"}]},
                    },
                }
            ]
        )
        notion_mock.get_place = AsyncMock(
            return_value={
                "properties": {
                    "name": {"title": [{"text": {"content": "Nearby Place"}}]},
                    "address": {"rich_text": []},
                    "lat": {"number": 37.7880},
                    "lng": {"number": -122.4075},
                }
            }
        )

        service = ProximityTaskService(notion_client=notion_mock, maps_client=maps_mock)
        result = await service.find_tasks_near("Union Square")

        response = result.format_response()

        # Check format elements
        assert "📍 Tasks near Union Square" in response
        assert "Task 1" in response
        assert "🔴" in response  # High priority indicator
        assert "Nearby Place" in response

    @pytest.mark.asyncio
    async def test_at127_query_pattern_matching(self):
        """AT-127: 'What can I do near Union Square?' triggers proximity search."""
        query = "What can I do near Union Square?"

        # Should be recognized as proximity query
        assert is_proximity_query(query) is True

        # Should extract location
        location = extract_location_from_query(query)
        assert location == "Union Square"


class TestConstants:
    """Tests for module constants."""

    def test_proximity_patterns_exist(self):
        """Test that proximity patterns are defined."""
        assert len(PROXIMITY_PATTERNS) > 0
        assert "what can i do near" in PROXIMITY_PATTERNS

    def test_max_distance_reasonable(self):
        """Test that max distance is reasonable."""
        assert MAX_NEARBY_DISTANCE_METERS == 5000  # 5km default
