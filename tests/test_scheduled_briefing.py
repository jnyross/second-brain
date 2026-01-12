"""Tests for scheduled briefing sender (T-081).

Tests:
- systemd unit file syntax validation
- CLI briefing command works
- Timer configuration is correct
- AT-106: Morning briefing delivery
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


class TestSystemdFiles:
    """Tests for systemd unit file validity."""

    @pytest.fixture
    def systemd_dir(self) -> Path:
        """Get the systemd deployment directory."""
        return PROJECT_ROOT / "deploy" / "systemd"

    def test_systemd_directory_exists(self, systemd_dir: Path):
        """Systemd deployment directory exists."""
        assert systemd_dir.exists(), "deploy/systemd directory should exist"

    def test_timer_file_exists(self, systemd_dir: Path):
        """Timer unit file exists."""
        timer_file = systemd_dir / "second-brain-briefing.timer"
        assert timer_file.exists(), "second-brain-briefing.timer should exist"

    def test_briefing_service_file_exists(self, systemd_dir: Path):
        """Briefing service unit file exists."""
        service_file = systemd_dir / "second-brain-briefing.service"
        assert service_file.exists(), "second-brain-briefing.service should exist"

    def test_main_service_file_exists(self, systemd_dir: Path):
        """Main bot service unit file exists."""
        service_file = systemd_dir / "second-brain.service"
        assert service_file.exists(), "second-brain.service should exist"

    def test_install_script_exists(self, systemd_dir: Path):
        """Installation script exists."""
        install_script = systemd_dir / "install.sh"
        assert install_script.exists(), "install.sh should exist"

    def test_install_script_executable(self, systemd_dir: Path):
        """Installation script is executable."""
        install_script = systemd_dir / "install.sh"
        assert os.access(install_script, os.X_OK), "install.sh should be executable"

    def test_timer_has_oncalendar(self, systemd_dir: Path):
        """Timer has OnCalendar directive for 7am."""
        timer_file = systemd_dir / "second-brain-briefing.timer"
        content = timer_file.read_text()
        assert "OnCalendar" in content, "Timer should have OnCalendar directive"
        assert "07:00" in content, "Timer should be scheduled for 7:00 AM"

    def test_timer_is_persistent(self, systemd_dir: Path):
        """Timer has Persistent=true for missed runs."""
        timer_file = systemd_dir / "second-brain-briefing.timer"
        content = timer_file.read_text()
        assert "Persistent=true" in content, "Timer should be persistent"

    def test_timer_references_briefing_service(self, systemd_dir: Path):
        """Timer references the correct service unit."""
        timer_file = systemd_dir / "second-brain-briefing.timer"
        content = timer_file.read_text()
        assert "second-brain-briefing.service" in content, "Timer should reference briefing service"

    def test_briefing_service_is_oneshot(self, systemd_dir: Path):
        """Briefing service is Type=oneshot."""
        service_file = systemd_dir / "second-brain-briefing.service"
        content = service_file.read_text()
        assert "Type=oneshot" in content, "Briefing service should be oneshot"

    def test_briefing_service_runs_briefing_command(self, systemd_dir: Path):
        """Briefing service runs the briefing command."""
        service_file = systemd_dir / "second-brain-briefing.service"
        content = service_file.read_text()
        assert "assistant briefing" in content or "-m assistant briefing" in content, \
            "Service should run briefing command"

    def test_main_service_is_always_restart(self, systemd_dir: Path):
        """Main bot service has Restart=always."""
        service_file = systemd_dir / "second-brain.service"
        content = service_file.read_text()
        assert "Restart=always" in content, "Main service should restart always"

    def test_main_service_requires_network(self, systemd_dir: Path):
        """Main service requires network."""
        service_file = systemd_dir / "second-brain.service"
        content = service_file.read_text()
        assert "network" in content.lower(), "Main service should depend on network"


class TestInstallScript:
    """Tests for the installation script."""

    @pytest.fixture
    def install_script(self) -> Path:
        """Get the install script path."""
        return PROJECT_ROOT / "deploy" / "systemd" / "install.sh"

    def test_install_script_has_shebang(self, install_script: Path):
        """Install script has proper shebang."""
        content = install_script.read_text()
        assert content.startswith("#!/bin/bash"), "Script should start with bash shebang"

    def test_install_script_has_error_handling(self, install_script: Path):
        """Install script has set -e for error handling."""
        content = install_script.read_text()
        assert "set -e" in content or "set -euo pipefail" in content, \
            "Script should have error handling"

    def test_install_script_checks_root(self, install_script: Path):
        """Install script checks for root."""
        content = install_script.read_text()
        assert "EUID" in content or "root" in content, \
            "Script should check for root privileges"

    def test_install_script_creates_user(self, install_script: Path):
        """Install script creates second-brain user."""
        content = install_script.read_text()
        assert "second-brain" in content and "useradd" in content, \
            "Script should create second-brain user"

    def test_install_script_enables_services(self, install_script: Path):
        """Install script enables systemd services."""
        content = install_script.read_text()
        assert "systemctl enable" in content, "Script should enable services"

    def test_bash_syntax_valid(self, install_script: Path):
        """Install script has valid bash syntax."""
        # Check syntax without executing
        result = subprocess.run(
            ["bash", "-n", str(install_script)],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Bash syntax error: {result.stderr}"


class TestBriefingCLI:
    """Tests for the briefing CLI command."""

    @pytest.mark.asyncio
    async def test_send_briefing_generates_content(self):
        """send_briefing generates briefing content."""
        mock_generator = MagicMock()
        mock_generator.generate_morning_briefing = AsyncMock(
            return_value="Good morning! Here's your day..."
        )

        mock_bot = MagicMock()
        mock_bot.send_briefing = AsyncMock()
        mock_bot.stop = AsyncMock()

        with patch("assistant.cli.settings") as mock_settings, \
             patch("assistant.services.BriefingGenerator", return_value=mock_generator), \
             patch("assistant.telegram.SecondBrainBot", return_value=mock_bot):
            mock_settings.has_telegram = True
            mock_settings.has_notion = True
            mock_settings.user_telegram_chat_id = "123456789"
            mock_settings.user_timezone = "America/Los_Angeles"
            mock_settings.log_level = "INFO"

            from assistant.cli import send_briefing
            await send_briefing()

        mock_generator.generate_morning_briefing.assert_called_once()
        mock_bot.send_briefing.assert_called_once_with(
            "123456789",
            "Good morning! Here's your day..."
        )
        mock_bot.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_briefing_requires_telegram_config(self):
        """send_briefing exits if Telegram not configured."""
        with patch("assistant.cli.settings") as mock_settings:
            mock_settings.has_telegram = False

            from assistant.cli import send_briefing

            with pytest.raises(SystemExit) as exc_info:
                await send_briefing()

            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_send_briefing_requires_chat_id(self):
        """send_briefing exits if chat ID not configured."""
        with patch("assistant.cli.settings") as mock_settings:
            mock_settings.has_telegram = True
            mock_settings.user_telegram_chat_id = None

            from assistant.cli import send_briefing

            with pytest.raises(SystemExit) as exc_info:
                await send_briefing()

            assert exc_info.value.code == 1


class TestAT106:
    """AT-106: Morning Briefing Delivery.

    Given: System configured for 7am briefing
    When: Clock reaches 7:00am
    Then: Telegram message sent with today's calendar, due tasks, flagged items
    """

    @pytest.fixture
    def mock_notion_client(self):
        """Create a mock Notion client with test data."""
        mock = AsyncMock()
        mock.query_tasks = AsyncMock(return_value=[
            {
                "properties": {
                    "title": {"title": [{"text": {"content": "Call dentist"}}]},
                    "priority": {"select": {"name": "high"}},
                    "status": {"select": {"name": "todo"}},
                    "due_date": {"date": {"start": "2026-01-12"}}
                }
            }
        ])
        mock.query_inbox = AsyncMock(return_value=[
            {
                "properties": {
                    "raw_input": {"rich_text": [{"text": {"content": "Something unclear"}}]},
                    "interpretation": {"rich_text": [{"text": {"content": "Possible task?"}}]}
                }
            }
        ])
        mock.close = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_briefing_includes_due_tasks(self, mock_notion_client):
        """Briefing includes tasks due today."""
        from assistant.services.briefing import BriefingGenerator

        generator = BriefingGenerator(notion_client=mock_notion_client)
        briefing = await generator.generate_morning_briefing()

        assert "DUE TODAY" in briefing or "Call dentist" in briefing

    @pytest.mark.asyncio
    async def test_briefing_includes_flagged_items(self, mock_notion_client):
        """Briefing includes items needing clarification."""
        from assistant.services.briefing import BriefingGenerator

        generator = BriefingGenerator(notion_client=mock_notion_client)
        briefing = await generator.generate_morning_briefing()

        assert "NEEDS CLARIFICATION" in briefing or "Something unclear" in briefing

    @pytest.mark.asyncio
    async def test_briefing_includes_debrief_cta(self, mock_notion_client):
        """Briefing includes call-to-action for /debrief."""
        from assistant.services.briefing import BriefingGenerator

        generator = BriefingGenerator(notion_client=mock_notion_client)
        briefing = await generator.generate_morning_briefing()

        assert "/debrief" in briefing

    def test_timer_scheduled_for_7am(self):
        """Timer is scheduled for 7:00 AM."""
        timer_file = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_file.read_text()

        # Check for 7am scheduling
        assert "07:00:00" in content or "07:00" in content, \
            "Timer should be scheduled for 7:00 AM"

    def test_timer_will_catch_up_if_missed(self):
        """Timer is persistent so it catches up if system was off."""
        timer_file = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_file.read_text()

        assert "Persistent=true" in content, \
            "Timer should be persistent to catch up on missed runs"
