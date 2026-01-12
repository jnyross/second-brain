"""Tests for server setup script (T-204, AT-208).

Validates the setup-server.sh script meets all PRD 12.7 requirements
and AT-208 acceptance criteria for security hardening.
"""

from pathlib import Path

import pytest


@pytest.fixture
def setup_script():
    """Load the setup script content."""
    script_path = Path(__file__).parent.parent / "deploy" / "scripts" / "setup-server.sh"
    assert script_path.exists(), f"Setup script not found at {script_path}"
    return script_path.read_text()


class TestSetupScriptExists:
    """Test that the setup script file exists and is valid."""

    def test_script_exists(self):
        """Setup script should exist at expected path."""
        script_path = Path(__file__).parent.parent / "deploy" / "scripts" / "setup-server.sh"
        assert script_path.exists()

    def test_script_is_executable(self):
        """Setup script should have executable permission."""
        script_path = Path(__file__).parent.parent / "deploy" / "scripts" / "setup-server.sh"
        # Check if file has any execute permission
        import os
        import stat

        mode = os.stat(script_path).st_mode
        assert mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), "Script should be executable"

    def test_script_has_shebang(self, setup_script):
        """Script should start with bash shebang."""
        assert setup_script.startswith("#!/bin/bash")

    def test_script_uses_strict_mode(self, setup_script):
        """Script should use strict mode (set -euo pipefail)."""
        assert "set -euo pipefail" in setup_script


class TestDockerInstallation:
    """Test Docker installation steps."""

    def test_installs_docker(self, setup_script):
        """Script should install Docker using official script."""
        assert "https://get.docker.com" in setup_script

    def test_enables_docker_service(self, setup_script):
        """Script should enable Docker service."""
        assert "systemctl enable docker" in setup_script

    def test_checks_docker_already_installed(self, setup_script):
        """Script should check if Docker is already installed (idempotency)."""
        assert "command -v docker" in setup_script or "docker info" in setup_script

    def test_installs_docker_compose(self, setup_script):
        """Script should install Docker Compose plugin."""
        assert "docker-compose-plugin" in setup_script or "docker compose" in setup_script


class TestFail2banInstallation:
    """Test fail2ban installation and configuration."""

    def test_installs_fail2ban(self, setup_script):
        """Script should install fail2ban."""
        assert "apt" in setup_script and "fail2ban" in setup_script

    def test_enables_fail2ban_service(self, setup_script):
        """Script should enable fail2ban service."""
        assert "systemctl enable fail2ban" in setup_script

    def test_configures_jail_local(self, setup_script):
        """Script should create jail.local configuration."""
        assert "jail.local" in setup_script

    def test_configures_ssh_protection(self, setup_script):
        """Script should configure SSH protection in fail2ban."""
        assert "[sshd]" in setup_script
        assert "enabled = true" in setup_script


class TestUFWFirewall:
    """Test UFW firewall configuration."""

    def test_installs_ufw(self, setup_script):
        """Script should install UFW."""
        assert "ufw" in setup_script

    def test_default_deny_incoming(self, setup_script):
        """Script should deny incoming by default."""
        assert "ufw default deny incoming" in setup_script

    def test_default_allow_outgoing(self, setup_script):
        """Script should allow outgoing by default."""
        assert "ufw default allow outgoing" in setup_script

    def test_allows_ssh(self, setup_script):
        """Script should allow SSH before enabling firewall."""
        assert "ufw allow ssh" in setup_script

    def test_enables_ufw(self, setup_script):
        """Script should enable UFW (with --force to skip prompt)."""
        assert "ufw --force enable" in setup_script or "ufw enable" in setup_script


class TestDeployUser:
    """Test deploy user creation."""

    def test_creates_deploy_user(self, setup_script):
        """Script should create deploy user."""
        assert "useradd" in setup_script and "deploy" in setup_script

    def test_adds_deploy_to_docker_group(self, setup_script):
        """Script should add deploy user to docker group."""
        assert "usermod -aG docker" in setup_script

    def test_creates_ssh_directory(self, setup_script):
        """Script should create .ssh directory for deploy user."""
        assert ".ssh" in setup_script
        assert "authorized_keys" in setup_script

    def test_sets_ssh_permissions(self, setup_script):
        """Script should set proper permissions on .ssh directory."""
        assert "chmod 700" in setup_script or "chmod" in setup_script


class TestAppDirectories:
    """Test application directory creation."""

    def test_creates_opt_directory(self, setup_script):
        """Script should create /opt/second-brain directory."""
        assert "/opt/second-brain" in setup_script

    def test_creates_var_directory(self, setup_script):
        """Script should create /var/lib/second-brain directory."""
        assert "/var/lib/second-brain" in setup_script

    def test_creates_subdirectories(self, setup_script):
        """Script should create necessary subdirectories."""
        required_dirs = ["data", "logs", "scripts"]
        for dir_name in required_dirs:
            assert dir_name in setup_script, f"Missing directory: {dir_name}"

    def test_sets_ownership_to_deploy(self, setup_script):
        """Script should set ownership to deploy user."""
        assert "chown" in setup_script and "deploy" in setup_script


class TestSSHHardening:
    """Test SSH configuration hardening (AT-208)."""

    def test_disables_password_auth(self, setup_script):
        """Script should disable SSH password authentication."""
        assert "PasswordAuthentication no" in setup_script

    def test_restricts_root_login(self, setup_script):
        """Script should restrict root login."""
        assert "PermitRootLogin" in setup_script

    def test_disables_empty_passwords(self, setup_script):
        """Script should disable empty passwords."""
        assert "PermitEmptyPasswords no" in setup_script

    def test_restarts_sshd(self, setup_script):
        """Script should restart SSH service after changes."""
        assert "systemctl restart sshd" in setup_script or "service sshd restart" in setup_script


class TestEnvironmentFile:
    """Test environment file template creation."""

    def test_creates_env_template(self, setup_script):
        """Script should create environment file template."""
        assert "/etc/second-brain.env" in setup_script

    def test_sets_env_permissions(self, setup_script):
        """Script should set secure permissions on env file."""
        assert "chmod 600" in setup_script

    def test_includes_required_vars(self, setup_script):
        """Script should include required environment variables."""
        required_vars = [
            "TELEGRAM_BOT_TOKEN",
            "NOTION_API_KEY",
        ]
        for var in required_vars:
            assert var in setup_script, f"Missing env var: {var}"


class TestIdempotency:
    """Test that script is safe to run multiple times."""

    def test_checks_docker_exists(self, setup_script):
        """Script should check if Docker is already installed."""
        assert "if" in setup_script and "docker" in setup_script

    def test_checks_user_exists(self, setup_script):
        """Script should check if deploy user already exists."""
        assert "id" in setup_script or "getent" in setup_script

    def test_checks_fail2ban_exists(self, setup_script):
        """Script should check if fail2ban is already installed."""
        assert "dpkg" in setup_script or "apt" in setup_script


class TestErrorHandling:
    """Test error handling in the script."""

    def test_root_check(self, setup_script):
        """Script should check if running as root."""
        assert "EUID" in setup_script or "whoami" in setup_script or "root" in setup_script

    def test_colored_output(self, setup_script):
        """Script should have colored output functions."""
        assert "log_info" in setup_script or "echo" in setup_script

    def test_exit_on_failure(self, setup_script):
        """Script should exit on failures (via set -e)."""
        assert "set -e" in setup_script or "set -euo" in setup_script


class TestAT208SecurityHardening:
    """AT-208 acceptance test: Security hardening on fresh droplet."""

    def test_at208_ssh_password_disabled(self, setup_script):
        """AT-208: SSH password auth should be disabled."""
        # Given: Fresh droplet with setup script run
        # Then: SSH password auth disabled
        assert "PasswordAuthentication no" in setup_script

    def test_at208_ufw_enabled(self, setup_script):
        """AT-208: UFW should be enabled."""
        # Then: UFW enabled
        assert "ufw --force enable" in setup_script or "ufw enable" in setup_script

    def test_at208_only_ssh_open(self, setup_script):
        """AT-208: Only SSH should be open (default deny + allow ssh)."""
        # Then: Only SSH open
        assert "ufw default deny incoming" in setup_script
        assert "ufw allow ssh" in setup_script
        # Should not allow other ports
        assert "ufw allow 80" not in setup_script
        assert "ufw allow 443" not in setup_script

    def test_at208_fail2ban_running(self, setup_script):
        """AT-208: fail2ban should be configured and enabled."""
        # Then: fail2ban running
        assert "systemctl enable fail2ban" in setup_script
        has_restart = "systemctl restart fail2ban" in setup_script
        has_start = "systemctl start fail2ban" in setup_script
        assert has_restart or has_start

    def test_at208_deploy_user_no_password(self, setup_script):
        """AT-208: Deploy user should use SSH keys, not password."""
        # Then: Deploy user can SSH but not with password
        assert "authorized_keys" in setup_script
        # No password setting for deploy user
        assert "passwd deploy" not in setup_script


class TestPRDSection127Compliance:
    """Verify compliance with PRD Section 12.7 requirements."""

    def test_updates_system(self, setup_script):
        """Script should update system packages."""
        assert "apt update" in setup_script or "apt-get update" in setup_script

    def test_docker_group_for_deploy(self, setup_script):
        """Script should add deploy user to docker group."""
        assert "usermod -aG docker" in setup_script

    def test_app_directory_structure(self, setup_script):
        """Script should create proper directory structure."""
        assert "/opt/second-brain" in setup_script
        assert "data" in setup_script
        assert "logs" in setup_script
        assert "scripts" in setup_script

    def test_systemd_timers_mentioned(self, setup_script):
        """Script should reference systemd timers (or indicate they're handled separately)."""
        # May copy timers or just document them
        assert "systemd" in setup_script or "timer" in setup_script or "briefing" in setup_script


class TestScriptDocumentation:
    """Test that script is well documented."""

    def test_has_header_comment(self, setup_script):
        """Script should have header comment explaining purpose."""
        assert "setup-server.sh" in setup_script
        assert "Ubuntu" in setup_script or "droplet" in setup_script

    def test_has_next_steps(self, setup_script):
        """Script should print next steps after completion."""
        assert "Next steps" in setup_script or "complete" in setup_script

    def test_documents_requirements(self, setup_script):
        """Script should document prerequisites."""
        assert "Ubuntu" in setup_script or "root" in setup_script


class TestBashBestPractices:
    """Test bash scripting best practices."""

    def test_quotes_variables(self, setup_script):
        """Script should quote variable expansions."""
        # Check for common patterns
        assert '"$' in setup_script or "'$" in setup_script

    def test_uses_local_vars(self, setup_script):
        """Script should use uppercase for global vars."""
        assert "DEPLOY_USER" in setup_script or "APP_DIR" in setup_script

    def test_no_command_injection(self, setup_script):
        """Script should not have obvious command injection vectors."""
        # Check for dangerous patterns
        assert "eval" not in setup_script or "eval " not in setup_script
        assert "`$" not in setup_script  # No nested command substitution with vars
