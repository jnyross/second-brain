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


def make_notion_pattern(
    trigger: str,
    meaning: str,
    pattern_type: str | None = None,
    confidence: int = 80,
) -> dict:
    """Create a mock Notion pattern page response."""
    page = {
        "id": f"pattern-{trigger[:10].replace(' ', '-')}",
        "properties": {
            "title": {"title": [{"text": {"content": trigger}}]},
            "trigger": {"rich_text": [{"text": {"content": trigger}}]},
            "meaning": {"rich_text": [{"text": {"content": meaning}}]},
            "confidence": {"number": confidence},
        },
    }
    if pattern_type:
        page["properties"]["type"] = {"select": {"name": pattern_type}}
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
            # Compare timezone zones by name rather than object identity
            assert str(generator.timezone) == str(pytz.timezone("America/Los_Angeles"))


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


class TestBriefingGeneratorTILSection:
    """Tests for Today I Learned section (T-111)."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()

    @pytest.mark.asyncio
    async def test_til_section_no_notion(self):
        """TIL section returns None without Notion."""
        now = datetime.now(pytz.UTC)
        result = await self.generator._generate_til_section(now)
        assert result is None

    @pytest.mark.asyncio
    async def test_til_section_no_patterns(self):
        """TIL section returns None when no patterns found."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns.return_value = []

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            now = datetime.now(pytz.UTC)
            result = await generator._generate_til_section(now)

        assert result is None

    @pytest.mark.asyncio
    async def test_til_section_with_patterns(self):
        """TIL section formats patterns correctly."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns.return_value = [
            make_notion_pattern("Jess", "Tess", "person_alias", 85),
            make_notion_pattern("cafe", "Corner Coffee", "place_alias", 75),
        ]

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            now = datetime.now(pytz.UTC)
            result = await generator._generate_til_section(now)

        assert result is not None
        assert "🧠 **TODAY I LEARNED**" in result
        assert "Jess" in result
        assert "Tess" in result
        assert "cafe" in result
        assert "Corner Coffee" in result
        assert "👤" in result  # person_alias icon
        assert "📍" in result  # place_alias icon

    @pytest.mark.asyncio
    async def test_til_section_queries_with_correct_filters(self):
        """TIL section queries patterns with min confidence and created_after."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns.return_value = []

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            now = datetime.now(pytz.UTC)
            await generator._generate_til_section(now)

        mock_notion.query_patterns.assert_called_once()
        call_kwargs = mock_notion.query_patterns.call_args.kwargs
        assert call_kwargs["min_confidence"] == 70
        assert call_kwargs["limit"] == 5
        # Should query last 24 hours
        assert "created_after" in call_kwargs

    @pytest.mark.asyncio
    async def test_til_section_handles_api_error(self):
        """TIL section handles API errors gracefully."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns.side_effect = Exception("API error")

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            now = datetime.now(pytz.UTC)
            result = await generator._generate_til_section(now)

        assert result is None  # Graceful handling


class TestBriefingGeneratorFormatTIL:
    """Tests for TIL formatting helper."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()

    def test_format_til_empty(self):
        """_format_til_section returns None for empty list."""
        result = self.generator._format_til_section([])
        assert result is None

    def test_format_til_basic(self):
        """_format_til_section formats patterns with trigger and meaning."""
        patterns = [make_notion_pattern("mike", "Mike Smith")]
        result = self.generator._format_til_section(patterns)

        assert "🧠 **TODAY I LEARNED**" in result
        assert '"mike"' in result
        assert '"Mike Smith"' in result
        assert "→" in result

    def test_format_til_truncates_long_trigger(self):
        """_format_til_section truncates long trigger text."""
        long_trigger = "a" * 50
        patterns = [make_notion_pattern(long_trigger, "short")]
        result = self.generator._format_til_section(patterns)

        # Should be truncated to 30 chars + "..."
        assert "..." in result
        assert long_trigger not in result

    def test_format_til_truncates_long_meaning(self):
        """_format_til_section truncates long meaning text."""
        long_meaning = "b" * 50
        patterns = [make_notion_pattern("short", long_meaning)]
        result = self.generator._format_til_section(patterns)

        assert "..." in result
        assert long_meaning not in result

    def test_format_til_person_alias_icon(self):
        """_format_til_section shows person icon for person_alias type."""
        patterns = [make_notion_pattern("nick", "Nicholas", "person_alias")]
        result = self.generator._format_til_section(patterns)
        assert "👤" in result

    def test_format_til_place_alias_icon(self):
        """_format_til_section shows place icon for place_alias type."""
        patterns = [make_notion_pattern("work", "Office Building", "place_alias")]
        result = self.generator._format_til_section(patterns)
        assert "📍" in result

    def test_format_til_project_alias_icon(self):
        """_format_til_section shows project icon for project_alias type."""
        patterns = [make_notion_pattern("sb", "Second Brain", "project_alias")]
        result = self.generator._format_til_section(patterns)
        assert "📁" in result

    def test_format_til_preference_icon(self):
        """_format_til_section shows settings icon for preference type."""
        patterns = [make_notion_pattern("morning", "9 AM", "preference")]
        result = self.generator._format_til_section(patterns)
        assert "⚙️" in result

    def test_format_til_no_icon_for_unknown_type(self):
        """_format_til_section uses no icon for unknown type."""
        patterns = [make_notion_pattern("test", "test value", "unknown_type")]
        result = self.generator._format_til_section(patterns)
        # Should still format, just without type icon
        assert "test" in result

    def test_format_til_limits_to_five(self):
        """_format_til_section limits to 5 patterns and shows more indicator."""
        patterns = [make_notion_pattern(f"trigger{i}", f"meaning{i}") for i in range(7)]
        result = self.generator._format_til_section(patterns)

        # Should show "...and X more"
        assert "2 more" in result

    def test_format_til_skips_incomplete_patterns(self):
        """_format_til_section skips patterns without trigger or meaning."""
        # Pattern with empty meaning
        incomplete = {
            "id": "pattern-incomplete",
            "properties": {
                "title": {"title": [{"text": {"content": "trigger"}}]},
                "trigger": {"rich_text": [{"text": {"content": "trigger"}}]},
                "meaning": {"rich_text": []},  # Empty meaning
                "confidence": {"number": 80},
            },
        }
        complete = make_notion_pattern("good", "good value")
        result = self.generator._format_til_section([incomplete, complete])

        # Should still format the complete one
        assert "good" in result


class TestBriefingGeneratorExtractNumber:
    """Tests for _extract_number helper."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            self.generator = BriefingGenerator()

    def test_extract_number_present(self):
        """_extract_number extracts number from Notion page."""
        page = {"properties": {"confidence": {"number": 85}}}
        result = self.generator._extract_number(page, "confidence")
        assert result == 85

    def test_extract_number_missing(self):
        """_extract_number returns None for missing field."""
        page = {"properties": {}}
        result = self.generator._extract_number(page, "confidence")
        assert result is None

    def test_extract_number_zero(self):
        """_extract_number correctly returns zero."""
        page = {"properties": {"count": {"number": 0}}}
        result = self.generator._extract_number(page, "count")
        assert result == 0


class TestBriefingTILIntegration:
    """Integration tests for TIL in full briefing."""

    @pytest.mark.asyncio
    async def test_til_section_included_in_briefing(self):
        """TIL section is included in full briefing when patterns exist."""
        mock_notion = AsyncMock()
        mock_notion.query_tasks.return_value = []
        mock_notion.query_inbox.return_value = []
        mock_notion.query_patterns.return_value = [
            make_notion_pattern("jess", "Tess", "person_alias"),
        ]

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            result = await generator.generate_morning_briefing()

        assert "🧠 **TODAY I LEARNED**" in result
        assert "jess" in result
        assert "Tess" in result

    @pytest.mark.asyncio
    async def test_til_section_not_included_when_no_patterns(self):
        """TIL section is omitted when no patterns exist."""
        mock_notion = AsyncMock()
        mock_notion.query_tasks.return_value = []
        mock_notion.query_inbox.return_value = []
        mock_notion.query_patterns.return_value = []

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            result = await generator.generate_morning_briefing()

        assert "TODAY I LEARNED" not in result


class TestT111AcceptanceTest:
    """Acceptance tests for T-111: Today I Learned summary."""

    @pytest.mark.asyncio
    async def test_learned_patterns_appear_in_briefing(self):
        """
        AT-111: Patterns learned in last 24 hours appear in morning briefing.

        Given: User has corrected "Jess" to "Tess" yesterday
        And: Pattern was stored with confidence >= 70%
        When: Morning briefing is generated
        Then: Briefing includes "Today I Learned" section
        And: Section shows "Jess" → "Tess" pattern
        """
        # Simulate pattern learned yesterday
        mock_notion = AsyncMock()
        mock_notion.query_tasks.return_value = []
        mock_notion.query_inbox.return_value = []
        mock_notion.query_patterns.return_value = [
            make_notion_pattern("jess", "Tess", "person_alias", confidence=85),
        ]

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "UTC"
            generator = BriefingGenerator(notion_client=mock_notion)
            result = await generator.generate_morning_briefing()

        # Verify TIL section present
        assert "🧠 **TODAY I LEARNED**" in result
        # Verify pattern shown
        assert "jess" in result.lower()
        assert "tess" in result.lower()
        # Verify person icon shown for person_alias type
        assert "👤" in result


class TestTravelTimeInBriefing:
    """Tests for T-155: Travel times in morning briefing."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "America/Los_Angeles"
            mock_settings.user_home_address = ""
            mock_settings.google_maps_api_key = ""
            self.generator = BriefingGenerator()

    def test_format_calendar_events_without_travel_info(self):
        """Calendar events format correctly without travel info."""
        from assistant.google.calendar import CalendarEvent

        la_tz = pytz.timezone("America/Los_Angeles")
        events = [
            CalendarEvent(
                event_id="event-1",
                title="Dentist appointment",
                start_time=la_tz.localize(datetime(2026, 1, 13, 14, 0)),
                end_time=la_tz.localize(datetime(2026, 1, 13, 15, 0)),
                timezone="America/Los_Angeles",
                attendees=[],
                location="123 Main St",
            ),
        ]
        result = self.generator._format_calendar_events(events, travel_info=None)

        assert result is not None
        assert "📅 **TODAY**" in result
        assert "14:00 - Dentist appointment" in result
        assert "(123 Main St)" in result
        assert "Leave by" not in result  # No travel info

    def test_format_calendar_events_with_travel_info(self):
        """Calendar events include 'Leave by' when travel info is provided (AT-122)."""
        from assistant.google.calendar import CalendarEvent
        from assistant.google.maps import TravelTime
        from assistant.services.briefing import TravelInfo

        la_tz = pytz.timezone("America/Los_Angeles")
        event_time = la_tz.localize(datetime(2026, 1, 13, 14, 0))
        events = [
            CalendarEvent(
                event_id="event-1",
                title="Dentist appointment",
                start_time=event_time,
                end_time=la_tz.localize(datetime(2026, 1, 13, 15, 0)),
                timezone="America/Los_Angeles",
                attendees=[],
                location="123 Main St",
            ),
        ]

        # Create travel info with 20 min travel time
        travel_time = TravelTime(
            origin="Home Address",
            destination="123 Main St",
            distance_meters=10000,
            duration_seconds=1200,  # 20 min
            duration_in_traffic_seconds=None,
        )
        travel_info = {
            "event-1": TravelInfo(
                leave_by=event_time - timedelta(minutes=20),
                travel_time=travel_time,
                from_location="Home Address",
                to_location="123 Main St",
            ),
        }

        result = self.generator._format_calendar_events(events, travel_info=travel_info)

        assert result is not None
        assert "Leave by 13:40" in result
        assert "(20 min)" in result

    def test_format_tasks_with_travel_info(self):
        """Tasks with places show 'Leave by' departure time (AT-122)."""
        from assistant.google.maps import TravelTime
        from assistant.services.briefing import TravelInfo

        la_tz = pytz.timezone("America/Los_Angeles")
        due_time = la_tz.localize(datetime(2026, 1, 13, 14, 0))

        tasks = [
            {
                "id": "task-dentist",
                "properties": {
                    "title": {"title": [{"text": {"content": "Dentist appointment"}}]},
                    "status": {"select": {"name": "todo"}},
                    "priority": {"select": {"name": "high"}},
                    "due_date": {"date": {"start": due_time.isoformat()}},
                },
            },
        ]

        # Create travel info with 25 min travel time
        travel_time = TravelTime(
            origin="Home",
            destination="123 Main St",
            distance_meters=15000,
            duration_seconds=1500,  # 25 min
            duration_in_traffic_seconds=None,
        )
        travel_info = {
            "task-dentist": TravelInfo(
                leave_by=due_time - timedelta(minutes=25),
                travel_time=travel_time,
                from_location="Home",
                to_location="123 Main St",
            ),
        }

        result = self.generator._format_tasks_due_today(tasks, travel_info=travel_info)

        assert result is not None
        assert "✅ **DUE TODAY**" in result
        assert "Dentist appointment" in result
        assert "at 14:00" in result
        assert "Leave by 13:35" in result
        assert "(25 min)" in result


class TestTravelInfoDataclass:
    """Tests for TravelInfo dataclass."""

    def test_format_departure(self):
        """TravelInfo formats departure time correctly."""
        from assistant.google.maps import TravelTime
        from assistant.services.briefing import TravelInfo

        la_tz = pytz.timezone("America/Los_Angeles")
        leave_by = la_tz.localize(datetime(2026, 1, 13, 13, 40))

        travel_time = TravelTime(
            origin="Home",
            destination="Office",
            distance_meters=10000,
            duration_seconds=1200,  # 20 min
            duration_in_traffic_seconds=None,
        )
        info = TravelInfo(
            leave_by=leave_by,
            travel_time=travel_time,
            from_location="Home",
            to_location="Office",
        )

        result = info.format_departure(la_tz)
        assert result == "Leave by 13:40 (20 min)"

    def test_format_departure_with_traffic(self):
        """TravelInfo uses traffic-aware duration when available."""
        from assistant.google.maps import TravelTime
        from assistant.services.briefing import TravelInfo

        la_tz = pytz.timezone("America/Los_Angeles")
        leave_by = la_tz.localize(datetime(2026, 1, 13, 13, 30))

        travel_time = TravelTime(
            origin="Home",
            destination="Office",
            distance_meters=10000,
            duration_seconds=1200,  # 20 min without traffic
            duration_in_traffic_seconds=1800,  # 30 min with traffic
        )
        info = TravelInfo(
            leave_by=leave_by,
            travel_time=travel_time,
            from_location="Home",
            to_location="Office",
        )

        result = info.format_departure(la_tz)
        assert result == "Leave by 13:30 (30 min)"  # Uses traffic-aware time


class TestExtractPlaceIds:
    """Tests for _extract_place_ids helper."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = False
            mock_settings.user_timezone = "UTC"
            mock_settings.user_home_address = ""
            mock_settings.google_maps_api_key = ""
            self.generator = BriefingGenerator()

    def test_extract_place_ids_from_relation(self):
        """Extracts place IDs from Notion relation property."""
        task = {
            "properties": {
                "places": {
                    "relation": [
                        {"id": "place-123"},
                        {"id": "place-456"},
                    ]
                }
            }
        }
        result = self.generator._extract_place_ids(task)
        assert result == ["place-123", "place-456"]

    def test_extract_place_ids_from_multi_select(self):
        """Extracts place IDs from multi_select property (fallback)."""
        task = {
            "properties": {
                "place_ids": {
                    "multi_select": [
                        {"name": "place-789"},
                    ]
                }
            }
        }
        result = self.generator._extract_place_ids(task)
        assert result == ["place-789"]

    def test_extract_place_ids_from_rich_text(self):
        """Extracts place IDs from rich_text property (fallback)."""
        task = {
            "properties": {
                "place_ids": {
                    "rich_text": [
                        {"text": {"content": "place-abc, place-def"}}
                    ]
                }
            }
        }
        result = self.generator._extract_place_ids(task)
        assert result == ["place-abc", "place-def"]

    def test_extract_place_ids_empty(self):
        """Returns empty list when no places found."""
        task = {"properties": {}}
        result = self.generator._extract_place_ids(task)
        assert result == []


class TestAT122TravelTimeInMorningBriefing:
    """Acceptance test for AT-122: Travel Time in Morning Briefing.

    Given: User has task "Dentist at 2pm" with place "123 Main St"
    When: Morning briefing generated
    Then: Briefing includes travel estimate from home
    Pass condition: Briefing contains "Leave by X" with calculated departure time
    """

    @pytest.mark.asyncio
    async def test_at122_travel_time_in_briefing(self):
        """
        AT-122: Travel times appear in morning briefing for tasks with places.

        Given: User has task "Dentist at 2pm" with place "123 Main St"
        When: Morning briefing generated
        Then: Briefing includes travel estimate from home
        Pass condition: Briefing contains "Leave by X" with calculated departure time
        """
        from assistant.google.calendar import CalendarClient
        from assistant.google.maps import MapsClient, TravelTime

        # Mock Notion with a task that has a place
        mock_notion = AsyncMock()
        la_tz = pytz.timezone("America/Los_Angeles")
        due_time = la_tz.localize(datetime(2026, 1, 13, 14, 0))  # 2pm

        # Task "Dentist at 2pm" with place
        mock_notion.query_tasks.return_value = [
            {
                "id": "task-dentist-123",
                "properties": {
                    "title": {"title": [{"text": {"content": "Dentist"}}]},
                    "status": {"select": {"name": "todo"}},
                    "priority": {"select": {"name": "high"}},
                    "due_date": {"date": {"start": due_time.isoformat()}},
                    "places": {"relation": [{"id": "place-123-main-st"}]},
                },
            },
        ]
        mock_notion.query_inbox.return_value = []
        mock_notion.query_patterns.return_value = []

        # Place "123 Main St"
        mock_notion.get_place.return_value = {
            "id": "place-123-main-st",
            "properties": {
                "name": {"title": [{"text": {"content": "Dr Smith Office"}}]},
                "address": {"rich_text": [{"text": {"content": "123 Main St"}}]},
            },
        }

        # Mock Maps with 20 min travel time
        mock_maps = AsyncMock(spec=MapsClient)
        mock_maps.get_travel_time.return_value = TravelTime(
            origin="456 Home Ave",
            destination="123 Main St",
            distance_meters=10000,
            duration_seconds=1200,  # 20 min
            duration_in_traffic_seconds=None,
        )

        # Mock Calendar (no events for this test)
        mock_calendar = MagicMock(spec=CalendarClient)
        mock_calendar.is_authenticated.return_value = False

        with patch("assistant.services.briefing.settings") as mock_settings:
            mock_settings.has_notion = True
            mock_settings.user_timezone = "America/Los_Angeles"
            mock_settings.user_home_address = "456 Home Ave"
            mock_settings.google_maps_api_key = "test-key"

            generator = BriefingGenerator(
                notion_client=mock_notion,
                calendar_client=mock_calendar,
                maps_client=mock_maps,
            )
            result = await generator.generate_morning_briefing()

        # AT-122 Pass condition: Briefing contains "Leave by X"
        assert "Leave by" in result, f"AT-122 FAIL: 'Leave by' not found in briefing:\n{result}"
        assert "13:40" in result, f"AT-122 FAIL: Expected departure time '13:40' not found:\n{result}"
        assert "20 min" in result, f"AT-122 FAIL: Expected travel duration not found:\n{result}"

        # Verify Maps API was called correctly
        mock_maps.get_travel_time.assert_called_once_with(
            origin="456 Home Ave",
            destination="123 Main St",
            mode="driving",
        )
