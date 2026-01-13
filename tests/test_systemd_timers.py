"""Tests for T-207: Configure systemd timers on server.

This module tests the systemd timer configuration for scheduled tasks:
- Morning briefing at 7am (AT-206)
- Proactive nudges at 9am, 2pm, 6pm (AT-206)

Acceptance Test AT-206:
- Given: Deployed to droplet with systemd timers
- When: Timer triggers (briefing at 7am, nudge at 2pm)
- Then: Command executes successfully
- Pass condition: Log shows successful execution
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Project root for file access
PROJECT_ROOT = Path(__file__).parent.parent


class TestInstallScriptExists:
    """Test that the install script exists and is properly configured."""

    def test_install_script_exists(self) -> None:
        """Install script should exist."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        assert install_path.exists()

    def test_install_script_is_executable(self) -> None:
        """Install script should be executable."""
        import os

        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        mode = os.stat(install_path).st_mode
        assert mode & 0o111  # Has execute bit

    def test_install_script_has_shebang(self) -> None:
        """Install script should have bash shebang."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert content.startswith("#!/bin/bash")

    def test_install_script_uses_strict_mode(self) -> None:
        """Install script should use strict mode (set -euo pipefail)."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "set -euo pipefail" in content


class TestBriefingTimerFiles:
    """Test the briefing timer configuration files."""

    def test_briefing_service_exists(self) -> None:
        """Briefing service file should exist."""
        service_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.service"
        assert service_path.exists()

    def test_briefing_timer_exists(self) -> None:
        """Briefing timer file should exist."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        assert timer_path.exists()

    def test_briefing_timer_runs_at_7am(self) -> None:
        """Briefing timer should be configured for 7:00 AM."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_path.read_text()
        assert "OnCalendar=*-*-* 07:00:00" in content

    def test_briefing_timer_is_persistent(self) -> None:
        """Briefing timer should have Persistent=true for missed runs."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_path.read_text()
        assert "Persistent=true" in content

    def test_briefing_timer_has_randomized_delay(self) -> None:
        """Briefing timer should have randomized delay to avoid thundering herd."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_path.read_text()
        assert "RandomizedDelaySec=300" in content

    def test_briefing_timer_points_to_service(self) -> None:
        """Briefing timer should trigger the correct service."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_path.read_text()
        assert "Unit=second-brain-briefing.service" in content


class TestNudgeTimerFiles:
    """Test the nudge timer configuration files."""

    def test_nudge_service_exists(self) -> None:
        """Nudge service file should exist."""
        service_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.service"
        assert service_path.exists()

    def test_nudge_timer_exists(self) -> None:
        """Nudge timer file should exist."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"
        assert timer_path.exists()

    def test_nudge_timer_runs_at_9am(self) -> None:
        """Nudge timer should run at 9:00 AM for overdue tasks."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = timer_path.read_text()
        assert "OnCalendar=*-*-* 09:00:00" in content

    def test_nudge_timer_runs_at_2pm(self) -> None:
        """Nudge timer should run at 2:00 PM for due-today tasks."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = timer_path.read_text()
        assert "OnCalendar=*-*-* 14:00:00" in content

    def test_nudge_timer_runs_at_6pm(self) -> None:
        """Nudge timer should run at 6:00 PM for due-tomorrow tasks."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = timer_path.read_text()
        assert "OnCalendar=*-*-* 18:00:00" in content

    def test_nudge_timer_is_persistent(self) -> None:
        """Nudge timer should have Persistent=true for missed runs."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = timer_path.read_text()
        assert "Persistent=true" in content

    def test_nudge_timer_points_to_service(self) -> None:
        """Nudge timer should trigger the correct service."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = timer_path.read_text()
        assert "Unit=second-brain-nudge.service" in content


class TestInstallScriptCopiesAllFiles:
    """Test that install.sh copies all required files."""

    def test_copies_main_service(self) -> None:
        """Install script should copy the main service."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert 'cp "${SCRIPT_DIR}/second-brain.service"' in content

    def test_copies_briefing_service(self) -> None:
        """Install script should copy the briefing service."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert 'cp "${SCRIPT_DIR}/second-brain-briefing.service"' in content

    def test_copies_briefing_timer(self) -> None:
        """Install script should copy the briefing timer."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert 'cp "${SCRIPT_DIR}/second-brain-briefing.timer"' in content

    def test_copies_nudge_service(self) -> None:
        """Install script should copy the nudge service."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert 'cp "${SCRIPT_DIR}/second-brain-nudge.service"' in content

    def test_copies_nudge_timer(self) -> None:
        """Install script should copy the nudge timer."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert 'cp "${SCRIPT_DIR}/second-brain-nudge.timer"' in content


class TestInstallScriptEnablesTimers:
    """Test that install.sh enables both timers."""

    def test_enables_main_service(self) -> None:
        """Install script should enable the main service."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "systemctl enable second-brain.service" in content

    def test_enables_briefing_timer(self) -> None:
        """Install script should enable the briefing timer."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "systemctl enable second-brain-briefing.timer" in content

    def test_enables_nudge_timer(self) -> None:
        """Install script should enable the nudge timer."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "systemctl enable second-brain-nudge.timer" in content

    def test_reloads_daemon_before_enable(self) -> None:
        """Install script should reload daemon before enabling."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        # Reload should come before enable
        reload_pos = content.find("systemctl daemon-reload")
        enable_pos = content.find("systemctl enable")
        assert reload_pos < enable_pos


class TestInstallScriptPermissions:
    """Test that install.sh sets proper file permissions."""

    def test_sets_service_permissions(self) -> None:
        """Install script should set 644 on service files."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "chmod 644 /etc/systemd/system/second-brain.service" in content

    def test_sets_briefing_timer_permissions(self) -> None:
        """Install script should set 644 on briefing timer."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "chmod 644 /etc/systemd/system/second-brain-briefing.timer" in content

    def test_sets_nudge_timer_permissions(self) -> None:
        """Install script should set 644 on nudge timer."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "chmod 644 /etc/systemd/system/second-brain-nudge.timer" in content


class TestInstallScriptDocumentation:
    """Test that install.sh has proper documentation."""

    def test_has_usage_instructions(self) -> None:
        """Install script should have usage documentation."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "Usage:" in content

    def test_documents_next_steps(self) -> None:
        """Install script should document next steps."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "Next steps:" in content

    def test_shows_useful_commands(self) -> None:
        """Install script should show useful systemctl commands."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()
        assert "systemctl list-timers" in content


class TestServiceFiles:
    """Test the service file configurations."""

    def test_briefing_service_runs_docker_exec(self) -> None:
        """Briefing service should use docker exec."""
        service_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.service"
        content = service_path.read_text()
        assert "docker exec" in content or "docker compose" in content

    def test_briefing_service_runs_briefing_command(self) -> None:
        """Briefing service should run the briefing command."""
        service_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.service"
        content = service_path.read_text()
        assert "briefing" in content

    def test_nudge_service_runs_docker_exec(self) -> None:
        """Nudge service should use docker exec."""
        service_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.service"
        content = service_path.read_text()
        assert "docker exec" in content or "docker compose" in content

    def test_nudge_service_runs_nudge_command(self) -> None:
        """Nudge service should run the nudge command."""
        service_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.service"
        content = service_path.read_text()
        assert "nudge" in content


class TestAT206ScheduledTimersWork:
    """AT-206: Scheduled timers work.

    Given: Deployed to droplet with systemd timers
    When: Timer triggers (briefing at 7am, nudge at 2pm)
    Then: Command executes successfully
    Pass condition: Log shows successful execution
    """

    def test_briefing_timer_configured_for_7am(self) -> None:
        """Briefing timer should be set to 7:00 AM."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_path.read_text()
        # AT-206: Timer triggers at 7am
        assert "07:00:00" in content

    def test_nudge_timer_configured_for_2pm(self) -> None:
        """Nudge timer should include 2:00 PM trigger."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = timer_path.read_text()
        # AT-206: Timer triggers at 2pm
        assert "14:00:00" in content

    def test_timers_are_persistent(self) -> None:
        """Both timers should be persistent for reliability."""
        briefing_timer = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        nudge_timer = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"

        assert "Persistent=true" in briefing_timer.read_text()
        assert "Persistent=true" in nudge_timer.read_text()

    def test_install_script_enables_both_timers(self) -> None:
        """Install script should enable both briefing and nudge timers."""
        install_path = PROJECT_ROOT / "deploy" / "systemd" / "install.sh"
        content = install_path.read_text()

        # AT-206: Both timers should be enabled
        assert "systemctl enable second-brain-briefing.timer" in content
        assert "systemctl enable second-brain-nudge.timer" in content

    def test_services_execute_correct_commands(self) -> None:
        """Services should execute the correct CLI commands."""
        briefing_service = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.service"
        nudge_service = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.service"

        # AT-206: Commands execute successfully
        assert "briefing" in briefing_service.read_text()
        assert "nudge" in nudge_service.read_text()


class TestT207PRDCompliance:
    """Test PRD compliance for T-207."""

    def test_prd_briefing_at_7am(self) -> None:
        """PRD 5.2 requires morning briefing at 7am."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_path.read_text()
        # PRD 5.2: "Morning Briefing (7am)"
        assert "07:00:00" in content

    def test_prd_nudge_multiple_times(self) -> None:
        """PRD 2.2 'Tap on Shoulder' requires multiple nudge times."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = timer_path.read_text()
        # Nudges at different times of day
        assert content.count("OnCalendar=") >= 3

    def test_prd_docker_container_name(self) -> None:
        """PRD 1.2 requires container named 'second-brain' for docker exec."""
        briefing_service = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.service"
        content = briefing_service.read_text()
        # PRD 1.2: "container_name second-brain"
        assert "second-brain" in content

    def test_prd_systemd_timer_reliability(self) -> None:
        """PRD requires systemd timer for reliable 7am delivery."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_path.read_text()
        # PRD: "systemd timer guarantees 7am briefing even if main process is down"
        # Persistent ensures missed runs are caught up
        assert "Persistent=true" in content


class TestSetupServerTimerIntegration:
    """Test that setup-server.sh integrates with timers properly."""

    def test_setup_creates_timer_installer(self) -> None:
        """Setup script should create install-timers.sh helper."""
        setup_path = PROJECT_ROOT / "deploy" / "scripts" / "setup-server.sh"
        content = setup_path.read_text()
        assert "install-timers.sh" in content

    def test_setup_enables_briefing_timer_in_helper(self) -> None:
        """Setup script's helper should enable briefing timer."""
        setup_path = PROJECT_ROOT / "deploy" / "scripts" / "setup-server.sh"
        content = setup_path.read_text()
        # The heredoc contains the timer enable commands
        assert "second-brain-briefing.timer" in content

    def test_setup_enables_nudge_timer_in_helper(self) -> None:
        """Setup script's helper should enable nudge timer."""
        setup_path = PROJECT_ROOT / "deploy" / "scripts" / "setup-server.sh"
        content = setup_path.read_text()
        # The heredoc contains the timer enable commands
        assert "second-brain-nudge.timer" in content


class TestTimerUnits:
    """Test systemd timer unit structure."""

    @pytest.mark.parametrize(
        "timer_name",
        ["second-brain-briefing.timer", "second-brain-nudge.timer"],
    )
    def test_timer_has_unit_section(self, timer_name: str) -> None:
        """Timer should have [Unit] section."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / timer_name
        content = timer_path.read_text()
        assert "[Unit]" in content

    @pytest.mark.parametrize(
        "timer_name",
        ["second-brain-briefing.timer", "second-brain-nudge.timer"],
    )
    def test_timer_has_timer_section(self, timer_name: str) -> None:
        """Timer should have [Timer] section."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / timer_name
        content = timer_path.read_text()
        assert "[Timer]" in content

    @pytest.mark.parametrize(
        "timer_name",
        ["second-brain-briefing.timer", "second-brain-nudge.timer"],
    )
    def test_timer_has_install_section(self, timer_name: str) -> None:
        """Timer should have [Install] section."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / timer_name
        content = timer_path.read_text()
        assert "[Install]" in content

    @pytest.mark.parametrize(
        "timer_name",
        ["second-brain-briefing.timer", "second-brain-nudge.timer"],
    )
    def test_timer_wanted_by_timers_target(self, timer_name: str) -> None:
        """Timer should be WantedBy=timers.target."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / timer_name
        content = timer_path.read_text()
        assert "WantedBy=timers.target" in content


class TestTimerAccuracy:
    """Test timer accuracy settings."""

    def test_briefing_timer_has_accuracy(self) -> None:
        """Briefing timer should have AccuracySec setting."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-briefing.timer"
        content = timer_path.read_text()
        assert "AccuracySec=" in content

    def test_nudge_timer_has_accuracy(self) -> None:
        """Nudge timer should have AccuracySec setting."""
        timer_path = PROJECT_ROOT / "deploy" / "systemd" / "second-brain-nudge.timer"
        content = timer_path.read_text()
        assert "AccuracySec=" in content
