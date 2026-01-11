from datetime import datetime, timedelta
from typing import Any
import pytz

from assistant.config import settings
from assistant.notion import NotionClient


class BriefingGenerator:
    def __init__(self):
        self.notion = NotionClient() if settings.has_notion else None
        self.timezone = pytz.timezone(settings.user_timezone)

    async def generate_morning_briefing(self) -> str:
        now = datetime.now(self.timezone)
        today_end = now.replace(hour=23, minute=59, second=59)

        sections = []
        sections.append(f"Good morning! Here's your day for {now.strftime('%A, %B %d')}:\n")

        if self.notion:
            try:
                tasks_today = await self._get_tasks_due_today(today_end)
                if tasks_today:
                    sections.append("**DUE TODAY**")
                    for task in tasks_today[:5]:
                        title = self._extract_title(task)
                        sections.append(f"* {title}")
                    sections.append("")

                flagged = await self._get_flagged_items()
                if flagged:
                    sections.append(f"**NEEDS CLARIFICATION** ({len(flagged)} items)")
                    for item in flagged[:3]:
                        text = self._extract_text(item, "raw_input")
                        preview = text[:50] + "..." if len(text) > 50 else text
                        sections.append(f"* \"{preview}\"")
                    sections.append("")

            except Exception:
                sections.append("*Could not fetch tasks from Notion*\n")
            finally:
                await self.notion.close()
        else:
            sections.append("*Notion not configured*\n")

        sections.append("Reply /debrief anytime to review together.")

        return "\n".join(sections)

    async def _get_tasks_due_today(self, today_end: datetime) -> list[dict[str, Any]]:
        if not self.notion:
            return []

        return await self.notion.query_tasks(due_before=today_end)

    async def _get_flagged_items(self) -> list[dict[str, Any]]:
        if not self.notion:
            return []

        result = await self.notion._request(
            "POST",
            f"/databases/{settings.notion_inbox_db_id}/query",
            {
                "filter": {
                    "and": [
                        {"property": "needs_clarification", "checkbox": {"equals": True}},
                        {"property": "processed", "checkbox": {"equals": False}},
                    ]
                },
                "page_size": 10,
            },
        )
        return result.get("results", [])

    def _extract_title(self, page: dict[str, Any]) -> str:
        props = page.get("properties", {})
        title_prop = props.get("title", {})
        title_list = title_prop.get("title", [])
        if title_list:
            return title_list[0].get("text", {}).get("content", "Untitled")
        return "Untitled"

    def _extract_text(self, page: dict[str, Any], field: str) -> str:
        props = page.get("properties", {})
        field_prop = props.get(field, {})
        text_list = field_prop.get("rich_text", [])
        if text_list:
            return text_list[0].get("text", {}).get("content", "")
        return ""
