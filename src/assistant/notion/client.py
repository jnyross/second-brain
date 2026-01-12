import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from assistant.config import settings
from assistant.notion.schemas import (
    ActionType,
    InboxItem,
    LogEntry,
    Pattern,
    Person,
    Place,
    Project,
    Task,
)

T = TypeVar("T", bound=BaseModel)

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

OFFLINE_QUEUE_PATH = Path.home() / ".second-brain" / "queue" / "pending.jsonl"


class NotionClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.notion_api_key
        self._client: httpx.AsyncClient | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=NOTION_API_URL,
                headers=self.headers,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        retries: int = 3,
    ) -> dict[str, Any]:
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(retries):
            try:
                response = await client.request(method, path, json=json_data)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "1"))
                    import asyncio

                    await asyncio.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code >= 500:
                    import asyncio

                    await asyncio.sleep(2**attempt)
                    continue
                raise

            except httpx.RequestError as e:
                last_error = e
                import asyncio

                await asyncio.sleep(2**attempt)
                continue

        if last_error:
            self._queue_offline(method, path, json_data)
            raise last_error

        raise RuntimeError("Request failed without error")

    def _queue_offline(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None,
    ) -> None:
        OFFLINE_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "method": method,
            "path": path,
            "data": json_data,
        }
        with open(OFFLINE_QUEUE_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _generate_dedupe_key(self, *args: Any) -> str:
        content = "|".join(str(a) for a in args)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # Properties that exist in each Notion database
    NOTION_DB_PROPERTIES: dict[str, set[str]] = {
        "inbox": {
            "raw_input",
            "source",
            "confidence",
            "processed",
            "timestamp",
            "needs_clarification",
            "dedupe_key",
        },
        "tasks": {"title", "status", "priority", "due_date", "confidence", "deleted_at"},
        "people": {"name", "email", "relationship", "deleted_at", "archived"},
        "places": {"name", "place_type", "address"},
        "projects": {"name", "status", "deadline"},
        "log": {"action_type", "action_taken", "timestamp", "idempotency_key", "confidence"},
        "patterns": {"trigger", "meaning", "confidence"},
        "preferences": {"preference", "category", "value", "last_updated"},
        "emails": {
            "subject",
            "from_address",
            "to_address",
            "thread_id",
            "message_id",
            "received_at",
            "snippet",
            "has_attachments",
            "labels",
            "processed",
        },
    }

    def _model_to_notion_properties(
        self,
        model: BaseModel,
        db_type: str,
    ) -> dict[str, Any]:
        from enum import Enum

        data = model.model_dump(exclude_none=True)
        properties: dict[str, Any] = {}

        # Get valid properties for this database type
        valid_properties = self.NOTION_DB_PROPERTIES.get(db_type, set())

        for key, value in data.items():
            if key == "id":
                continue

            # Skip properties not in the Notion database
            if valid_properties and key not in valid_properties:
                continue

            # Handle enum values - extract the string value
            if isinstance(value, Enum):
                value = value.value

            if isinstance(value, datetime):
                properties[key] = {"date": {"start": value.isoformat()}}
            elif isinstance(value, bool):
                properties[key] = {"checkbox": value}
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                properties[key] = {"number": value}
            elif isinstance(value, list):
                if all(isinstance(v, str) for v in value):
                    properties[key] = {"multi_select": [{"name": v} for v in value]}
            elif isinstance(value, str):
                if key in ("title", "name", "preference", "trigger", "subject", "raw_input"):
                    properties[key] = {"title": [{"text": {"content": value}}]}
                elif key in (
                    "status",
                    "priority",
                    "source",
                    "relationship",
                    "action_type",
                    "category",
                    "place_type",
                    "project_type",
                ):
                    properties[key] = {"select": {"name": value}}
                else:
                    properties[key] = {"rich_text": [{"text": {"content": value}}]}

        return properties

    async def create_inbox_item(self, item: InboxItem) -> str:
        item.dedupe_key = self._generate_dedupe_key(
            item.raw_input,
            item.telegram_chat_id,
            item.timestamp.isoformat(),
        )

        existing = await self._check_dedupe("inbox", item.dedupe_key)
        if existing:
            return existing

        properties = self._model_to_notion_properties(item, "inbox")
        result = await self._request(
            "POST",
            "/pages",
            {
                "parent": {"database_id": settings.notion_inbox_db_id},
                "properties": properties,
            },
        )
        return result["id"]

    async def create_task(self, task: Task) -> str:
        properties = self._model_to_notion_properties(task, "tasks")
        result = await self._request(
            "POST",
            "/pages",
            {
                "parent": {"database_id": settings.notion_tasks_db_id},
                "properties": properties,
            },
        )
        return result["id"]

    async def create_person(self, person: Person) -> str:
        if person.email:
            person.unique_key = person.email.lower()

        properties = self._model_to_notion_properties(person, "people")
        result = await self._request(
            "POST",
            "/pages",
            {
                "parent": {"database_id": settings.notion_people_db_id},
                "properties": properties,
            },
        )
        return result["id"]

    async def create_log_entry(self, entry: LogEntry) -> str:
        if entry.idempotency_key:
            existing = await self._check_dedupe("log", entry.idempotency_key)
            if existing:
                return existing

        properties = self._model_to_notion_properties(entry, "log")
        result = await self._request(
            "POST",
            "/pages",
            {
                "parent": {"database_id": settings.notion_log_db_id},
                "properties": properties,
            },
        )
        return result["id"]

    async def _check_dedupe(self, db_type: str, key: str) -> str | None:
        db_id_map = {
            "inbox": settings.notion_inbox_db_id,
            "log": settings.notion_log_db_id,
        }
        db_id = db_id_map.get(db_type)
        if not db_id:
            return None

        key_field = "dedupe_key" if db_type == "inbox" else "idempotency_key"

        result = await self._request(
            "POST",
            f"/databases/{db_id}/query",
            {
                "filter": {
                    "property": key_field,
                    "rich_text": {"equals": key},
                },
                "page_size": 1,
            },
        )

        if result.get("results"):
            return result["results"][0]["id"]
        return None

    async def query_tasks(
        self,
        status: str | None = None,
        exclude_statuses: list[str] | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
        include_deleted: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query tasks with optional filters.

        Args:
            status: Filter by specific status
            exclude_statuses: Exclude tasks with these statuses (e.g., ['done', 'cancelled'])
            due_before: Tasks due on or before this datetime
            due_after: Tasks due on or after this datetime
            include_deleted: Include soft-deleted tasks
            limit: Maximum number of results

        Returns:
            List of task results from Notion
        """
        filters: list[dict[str, Any]] = []

        if status:
            filters.append(
                {
                    "property": "status",
                    "select": {"equals": status},
                }
            )

        if exclude_statuses:
            for excluded_status in exclude_statuses:
                filters.append(
                    {
                        "property": "status",
                        "select": {"does_not_equal": excluded_status},
                    }
                )

        if due_before:
            filters.append(
                {
                    "property": "due_date",
                    "date": {"on_or_before": due_before.isoformat()},
                }
            )

        if due_after:
            filters.append(
                {
                    "property": "due_date",
                    "date": {"on_or_after": due_after.isoformat()},
                }
            )

        if not include_deleted:
            filters.append(
                {
                    "property": "deleted_at",
                    "date": {"is_empty": True},
                }
            )

        query_filter = {"and": filters} if len(filters) > 1 else (filters[0] if filters else None)

        result = await self._request(
            "POST",
            f"/databases/{settings.notion_tasks_db_id}/query",
            {
                "filter": query_filter,
                "page_size": limit,
                "sorts": [{"property": "due_date", "direction": "ascending"}],
            }
            if query_filter
            else {
                "page_size": limit,
                "sorts": [{"property": "due_date", "direction": "ascending"}],
            },
        )

        return result.get("results", [])

    async def query_inbox(
        self,
        needs_clarification: bool | None = None,
        processed: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query inbox items with optional filters.

        Args:
            needs_clarification: Filter by needs_clarification flag
            processed: Filter by processed flag
            limit: Maximum number of results

        Returns:
            List of inbox item results from Notion
        """
        filters: list[dict[str, Any]] = []

        if needs_clarification is not None:
            filters.append(
                {
                    "property": "needs_clarification",
                    "checkbox": {"equals": needs_clarification},
                }
            )

        if processed is not None:
            filters.append(
                {
                    "property": "processed",
                    "checkbox": {"equals": processed},
                }
            )

        query_filter = {"and": filters} if len(filters) > 1 else (filters[0] if filters else None)

        result = await self._request(
            "POST",
            f"/databases/{settings.notion_inbox_db_id}/query",
            {
                "filter": query_filter,
                "page_size": limit,
                "sorts": [{"property": "timestamp", "direction": "descending"}],
            }
            if query_filter
            else {
                "page_size": limit,
                "sorts": [{"property": "timestamp", "direction": "descending"}],
            },
        )

        return result.get("results", [])

    async def mark_inbox_processed(
        self,
        page_id: str,
        task_id: str | None = None,
    ) -> None:
        """Mark an inbox item as processed.

        Args:
            page_id: Notion page ID of the inbox item
            task_id: Optional ID of created task for linking
        """
        update: dict[str, Any] = {
            "properties": {
                "processed": {"checkbox": True},
            }
        }

        await self._request("PATCH", f"/pages/{page_id}", update)

    async def query_people(
        self,
        name: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []

        if name:
            filters.append(
                {
                    "or": [
                        {"property": "name", "title": {"contains": name}},
                        {"property": "aliases", "rich_text": {"contains": name}},
                    ]
                }
            )

        if not include_archived:
            filters.append(
                {
                    "property": "archived",
                    "checkbox": {"equals": False},
                }
            )

        query_filter = {"and": filters} if len(filters) > 1 else (filters[0] if filters else None)

        result = await self._request(
            "POST",
            f"/databases/{settings.notion_people_db_id}/query",
            {"filter": query_filter} if query_filter else {},
        )

        return result.get("results", [])

    async def query_places(
        self,
        name: str | None = None,
        place_type: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """Query places with optional filters.

        Args:
            name: Filter by place name (partial match)
            place_type: Filter by place type (restaurant, cinema, etc.)
            include_archived: Include archived places

        Returns:
            List of place results from Notion
        """
        filters: list[dict[str, Any]] = []

        if name:
            filters.append(
                {
                    "property": "name",
                    "title": {"contains": name},
                }
            )

        if place_type:
            filters.append(
                {
                    "property": "place_type",
                    "select": {"equals": place_type},
                }
            )

        if not include_archived:
            filters.append(
                {
                    "property": "archived",
                    "checkbox": {"equals": False},
                }
            )

        query_filter = {"and": filters} if len(filters) > 1 else (filters[0] if filters else None)

        result = await self._request(
            "POST",
            f"/databases/{settings.notion_places_db_id}/query",
            {"filter": query_filter} if query_filter else {},
        )

        return result.get("results", [])

    async def create_place(self, place: Place) -> str:
        """Create a new place in Notion.

        Args:
            place: Place object to create

        Returns:
            Notion page ID of the created place
        """
        properties = self._model_to_notion_properties(place, "places")
        result = await self._request(
            "POST",
            "/pages",
            {
                "parent": {"database_id": settings.notion_places_db_id},
                "properties": properties,
            },
        )
        return result["id"]

    async def query_projects(
        self,
        name: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """Query projects with optional filters.

        Args:
            name: Filter by project name (partial match)
            status: Filter by status (active, paused, completed, cancelled)
            include_archived: Include archived projects

        Returns:
            List of project results from Notion
        """
        filters: list[dict[str, Any]] = []

        if name:
            filters.append(
                {
                    "property": "name",
                    "title": {"contains": name},
                }
            )

        if status:
            filters.append(
                {
                    "property": "status",
                    "select": {"equals": status},
                }
            )

        if not include_archived:
            filters.append(
                {
                    "property": "archived",
                    "checkbox": {"equals": False},
                }
            )

        query_filter = {"and": filters} if len(filters) > 1 else (filters[0] if filters else None)

        result = await self._request(
            "POST",
            f"/databases/{settings.notion_projects_db_id}/query",
            {"filter": query_filter} if query_filter else {},
        )

        return result.get("results", [])

    async def create_project(self, project: Project) -> str:
        """Create a new project in Notion.

        Args:
            project: Project object to create

        Returns:
            Notion page ID of the created project
        """
        properties = self._model_to_notion_properties(project, "projects")
        result = await self._request(
            "POST",
            "/pages",
            {
                "parent": {"database_id": settings.notion_projects_db_id},
                "properties": properties,
            },
        )
        return result["id"]

    async def soft_delete(self, page_id: str) -> None:
        await self._request(
            "PATCH",
            f"/pages/{page_id}",
            {
                "properties": {
                    "deleted_at": {"date": {"start": datetime.utcnow().isoformat()}},
                }
            },
        )

    async def undo_delete(self, page_id: str) -> None:
        await self._request(
            "PATCH",
            f"/pages/{page_id}",
            {
                "properties": {
                    "deleted_at": {"date": None},
                }
            },
        )

    async def update_task_status(self, page_id: str, status: str) -> None:
        update: dict[str, Any] = {
            "properties": {
                "status": {"select": {"name": status}},
                "last_modified_at": {"date": {"start": datetime.utcnow().isoformat()}},
            }
        }

        if status == "done":
            update["properties"]["completed_at"] = {
                "date": {"start": datetime.utcnow().isoformat()}
            }

        await self._request("PATCH", f"/pages/{page_id}", update)

    async def log_action(
        self,
        action_type: ActionType,
        idempotency_key: str | None = None,
        input_text: str | None = None,
        action_taken: str | None = None,
        confidence: int | None = None,
        entities_affected: list[str] | None = None,
        external_api: str | None = None,
        external_resource_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> str:
        entry = LogEntry(
            action_type=action_type,
            idempotency_key=idempotency_key,
            input_text=input_text,
            action_taken=action_taken,
            confidence=confidence,
            entities_affected=entities_affected or [],
            external_api=external_api,
            external_resource_id=external_resource_id,
            error_code=error_code,
            error_message=error_message,
        )
        return await self.create_log_entry(entry)

    async def query_log_corrections(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[LogEntry]:
        """Query log entries that contain corrections.

        Args:
            since: Only return corrections after this timestamp
            limit: Maximum number of results

        Returns:
            List of LogEntry objects with correction data
        """
        filters: list[dict[str, Any]] = [
            {
                "property": "correction",
                "rich_text": {"is_not_empty": True},
            }
        ]

        if since:
            filters.append(
                {
                    "property": "timestamp",
                    "date": {"on_or_after": since.isoformat()},
                }
            )

        query_filter = {"and": filters} if len(filters) > 1 else filters[0]

        result = await self._request(
            "POST",
            f"/databases/{settings.notion_log_db_id}/query",
            {
                "filter": query_filter,
                "page_size": limit,
                "sorts": [{"property": "timestamp", "direction": "descending"}],
            },
        )

        entries = []
        for page in result.get("results", []):
            props = page.get("properties", {})

            # Extract timestamp
            timestamp_prop = props.get("timestamp", {}).get("date", {})
            timestamp_str = timestamp_prop.get("start") if timestamp_prop else None
            timestamp = (
                datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.utcnow()
            )

            # Extract correction
            correction_prop = props.get("correction", {}).get("rich_text", [])
            correction = correction_prop[0]["text"]["content"] if correction_prop else None

            # Extract corrected_at
            corrected_at_prop = props.get("corrected_at", {}).get("date", {})
            corrected_at_str = corrected_at_prop.get("start") if corrected_at_prop else None
            corrected_at = datetime.fromisoformat(corrected_at_str) if corrected_at_str else None

            # Extract action_type
            action_type_prop = props.get("action_type", {}).get("select", {})
            action_type_name = action_type_prop.get("name") if action_type_prop else "update"

            entry = LogEntry(
                id=page["id"],
                timestamp=timestamp,
                action_type=ActionType(action_type_name),
                correction=correction,
                corrected_at=corrected_at,
            )
            entries.append(entry)

        return entries

    async def create_pattern(self, pattern: Pattern) -> str:
        """Create a new pattern in Notion's Patterns database.

        Args:
            pattern: Pattern object to create

        Returns:
            Notion page ID of the created pattern
        """
        properties = self._model_to_notion_properties(pattern, "patterns")
        result = await self._request(
            "POST",
            "/pages",
            {
                "parent": {"database_id": settings.notion_patterns_db_id},
                "properties": properties,
            },
        )
        return result["id"]

    async def query_patterns(
        self,
        trigger: str | None = None,
        min_confidence: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query patterns with optional filters.

        Args:
            trigger: Filter by trigger text (partial match)
            min_confidence: Minimum confidence score
            limit: Maximum number of results

        Returns:
            List of pattern results from Notion
        """
        filters: list[dict[str, Any]] = []

        if trigger:
            filters.append(
                {
                    "property": "trigger",
                    "title": {"contains": trigger},
                }
            )

        if min_confidence is not None:
            filters.append(
                {
                    "property": "confidence",
                    "number": {"greater_than_or_equal_to": min_confidence},
                }
            )

        query_filter = {"and": filters} if len(filters) > 1 else (filters[0] if filters else None)

        result = await self._request(
            "POST",
            f"/databases/{settings.notion_patterns_db_id}/query",
            {
                "filter": query_filter,
                "page_size": limit,
                "sorts": [{"property": "confidence", "direction": "descending"}],
            }
            if query_filter
            else {
                "page_size": limit,
                "sorts": [{"property": "confidence", "direction": "descending"}],
            },
        )

        return result.get("results", [])

    async def update_pattern_confidence(
        self,
        page_id: str,
        times_confirmed: int | None = None,
        times_wrong: int | None = None,
        confidence: int | None = None,
    ) -> None:
        """Update a pattern's confirmation counts and confidence.

        Args:
            page_id: Notion page ID of the pattern
            times_confirmed: New confirmation count (or None to leave unchanged)
            times_wrong: New wrong count (or None to leave unchanged)
            confidence: New confidence score (or None to leave unchanged)
        """
        update: dict[str, Any] = {"properties": {}}

        if times_confirmed is not None:
            update["properties"]["times_confirmed"] = {"number": times_confirmed}

        if times_wrong is not None:
            update["properties"]["times_wrong"] = {"number": times_wrong}

        if confidence is not None:
            update["properties"]["confidence"] = {"number": confidence}

        update["properties"]["last_used"] = {"date": {"start": datetime.utcnow().isoformat()}}

        await self._request("PATCH", f"/pages/{page_id}", update)

    async def update_task_calendar_event(
        self,
        page_id: str,
        calendar_event_id: str | None,
    ) -> None:
        """Update a task's linked calendar event ID.

        Args:
            page_id: Notion page ID of the task
            calendar_event_id: Google Calendar event ID (or None to clear)
        """
        update: dict[str, Any] = {
            "properties": {
                "last_modified_at": {"date": {"start": datetime.utcnow().isoformat()}},
            }
        }

        if calendar_event_id:
            update["properties"]["calendar_event_id"] = {
                "rich_text": [{"text": {"content": calendar_event_id}}]
            }
        else:
            # Clear the calendar_event_id
            update["properties"]["calendar_event_id"] = {"rich_text": []}

        await self._request("PATCH", f"/pages/{page_id}", update)

    async def process_offline_queue(self) -> int:
        if not OFFLINE_QUEUE_PATH.exists():
            return 0

        processed = 0
        failed_entries: list[str] = []

        with open(OFFLINE_QUEUE_PATH) as f:
            entries = f.readlines()

        for line in entries:
            try:
                entry = json.loads(line)
                await self._request(
                    entry["method"],
                    entry["path"],
                    entry.get("data"),
                )
                processed += 1
            except Exception:
                failed_entries.append(line)

        if failed_entries:
            with open(OFFLINE_QUEUE_PATH, "w") as f:
                f.writelines(failed_entries)
        else:
            OFFLINE_QUEUE_PATH.unlink(missing_ok=True)

        return processed
