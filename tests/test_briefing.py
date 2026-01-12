"""Tests for the morning briefing generator."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from assistant.services.briefing import (
    BriefingGenerator,
    generate_briefing,
)


def make_notion_task(
    title: str,
    due_date: datetime | None = None,
    priority: str | None = None,
    status: str = "todo",
) -> dict:
    """Create a mock Notion task page response."""
    page = {
        "id": f"task-{title.replace(' ', '-')}",
        "properties": {
            "title": {"title": [{"text": {"content": title}}]},
            "status": {"select": {"name": status}},
        },
    }
    if due_date:
        page["properties"]["due_date"] = {"date": {"start": due_date.isoformat()}}
    if priority:
        page["properties"]["priority"] = {"select": {"name": priority}}
    return page


def make_notion_inbox_item(
    raw_input: str,
    interpretation: str | None = None,
    confidence: int = 50,
) -> dict:
    """Create a mock Notion inbox item page response."""
    page = {
        "id": f"inbox-{raw_input[:10].replace(' ', '-')}",
        "properties": {
            "raw_input": {"rich_text": [{"text": {"content": raw_input}}]},
            "confidence": {"number": confidence},
            "needs_clarification": {"checkbox": True},
            "processed": {"checkbox": False},
        },
    }
    if interpretation:
        page["properties"]["interpretation"] = {
            "rich_text": [{"text": {"content": interpretation}}]
        }
    return page


class TestBriefingGeneratorInit:
    """Tests for BriefingGenerator initialization."""

    def test_init_with_notion_client(self):
        """BriefingGenerator accepts a custom NotionClient."""
        mock_notion = MagicMock()
        generator = BriefingGenerator(notion_client=mock_notion)
        assert generator.notion is mock_notion

    def test_init_without_notion(self):
        """BriefingGenerator handles missing Notion configuration."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator()
            assert generator.notion is None

    def test_init_with_timezone(self):
        """BriefingGenerator uses configured timezone."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "America/Los_Angeles"
            generator = BriefingGenerator()
            assert generator.timezone == pytz.timezone("America/Los_Angeles")


class TestBriefingGeneratorExtractors:
    """Tests for BriefingGenerator extraction helper methods."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()

    def test_extract_title_present(self):
        """_extract_title extracts title from Notion page."""
        page = make_notion_task("Buy groceries")
        assert self.generator._extract_title(page) == "Buy groceries"

    def test_extract_title_missing(self):
        """_extract_title returns 'Untitled' when title is missing."""
        page = {"properties": {}}
        assert self.generator._extract_title(page) == "Untitled"

    def test_extract_title_empty_list(self):
        """_extract_title handles empty title list."""
        page = {"properties": {"title": {"title": []}}}
        assert self.generator._extract_title(page) == "Untitled"

    def test_extract_text_present(self):
        """_extract_text extracts rich text content."""
        page = make_notion_inbox_item("do the thing")
        assert self.generator._extract_text(page, "raw_input") == "do the thing"

    def test_extract_text_missing(self):
        """_extract_text returns empty string when field is missing."""
        page = {"properties": {}}
        assert self.generator._extract_text(page, "raw_input") == ""

    def test_extract_select_present(self):
        """_extract_select extracts select option."""
        page = make_notion_task("Task", priority="high")
        assert self.generator._extract_select(page, "priority") == "high"

    def test_extract_select_missing(self):
        """_extract_select returns None when field is missing."""
        page = {"properties": {}}
        assert self.generator._extract_select(page, "priority") is None

    def test_extract_date_datetime_format(self):
        """_extract_date parses datetime with time."""
        dt = datetime(2026, 1, 15, 14, 30, tzinfo=pytz.UTC)
        page = {"properties": {"due_date": {"date": {"start": dt.isoformat()}}}}
        result = self.generator._extract_date(page, "due_date")
        assert result is not None
        assert result.day == 15

    def test_extract_date_date_only_format(self):
        """_extract_date parses date without time."""
        page = {"properties": {"due_date": {"date": {"start": "2026-01-15"}}}}
        result = self.generator._extract_date(page, "due_date")
        assert result is not None
        assert result.day == 15

    def test_extract_date_missing(self):
        """_extract_date returns None when date is missing."""
        page = {"properties": {}}
        assert self.generator._extract_date(page, "due_date") is None

    def test_extract_date_null_value(self):
        """_extract_date handles null date value."""
        page = {"properties": {"due_date": {"date": None}}}
        assert self.generator._extract_date(page, "due_date") is None


class TestBriefingGeneratorPriorityIcons:
    """Tests for priority icon formatting."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()

    def test_urgent_priority_icon(self):
        """Urgent priority shows red circle."""
        assert self.generator._get_priority_icon("urgent") == "🔴 "

    def test_high_priority_icon(self):
        """High priority shows orange circle."""
        assert self.generator._get_priority_icon("high") == "🟠 "

    def test_medium_priority_icon(self):
        """Medium priority has no icon."""
        assert self.generator._get_priority_icon("medium") == ""

    def test_low_priority_icon(self):
        """Low priority has no icon."""
        assert self.generator._get_priority_icon("low") == ""

    def test_someday_priority_icon(self):
        """Someday priority shows thought bubble."""
        assert self.generator._get_priority_icon("someday") == "💭 "

    def test_none_priority_icon(self):
        """None priority returns empty string."""
        assert self.generator._get_priority_icon(None) == ""


class TestBriefingGeneratorRelativeDay:
    """Tests for relative day formatting."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()
        self.now = datetime(2026, 1, 11, 9, 0, tzinfo=pytz.UTC)

    def test_today(self):
        """Same day shows 'Today'."""
        date = datetime(2026, 1, 11, 14, 0, tzinfo=pytz.UTC)
        assert self.generator._format_relative_day(date, self.now) == "Today"

    def test_tomorrow(self):
        """Next day shows 'Tomorrow'."""
        date = datetime(2026, 1, 12, 14, 0, tzinfo=pytz.UTC)
        assert self.generator._format_relative_day(date, self.now) == "Tomorrow"

    def test_weekday_name(self):
        """2-6 days away shows weekday name."""
        # Jan 11 2026 is Sunday, Jan 14 is Wednesday
        date = datetime(2026, 1, 14, 14, 0, tzinfo=pytz.UTC)
        result = self.generator._format_relative_day(date, self.now)
        assert result == "Wednesday"

    def test_more_than_week(self):
        """More than 7 days shows 'In X days'."""
        date = datetime(2026, 1, 20, 14, 0, tzinfo=pytz.UTC)
        result = self.generator._format_relative_day(date, self.now)
        assert result == "In 9 days"


class TestBriefingGeneratorFormatTasks:
    """Tests for task formatting."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()

    def test_format_tasks_due_today_empty(self):
        """Empty task list returns None."""
        result = self.generator._format_tasks_due_today([])
        assert result is None

    def test_format_tasks_due_today_single(self):
        """Single task is formatted correctly."""
        tasks = [make_notion_task("Buy milk")]
        result = self.generator._format_tasks_due_today(tasks)
        assert result is not None
        assert "✅ **DUE TODAY**" in result
        assert "• Buy milk" in result

    def test_format_tasks_due_today_with_priority(self):
        """Tasks with priority show icons."""
        tasks = [
            make_notion_task("Urgent task", priority="urgent"),
            make_notion_task("High task", priority="high"),
        ]
        result = self.generator._format_tasks_due_today(tasks)
        assert "🔴 Urgent task" in result
        assert "🟠 High task" in result

    def test_format_tasks_due_today_with_status(self):
        """Tasks with non-standard status show status suffix."""
        tasks = [make_notion_task("In progress task", status="doing")]
        result = self.generator._format_tasks_due_today(tasks)
        assert "[doing]" in result

    def test_format_tasks_due_today_limit(self):
        """More than 5 tasks shows '...and X more'."""
        tasks = [make_notion_task(f"Task {i}") for i in range(7)]
        result = self.generator._format_tasks_due_today(tasks)
        assert "_...and 2 more_" in result

    def test_format_tasks_due_today_exactly_five(self):
        """Exactly 5 tasks doesn't show more message."""
        tasks = [make_notion_task(f"Task {i}") for i in range(5)]
        result = self.generator._format_tasks_due_today(tasks)
        assert "more" not in result


class TestBriefingGeneratorFormatFlagged:
    """Tests for flagged items formatting."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()

    def test_format_flagged_empty(self):
        """Empty flagged list returns None."""
        result = self.generator._format_flagged_items([])
        assert result is None

    def test_format_flagged_single(self):
        """Single flagged item is formatted correctly."""
        items = [make_notion_inbox_item("do the thing")]
        result = self.generator._format_flagged_items(items)
        assert result is not None
        assert "⚠️ **NEEDS CLARIFICATION** (1 item)" in result
        assert '"do the thing"' in result

    def test_format_flagged_plural(self):
        """Multiple flagged items show plural."""
        items = [
            make_notion_inbox_item("item 1"),
            make_notion_inbox_item("item 2"),
        ]
        result = self.generator._format_flagged_items(items)
        assert "(2 items)" in result

    def test_format_flagged_with_interpretation(self):
        """Flagged items with interpretation show it."""
        items = [make_notion_inbox_item("something", interpretation="Maybe a task")]
        result = self.generator._format_flagged_items(items)
        assert "_→ Maybe a task_" in result

    def test_format_flagged_truncates_long_input(self):
        """Long raw input is truncated."""
        long_text = "a" * 100
        items = [make_notion_inbox_item(long_text)]
        result = self.generator._format_flagged_items(items)
        assert "..." in result
        assert len(result) < len(long_text) + 100  # Reasonable bound

    def test_format_flagged_limit(self):
        """More than 3 flagged items shows '...and X more'."""
        items = [make_notion_inbox_item(f"item {i}") for i in range(5)]
        result = self.generator._format_flagged_items(items)
        assert "_...and 2 more_" in result


class TestBriefingGeneratorFormatThisWeek:
    """Tests for 'this week' section formatting."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()
        self.now = datetime(2026, 1, 11, 9, 0, tzinfo=pytz.UTC)

    def test_format_this_week_empty(self):
        """Empty task list returns None."""
        result = self.generator._format_this_week([], self.now)
        assert result is None

    def test_format_this_week_single(self):
        """Single upcoming task is formatted correctly."""
        tomorrow = datetime(2026, 1, 12, 14, 0, tzinfo=pytz.UTC)
        tasks = [make_notion_task("Future task", due_date=tomorrow)]
        result = self.generator._format_this_week(tasks, self.now)
        assert result is not None
        assert "📊 **THIS WEEK** (1 upcoming)" in result
        assert "**Tomorrow:**" in result
        assert "Future task" in result

    def test_format_this_week_grouped_by_day(self):
        """Tasks are grouped by day."""
        tomorrow = datetime(2026, 1, 12, 14, 0, tzinfo=pytz.UTC)
        day_after = datetime(2026, 1, 13, 14, 0, tzinfo=pytz.UTC)
        tasks = [
            make_notion_task("Tomorrow task 1", due_date=tomorrow),
            make_notion_task("Tomorrow task 2", due_date=tomorrow),
            make_notion_task("Day after task", due_date=day_after),
        ]
        result = self.generator._format_this_week(tasks, self.now)
        assert "**Tomorrow:**" in result
        assert "Tomorrow task 1" in result
        assert "Tomorrow task 2" in result
        # Jan 13 2026 is Tuesday
        assert "**Tuesday:**" in result
        assert "Day after task" in result

    def test_format_this_week_with_priority(self):
        """Tasks with priority show icons."""
        tomorrow = datetime(2026, 1, 12, 14, 0, tzinfo=pytz.UTC)
        tasks = [make_notion_task("Urgent future", due_date=tomorrow, priority="urgent")]
        result = self.generator._format_this_week(tasks, self.now)
        assert "🔴 Urgent future" in result


class TestBriefingGeneratorGenerate:
    """Tests for the main generate_morning_briefing method."""

    @pytest.mark.asyncio
    async def test_generate_no_notion(self):
        """Briefing with no Notion shows configuration message."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator()
            result = await generator.generate_morning_briefing()
            assert "*Notion not configured*" in result
            assert "Reply /debrief" in result

    @pytest.mark.asyncio
    async def test_generate_with_tasks(self):
        """Briefing includes tasks section when tasks exist."""
        mock_notion = AsyncMock()
        now = datetime.now(pytz.UTC)
        mock_notion.query_tasks.return_value = [
            make_notion_task("Task for today", due_date=now, priority="high"),
        ]
        mock_notion.query_inbox.return_value = []

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            result = await generator.generate_morning_briefing()

        assert "Good morning!" in result
        assert "✅ **DUE TODAY**" in result
        assert "Task for today" in result
        mock_notion.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_with_flagged_items(self):
        """Briefing includes flagged items section."""
        mock_notion = AsyncMock()
        mock_notion.query_tasks.return_value = []
        mock_notion.query_inbox.return_value = [
            make_notion_inbox_item("unclear thing", interpretation="Possibly a task"),
        ]

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            result = await generator.generate_morning_briefing()

        assert "⚠️ **NEEDS CLARIFICATION**" in result
        assert "unclear thing" in result

    @pytest.mark.asyncio
    async def test_generate_with_this_week(self):
        """Briefing includes this week section when upcoming tasks exist."""
        mock_notion = AsyncMock()
        now = datetime.now(pytz.UTC)
        tomorrow = now + timedelta(days=1)

        # First call for today's tasks, second for this week
        mock_notion.query_tasks.side_effect = [
            [],  # No tasks today
            [make_notion_task("Future task", due_date=tomorrow)],  # This week
        ]
        mock_notion.query_inbox.return_value = []

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            result = await generator.generate_morning_briefing()

        assert "📊 **THIS WEEK**" in result
        assert "Future task" in result

    @pytest.mark.asyncio
    async def test_generate_handles_notion_error(self):
        """Briefing handles Notion API errors gracefully."""
        mock_notion = AsyncMock()
        mock_notion.query_tasks.side_effect = Exception("API error")

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            result = await generator.generate_morning_briefing()

        assert "*Could not fetch data from Notion" in result
        assert "API error" in result
        mock_notion.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_empty_briefing(self):
        """Briefing with no data still has greeting and closing."""
        mock_notion = AsyncMock()
        mock_notion.query_tasks.return_value = []
        mock_notion.query_inbox.return_value = []

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            result = await generator.generate_morning_briefing()

        assert "Good morning!" in result
        assert "Reply /debrief anytime to review together." in result


class TestGenerateBriefingConvenience:
    """Tests for the convenience function."""

    @pytest.mark.asyncio
    async def test_generate_briefing_function(self):
        """generate_briefing convenience function works."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            result = await generate_briefing()
            assert "Good morning!" in result


class TestBriefingGeneratorCalendarSection:
    """Tests for calendar section placeholder."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()

    @pytest.mark.asyncio
    async def test_calendar_section_returns_none(self):
        """Calendar section returns None until implemented."""
        result = await self.generator._generate_calendar_section()
        assert result is None


class TestBriefingGeneratorEmailSection:
    """Tests for email section placeholder."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()

    @pytest.mark.asyncio
    async def test_email_section_returns_none(self):
        """Email section returns None until implemented."""
        result = await self.generator._generate_email_section()
        assert result is None


class TestBriefingGeneratorQueries:
    """Tests for Notion query methods."""

    @pytest.mark.asyncio
    async def test_get_tasks_due_today_no_notion(self):
        """_get_tasks_due_today returns empty list without Notion."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator()
            now = datetime.now(pytz.UTC)
            result = await generator._get_tasks_due_today(now, now)
            assert result == []

    @pytest.mark.asyncio
    async def test_get_tasks_due_today_with_notion(self):
        """_get_tasks_due_today queries Notion correctly."""
        mock_notion = AsyncMock()
        mock_notion.query_tasks.return_value = [make_notion_task("Task 1")]

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            now = datetime.now(pytz.UTC)
            end = now.replace(hour=23, minute=59)
            result = await generator._get_tasks_due_today(now, end)

        assert len(result) == 1
        mock_notion.query_tasks.assert_called_once()
        call_kwargs = mock_notion.query_tasks.call_args.kwargs
        assert call_kwargs["exclude_statuses"] == ["done", "cancelled", "deleted"]

    @pytest.mark.asyncio
    async def test_get_tasks_this_week_no_notion(self):
        """_get_tasks_this_week returns empty list without Notion."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator()
            now = datetime.now(pytz.UTC)
            result = await generator._get_tasks_this_week(now, now + timedelta(days=7))
            assert result == []

    @pytest.mark.asyncio
    async def test_get_flagged_items_no_notion(self):
        """_get_flagged_items returns empty list without Notion."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator()
            result = await generator._get_flagged_items()
            assert result == []

    @pytest.mark.asyncio
    async def test_get_flagged_items_with_notion(self):
        """_get_flagged_items queries Notion correctly."""
        mock_notion = AsyncMock()
        mock_notion.query_inbox.return_value = [make_notion_inbox_item("unclear")]

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            result = await generator._get_flagged_items()

        assert len(result) == 1
        mock_notion.query_inbox.assert_called_once_with(
            needs_clarification=True,
            processed=False,
            limit=10,
        )
