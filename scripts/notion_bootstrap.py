#!/usr/bin/env python3
"""
Bootstrap Notion workspace for Second Brain.
Creates all required databases if they don't exist.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

DATABASE_SCHEMAS = {
    "Inbox": {
        "raw_input": {"rich_text": {}},
        "source": {"select": {"options": [
            {"name": "telegram_text"},
            {"name": "telegram_voice"},
            {"name": "manual"},
        ]}},
        "timestamp": {"date": {}},
        "processed": {"checkbox": {}},
        "confidence": {"number": {}},
        "needs_clarification": {"checkbox": {}},
        "interpretation": {"rich_text": {}},
        "telegram_chat_id": {"rich_text": {}},
        "telegram_message_id": {"rich_text": {}},
        "voice_file_id": {"rich_text": {}},
        "transcript_confidence": {"number": {}},
        "language": {"rich_text": {}},
        "processing_error": {"rich_text": {}},
        "retry_count": {"number": {}},
        "dedupe_key": {"rich_text": {}},
    },
    "Tasks": {
        "title": {"title": {}},
        "status": {"select": {"options": [
            {"name": "inbox"},
            {"name": "todo"},
            {"name": "doing"},
            {"name": "done"},
            {"name": "cancelled"},
            {"name": "deleted"},
        ]}},
        "priority": {"select": {"options": [
            {"name": "urgent"},
            {"name": "high"},
            {"name": "medium"},
            {"name": "low"},
            {"name": "someday"},
        ]}},
        "due_date": {"date": {}},
        "due_timezone": {"rich_text": {}},
        "source": {"select": {"options": [
            {"name": "telegram"},
            {"name": "voice"},
            {"name": "manual"},
            {"name": "ai_created"},
            {"name": "email"},
        ]}},
        "confidence": {"number": {}},
        "created_by": {"select": {"options": [
            {"name": "user"},
            {"name": "ai"},
        ]}},
        "created_at": {"date": {}},
        "last_modified_at": {"date": {}},
        "completed_at": {"date": {}},
        "deleted_at": {"date": {}},
        "calendar_event_id": {"rich_text": {}},
        "estimated_duration": {"number": {}},
        "tags": {"multi_select": {}},
        "notes": {"rich_text": {}},
    },
    "People": {
        "name": {"title": {}},
        "aliases": {"rich_text": {}},
        "unique_key": {"rich_text": {}},
        "relationship": {"select": {"options": [
            {"name": "partner"},
            {"name": "family"},
            {"name": "friend"},
            {"name": "colleague"},
            {"name": "acquaintance"},
        ]}},
        "company": {"rich_text": {}},
        "email": {"email": {}},
        "phone": {"phone_number": {}},
        "telegram_handle": {"rich_text": {}},
        "preferences": {"rich_text": {}},
        "quirks": {"rich_text": {}},
        "communication_style": {"rich_text": {}},
        "last_contact": {"date": {}},
        "archived": {"checkbox": {}},
        "deleted_at": {"date": {}},
        "notes": {"rich_text": {}},
    },
    "Projects": {
        "name": {"title": {}},
        "status": {"select": {"options": [
            {"name": "active"},
            {"name": "paused"},
            {"name": "completed"},
            {"name": "cancelled"},
        ]}},
        "project_type": {"select": {"options": [
            {"name": "work"},
            {"name": "personal"},
        ]}},
        "deadline": {"date": {}},
        "next_action": {"rich_text": {}},
        "context": {"rich_text": {}},
        "archived": {"checkbox": {}},
        "deleted_at": {"date": {}},
    },
    "Places": {
        "name": {"title": {}},
        "place_type": {"select": {"options": [
            {"name": "restaurant"},
            {"name": "cinema"},
            {"name": "office"},
            {"name": "home"},
            {"name": "venue"},
            {"name": "other"},
        ]}},
        "address": {"rich_text": {}},
        "your_preference": {"rich_text": {}},
        "last_visit": {"date": {}},
        "rating": {"number": {}},
        "archived": {"checkbox": {}},
        "deleted_at": {"date": {}},
        "notes": {"rich_text": {}},
    },
    "Preferences": {
        "preference": {"title": {}},
        "category": {"select": {"options": [
            {"name": "meetings"},
            {"name": "food"},
            {"name": "travel"},
            {"name": "communication"},
            {"name": "schedule"},
            {"name": "other"},
        ]}},
        "details": {"rich_text": {}},
        "learned_from": {"rich_text": {}},
        "learned_at": {"date": {}},
        "confidence": {"number": {}},
        "times_applied": {"number": {}},
    },
    "Patterns": {
        "trigger": {"title": {}},
        "meaning": {"rich_text": {}},
        "confidence": {"number": {}},
        "times_confirmed": {"number": {}},
        "times_wrong": {"number": {}},
        "last_used": {"date": {}},
        "created_at": {"date": {}},
    },
    "Emails": {
        "subject": {"title": {}},
        "gmail_id": {"rich_text": {}},
        "thread_id": {"rich_text": {}},
        "snippet": {"rich_text": {}},
        "received_at": {"date": {}},
        "is_read": {"checkbox": {}},
        "needs_response": {"checkbox": {}},
        "priority": {"select": {"options": [
            {"name": "high"},
            {"name": "normal"},
            {"name": "low"},
        ]}},
        "response_draft": {"rich_text": {}},
        "response_sent": {"checkbox": {}},
        "response_sent_at": {"date": {}},
    },
    "Log": {
        "action_taken": {"title": {}},
        "request_id": {"rich_text": {}},
        "idempotency_key": {"rich_text": {}},
        "timestamp": {"date": {}},
        "action_type": {"select": {"options": [
            {"name": "capture"},
            {"name": "classify"},
            {"name": "create"},
            {"name": "update"},
            {"name": "delete"},
            {"name": "send"},
            {"name": "research"},
            {"name": "email_read"},
            {"name": "email_send"},
            {"name": "calendar_create"},
            {"name": "calendar_update"},
            {"name": "error"},
            {"name": "retry"},
        ]}},
        "input_text": {"rich_text": {}},
        "interpretation": {"rich_text": {}},
        "confidence": {"number": {}},
        "entities_affected": {"rich_text": {}},
        "external_api": {"rich_text": {}},
        "external_resource_id": {"rich_text": {}},
        "error_code": {"rich_text": {}},
        "error_message": {"rich_text": {}},
        "retry_count": {"number": {}},
        "correction": {"rich_text": {}},
        "corrected_at": {"date": {}},
        "undo_available_until": {"date": {}},
        "undone": {"checkbox": {}},
    },
}


async def get_parent_page_id(client: httpx.AsyncClient, headers: dict) -> str:
    response = await client.post(
        f"{NOTION_API_URL}/search",
        headers=headers,
        json={"filter": {"property": "object", "value": "page"}, "page_size": 1},
    )
    response.raise_for_status()
    results = response.json().get("results", [])

    if not results:
        print("No pages found. Please create a page in Notion first.")
        print("The databases will be created as children of that page.")
        sys.exit(1)

    return results[0]["id"]


async def create_database(
    client: httpx.AsyncClient,
    headers: dict,
    parent_id: str,
    name: str,
    properties: dict,
) -> str:
    response = await client.post(
        f"{NOTION_API_URL}/databases",
        headers=headers,
        json={
            "parent": {"type": "page_id", "page_id": parent_id},
            "title": [{"type": "text", "text": {"content": name}}],
            "properties": properties,
        },
    )
    response.raise_for_status()
    return response.json()["id"]


async def main() -> None:
    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        print("Error: NOTION_API_KEY environment variable not set")
        print("Get your API key from notion.so/my-integrations")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        print("Finding parent page...")
        parent_id = await get_parent_page_id(client, headers)
        print(f"Using parent page: {parent_id}\n")

        db_ids = {}

        for db_name, properties in DATABASE_SCHEMAS.items():
            print(f"Creating {db_name} database...")
            try:
                db_id = await create_database(client, headers, parent_id, db_name, properties)
                db_ids[db_name] = db_id
                print(f"  Created: {db_id}")
            except httpx.HTTPStatusError as e:
                print(f"  Error: {e.response.text}")
                continue

        print("\n" + "=" * 50)
        print("Add these to your .env file:\n")

        env_mapping = {
            "Inbox": "NOTION_INBOX_DB_ID",
            "Tasks": "NOTION_TASKS_DB_ID",
            "People": "NOTION_PEOPLE_DB_ID",
            "Projects": "NOTION_PROJECTS_DB_ID",
            "Places": "NOTION_PLACES_DB_ID",
            "Preferences": "NOTION_PREFERENCES_DB_ID",
            "Patterns": "NOTION_PATTERNS_DB_ID",
            "Emails": "NOTION_EMAILS_DB_ID",
            "Log": "NOTION_LOG_DB_ID",
        }

        for db_name, env_var in env_mapping.items():
            db_id = db_ids.get(db_name, "")
            print(f"{env_var}={db_id}")

        print("\n" + "=" * 50)
        print("Done! Remember to share the databases with your integration.")


if __name__ == "__main__":
    asyncio.run(main())
