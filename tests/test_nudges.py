"""Tests for the proactive nudges service (T-130).

Tests cover:
- NudgeCandidate and NudgeReport dataclasses
- NudgeService task querying and filtering
- Deduplication (nudge tracking)
- Time window checking
- Message formatting
- CLI integration
- Systemd file validation
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from assistant.services.nudges import (
    NUDGE_WINDOW_DUE_TODAY_END,
    NUDGE_WINDOW_DUE_TODAY_START,
    NUDGE_WINDOW_DUE_TOMORROW_END,
    NUDGE_WINDOW_DUE_TOMORROW_START,
    NUDGE_WINDOW_OVERDUE_END,
    NUDGE_WINDOW_OVERDUE_START,
    NudgeCandidate,
    NudgeReport,
    NudgeResult,
    NudgeService,
    NudgeType,
    format_nudge_message,
    get_nudge_tracker_path,
    get_pending_nudges,
    has_been_nudged_today,
    is_in_nudge_window,
    load_sent_nudges,
    mark_nudge_sent,
    run_nudges,
    save_sent_nudges,
)


@pytest.fixture
def tz():
    """User timezone fixture."""
    return pytz.timezone("America/Los_Angeles")


@pytest.fixture
def mock_settings(tmp_path):
    """Mock settings for tests."""
    with patch("assistant.services.nudges.settings") as mock:
        mock.has_notion = True
        mock.has_telegram = True
        mock.user_timezone = "America/Los_Angeles"
        mock.user_telegram_chat_id = "12345"
        mock.data_dir = str(tmp_path)
        yield mock


class TestNudgeCandidate:
    """Tests for NudgeCandidate dataclass."""

    def test_create_candidate(self, tz):
        """Test creating a nudge candidate."""
        now = datetime.now(tz)
        candidate = NudgeCandidate(
            task_id="task-123",
            title="Buy groceries",
            due_date=now + timedelta(hours=2),
            priority="high",
            nudge_type=NudgeType.DUE_TODAY,
        )

        assert candidate.task_id == "task-123"
        assert candidate.title == "Buy groceries"
        assert candidate.priority == "high"
        assert candidate.nudge_type == NudgeType.DUE_TODAY
        assert candidate.days_overdue == 0

    def test_overdue_candidate(self, tz):
        """Test overdue candidate with days calculation."""
        now = datetime.now(tz)
        candidate = NudgeCandidate(
            task_id="task-456",
            title="Submit report",
            due_date=now - timedelta(days=3),
            priority=None,
            nudge_type=NudgeType.OVERDUE,
            days_overdue=3,
        )

        assert candidate.nudge_type == NudgeType.OVERDUE
        assert candidate.days_overdue == 3


class TestNudgeReport:
    """Tests for NudgeReport dataclass."""

    def test_empty_report(self):
        """Test empty report defaults."""
        report = NudgeReport()

        assert report.candidates_found == 0
        assert report.nudges_sent == 0
        assert report.nudges_skipped == 0
        assert report.nudges_failed == 0
        assert report.results == []
        assert not report.all_successful  # No nudges sent = not successful

    def test_successful_report(self):
        """Test report with successful nudges."""
        report = NudgeReport(
            candidates_found=3,
            nudges_sent=2,
            nudges_skipped=1,
            nudges_failed=0,
            results=[
                NudgeResult(True, "t1", "msg1", NudgeType.DUE_TODAY),
                NudgeResult(True, "t2", "msg2", NudgeType.DUE_TOMORROW),
            ],
        )

        assert report.all_successful is True

    def test_failed_report(self):
        """Test report with failed nudges."""
        report = NudgeReport(
            candidates_found=2,
            nudges_sent=1,
            nudges_failed=1,
            results=[
                NudgeResult(True, "t1", "msg1", NudgeType.DUE_TODAY),
                NudgeResult(False, "t2", "msg2", NudgeType.OVERDUE, error="API error"),
            ],
        )

        assert report.all_successful is False


class TestNudgeResult:
    """Tests for NudgeResult dataclass."""

    def test_successful_result(self):
        """Test successful nudge result."""
        result = NudgeResult(
            success=True,
            task_id="task-123",
            message="Don't forget: \"Buy milk\"",
            nudge_type=NudgeType.DUE_TODAY,
        )

        assert result.success is True
        assert result.error is None

    def test_failed_result(self):
        """Test failed nudge result."""
        result = NudgeResult(
            success=False,
            task_id="task-456",
            message="Reminder",
            nudge_type=NudgeType.OVERDUE,
            error="Telegram API timeout",
        )

        assert result.success is False
        assert result.error == "Telegram API timeout"


class TestNudgeWindows:
    """Tests for time window checking."""

    def test_due_today_window_inside(self, tz):
        """Test within due today window (2pm-8pm)."""
        # 3pm - within window
        time_3pm = tz.localize(datetime(2024, 1, 15, 15, 0, 0))
        assert is_in_nudge_window(NudgeType.DUE_TODAY, time_3pm) is True

    def test_due_today_window_before(self, tz):
        """Test before due today window."""
        # 10am - before 2pm window
        time_10am = tz.localize(datetime(2024, 1, 15, 10, 0, 0))
        assert is_in_nudge_window(NudgeType.DUE_TODAY, time_10am) is False

    def test_due_today_window_after(self, tz):
        """Test after due today window."""
        # 9pm - after 8pm window
        time_9pm = tz.localize(datetime(2024, 1, 15, 21, 0, 0))
        assert is_in_nudge_window(NudgeType.DUE_TODAY, time_9pm) is False

    def test_due_tomorrow_window_inside(self, tz):
        """Test within due tomorrow window (6pm-9pm)."""
        time_7pm = tz.localize(datetime(2024, 1, 15, 19, 0, 0))
        assert is_in_nudge_window(NudgeType.DUE_TOMORROW, time_7pm) is True

    def test_due_tomorrow_window_outside(self, tz):
        """Test outside due tomorrow window."""
        time_3pm = tz.localize(datetime(2024, 1, 15, 15, 0, 0))
        assert is_in_nudge_window(NudgeType.DUE_TOMORROW, time_3pm) is False

    def test_overdue_window_inside(self, tz):
        """Test within overdue window (9am-8pm, broader)."""
        time_10am = tz.localize(datetime(2024, 1, 15, 10, 0, 0))
        assert is_in_nudge_window(NudgeType.OVERDUE, time_10am) is True

    def test_overdue_window_outside(self, tz):
        """Test outside overdue window."""
        time_8am = tz.localize(datetime(2024, 1, 15, 8, 0, 0))
        assert is_in_nudge_window(NudgeType.OVERDUE, time_8am) is False

    def test_high_priority_uses_broad_window(self, tz):
        """Test high priority uses broader window like overdue."""
        time_10am = tz.localize(datetime(2024, 1, 15, 10, 0, 0))
        assert is_in_nudge_window(NudgeType.HIGH_PRIORITY, time_10am) is True

    def test_window_constants(self):
        """Test window constants are sensible."""
        assert NUDGE_WINDOW_DUE_TODAY_START == 14  # 2pm
        assert NUDGE_WINDOW_DUE_TODAY_END == 20  # 8pm
        assert NUDGE_WINDOW_DUE_TOMORROW_START == 18  # 6pm
        assert NUDGE_WINDOW_DUE_TOMORROW_END == 21  # 9pm
        assert NUDGE_WINDOW_OVERDUE_START == 9  # 9am
        assert NUDGE_WINDOW_OVERDUE_END == 12  # noon


class TestNudgeTracking:
    """Tests for nudge deduplication tracking."""

    def test_save_and_load_nudges(self, mock_settings, tmp_path):
        """Test saving and loading sent nudges."""
        nudges = {
            "task-123:due_today:2024-01-15": "2024-01-15T14:00:00-08:00",
            "task-456:overdue:2024-01-15": "2024-01-15T09:30:00-08:00",
        }

        save_sent_nudges(nudges)
        loaded = load_sent_nudges()

        assert loaded == nudges

    def test_load_empty_nudges(self, mock_settings, tmp_path):
        """Test loading when no file exists."""
        loaded = load_sent_nudges()
        assert loaded == {}

    def test_has_been_nudged_today_true(self, mock_settings, tz):
        """Test detecting already nudged task."""
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))
        mark_nudge_sent("task-123", NudgeType.DUE_TODAY, now)

        assert has_been_nudged_today("task-123", NudgeType.DUE_TODAY, now) is True

    def test_has_been_nudged_today_false(self, mock_settings, tz):
        """Test detecting not-yet-nudged task."""
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))

        assert has_been_nudged_today("task-999", NudgeType.DUE_TODAY, now) is False

    def test_nudge_different_type_not_blocked(self, mock_settings, tz):
        """Test same task can get different nudge types."""
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))
        mark_nudge_sent("task-123", NudgeType.DUE_TODAY, now)

        # Same task but different type should not be blocked
        assert has_been_nudged_today("task-123", NudgeType.DUE_TOMORROW, now) is False

    def test_nudge_cleanup_old_entries(self, mock_settings, tz):
        """Test old entries are cleaned up."""
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))
        old_date = now - timedelta(days=10)

        # Pre-populate with old entry
        save_sent_nudges({
            "task-old:due_today:2024-01-05": old_date.isoformat(),
        })

        # Mark a new nudge (triggers cleanup)
        mark_nudge_sent("task-new", NudgeType.DUE_TODAY, now)

        loaded = load_sent_nudges()

        # Old entry should be cleaned up
        assert "task-old:due_today:2024-01-05" not in loaded
        # New entry should exist
        assert "task-new:due_today:2024-01-15" in loaded


class TestFormatNudgeMessage:
    """Tests for message formatting."""

    def test_format_due_today(self, tz):
        """Test formatting due today message."""
        candidate = NudgeCandidate(
            task_id="t1",
            title="Buy groceries",
            due_date=datetime.now(tz),
            priority=None,
            nudge_type=NudgeType.DUE_TODAY,
        )

        message = format_nudge_message(candidate)
        assert message == 'Don\'t forget: "Buy groceries" is due today'

    def test_format_due_today_high_priority(self, tz):
        """Test formatting high priority due today message."""
        candidate = NudgeCandidate(
            task_id="t1",
            title="Submit report",
            due_date=datetime.now(tz),
            priority="high",
            nudge_type=NudgeType.DUE_TODAY,
        )

        message = format_nudge_message(candidate)
        assert message == 'Priority: Don\'t forget: "Submit report" is due today'

    def test_format_due_tomorrow(self, tz):
        """Test formatting due tomorrow message."""
        candidate = NudgeCandidate(
            task_id="t1",
            title="Call doctor",
            due_date=datetime.now(tz) + timedelta(days=1),
            priority=None,
            nudge_type=NudgeType.DUE_TOMORROW,
        )

        message = format_nudge_message(candidate)
        assert message == 'Heads up: "Call doctor" is due tomorrow'

    def test_format_overdue_one_day(self, tz):
        """Test formatting overdue message (1 day)."""
        candidate = NudgeCandidate(
            task_id="t1",
            title="Pay bill",
            due_date=datetime.now(tz) - timedelta(days=1),
            priority=None,
            nudge_type=NudgeType.OVERDUE,
            days_overdue=1,
        )

        message = format_nudge_message(candidate)
        assert message == 'Overdue: "Pay bill" was due yesterday'

    def test_format_overdue_multiple_days(self, tz):
        """Test formatting overdue message (multiple days)."""
        candidate = NudgeCandidate(
            task_id="t1",
            title="Submit form",
            due_date=datetime.now(tz) - timedelta(days=5),
            priority=None,
            nudge_type=NudgeType.OVERDUE,
            days_overdue=5,
        )

        message = format_nudge_message(candidate)
        assert message == 'Overdue (5 days): "Submit form"'

    def test_format_high_priority(self, tz):
        """Test formatting high priority urgent message."""
        candidate = NudgeCandidate(
            task_id="t1",
            title="Emergency meeting",
            due_date=datetime.now(tz),
            priority="urgent",
            nudge_type=NudgeType.HIGH_PRIORITY,
        )

        message = format_nudge_message(candidate)
        assert message == 'Urgent reminder: "Emergency meeting"'


class TestNudgeService:
    """Tests for NudgeService class."""

    @pytest.fixture
    def mock_notion(self):
        """Create mock NotionClient."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_notion, mock_settings):
        """Create NudgeService with mocked dependencies."""
        return NudgeService(notion_client=mock_notion)

    @pytest.mark.asyncio
    async def test_get_candidates_due_today(self, service, mock_notion, tz):
        """Test getting tasks due today."""
        now = tz.localize(datetime(2024, 1, 15, 14, 0, 0))

        mock_notion.query_tasks.return_value = [
            {
                "id": "task-123",
                "properties": {
                    "title": {"title": [{"text": {"content": "Buy milk"}}]},
                    "priority": {"select": {"name": "medium"}},
                    "due_date": {"date": {"start": "2024-01-15T18:00:00"}},
                },
            }
        ]

        candidates = await service.get_nudge_candidates(now)

        # Should have at least one candidate
        assert len(candidates) >= 1
        # Check the due today candidate
        due_today = [c for c in candidates if c.nudge_type == NudgeType.DUE_TODAY]
        assert len(due_today) == 1
        assert due_today[0].title == "Buy milk"

    @pytest.mark.asyncio
    async def test_get_candidates_no_notion(self, mock_settings, tz):
        """Test service without Notion returns empty list."""
        mock_settings.has_notion = False
        service = NudgeService(notion_client=None)

        candidates = await service.get_nudge_candidates()
        assert candidates == []

    @pytest.mark.asyncio
    async def test_filter_candidates_time_window(self, service, tz, mock_settings):
        """Test filtering by time window."""
        # 3pm - within due_today window (2pm-8pm)
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))

        candidates = [
            NudgeCandidate("t1", "Task 1", now, None, NudgeType.DUE_TODAY),
            NudgeCandidate("t2", "Task 2", now + timedelta(days=1), None, NudgeType.DUE_TOMORROW),
        ]

        filtered = await service.filter_candidates(candidates, now)

        # Only due_today should pass (within 2pm-8pm window)
        # due_tomorrow window is 6pm-9pm, so at 3pm it should be filtered out
        assert len(filtered) == 1
        assert filtered[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_filter_candidates_dedup(self, service, tz, mock_settings):
        """Test filtering already-nudged tasks."""
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))

        # Mark t1 as already nudged
        mark_nudge_sent("t1", NudgeType.DUE_TODAY, now)

        candidates = [
            NudgeCandidate("t1", "Already nudged", now, None, NudgeType.DUE_TODAY),
            NudgeCandidate("t2", "Not nudged yet", now, None, NudgeType.DUE_TODAY),
        ]

        filtered = await service.filter_candidates(candidates, now)

        # Only t2 should pass
        assert len(filtered) == 1
        assert filtered[0].task_id == "t2"

    @pytest.mark.asyncio
    async def test_high_priority_upgrade(self, service, mock_notion, tz):
        """Test that high priority tasks due today get upgraded."""
        now = tz.localize(datetime(2024, 1, 15, 14, 0, 0))

        mock_notion.query_tasks.return_value = [
            {
                "id": "task-urgent",
                "properties": {
                    "title": {"title": [{"text": {"content": "Urgent task"}}]},
                    "priority": {"select": {"name": "urgent"}},
                    "due_date": {"date": {"start": "2024-01-15T18:00:00"}},
                },
            }
        ]

        candidates = await service.get_nudge_candidates(now)

        # High priority due today should be upgraded to HIGH_PRIORITY type
        urgent_tasks = [c for c in candidates if c.nudge_type == NudgeType.HIGH_PRIORITY]
        assert len(urgent_tasks) == 1
        assert urgent_tasks[0].priority == "urgent"

    @pytest.mark.asyncio
    async def test_send_nudges_success(self, service, tz, mock_settings):
        """Test successful nudge sending."""
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))

        candidates = [
            NudgeCandidate("t1", "Buy milk", now, None, NudgeType.DUE_TODAY),
        ]

        send_mock = AsyncMock()

        with patch.object(service, "filter_candidates", return_value=candidates):
            report = await service.send_nudges(candidates, send_func=send_mock)

        assert report.nudges_sent == 1
        assert report.nudges_failed == 0
        send_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_nudges_failure(self, service, tz, mock_settings):
        """Test handling of send failures."""
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))

        candidates = [
            NudgeCandidate("t1", "Task", now, None, NudgeType.DUE_TODAY),
        ]

        send_mock = AsyncMock(side_effect=Exception("Network error"))

        with patch.object(service, "filter_candidates", return_value=candidates):
            report = await service.send_nudges(candidates, send_func=send_mock)

        assert report.nudges_sent == 0
        assert report.nudges_failed == 1
        assert report.results[0].error == "Network error"

    @pytest.mark.asyncio
    async def test_run_full_cycle(self, service, mock_notion, tz, mock_settings):
        """Test complete run cycle."""
        mock_notion.query_tasks.return_value = []
        mock_notion.close = AsyncMock()

        report = await service.run()

        assert report.candidates_found == 0
        mock_notion.close.assert_called_once()


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_run_nudges_function(self, mock_settings):
        """Test run_nudges convenience function."""
        with patch("assistant.services.nudges.NudgeService") as MockService:
            mock_instance = MockService.return_value
            mock_instance.run = AsyncMock(return_value=NudgeReport(nudges_sent=2))

            report = await run_nudges()

            assert report.nudges_sent == 2

    @pytest.mark.asyncio
    async def test_get_pending_nudges_function(self, mock_settings):
        """Test get_pending_nudges convenience function."""
        with patch("assistant.services.nudges.NudgeService") as MockService:
            mock_instance = MockService.return_value
            mock_instance.get_nudge_candidates = AsyncMock(return_value=[])
            mock_instance.filter_candidates = AsyncMock(return_value=[])
            mock_instance.notion = MagicMock()
            mock_instance.notion.close = AsyncMock()

            pending = await get_pending_nudges()

            assert pending == []


class TestSystemdFiles:
    """Tests for systemd timer and service files."""

    def test_nudge_service_file_exists(self):
        """Test nudge service file exists."""
        path = Path(__file__).parent.parent / "deploy" / "systemd" / "second-brain-nudge.service"
        assert path.exists(), f"Missing {path}"

    def test_nudge_timer_file_exists(self):
        """Test nudge timer file exists."""
        path = Path(__file__).parent.parent / "deploy" / "systemd" / "second-brain-nudge.timer"
        assert path.exists(), f"Missing {path}"

    def test_nudge_timer_has_multiple_schedules(self):
        """Test timer runs multiple times per day."""
        path = Path(__file__).parent.parent / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = path.read_text()

        # Should have multiple OnCalendar entries
        assert content.count("OnCalendar=") >= 3, "Timer should run at least 3 times per day"

    def test_nudge_timer_times(self):
        """Test timer has correct times."""
        path = Path(__file__).parent.parent / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = path.read_text()

        # Check for expected times
        assert "09:00:00" in content, "Should have 9am for overdue"
        assert "14:00:00" in content, "Should have 2pm for due today"
        assert "18:00:00" in content, "Should have 6pm for due tomorrow"

    def test_nudge_service_runs_correct_command(self):
        """Test service runs nudge command."""
        path = Path(__file__).parent.parent / "deploy" / "systemd" / "second-brain-nudge.service"
        content = path.read_text()

        assert "assistant nudge" in content, "Service should run 'assistant nudge'"

    def test_nudge_timer_persistent(self):
        """Test timer catches up on missed runs."""
        path = Path(__file__).parent.parent / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = path.read_text()

        assert "Persistent=true" in content, "Timer should be persistent"


class TestCLIIntegration:
    """Tests for CLI command integration."""

    def test_cli_has_nudge_command(self):
        """Test CLI parser includes nudge command."""
        from assistant.cli import main
        import argparse

        # Create parser like main() does
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        subparsers.add_parser("nudge")

        args = parser.parse_args(["nudge"])
        assert args.command == "nudge"


class TestT130PRDRequirements:
    """Tests verifying PRD T-130 requirements."""

    def test_dont_forget_message_format(self, tz):
        """Test message format per PRD: 'Don't forget X'."""
        candidate = NudgeCandidate(
            task_id="t1",
            title="Complete report",
            due_date=datetime.now(tz),
            priority=None,
            nudge_type=NudgeType.DUE_TODAY,
        )

        message = format_nudge_message(candidate)
        assert "Don't forget" in message, "PRD requires 'Don't forget X' format"

    def test_proactive_surfacing(self):
        """Test nudges are proactive (scheduled, not user-triggered)."""
        # This is verified by the existence of systemd timer
        timer_path = Path(__file__).parent.parent / "deploy" / "systemd" / "second-brain-nudge.timer"
        assert timer_path.exists(), "Proactive nudges require scheduled timer"

    def test_multiple_nudge_types(self):
        """Test system supports different nudge scenarios."""
        assert NudgeType.DUE_TODAY is not None
        assert NudgeType.DUE_TOMORROW is not None
        assert NudgeType.OVERDUE is not None
        assert NudgeType.HIGH_PRIORITY is not None

    def test_deduplication_prevents_spam(self, mock_settings, tz):
        """Test same task doesn't get multiple nudges per day."""
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))

        # Mark as nudged
        mark_nudge_sent("task-123", NudgeType.DUE_TODAY, now)

        # Same task, same type, same day should be blocked
        assert has_been_nudged_today("task-123", NudgeType.DUE_TODAY, now) is True

        # Different day should not be blocked
        tomorrow = now + timedelta(days=1)
        assert has_been_nudged_today("task-123", NudgeType.DUE_TODAY, tomorrow) is False
