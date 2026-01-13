"""Tests for Telegram deployment notification script and CD workflow integration."""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def notify_script(project_root: Path) -> Path:
    """Path to notify-telegram.sh script."""
    return project_root / "deploy" / "scripts" / "notify-telegram.sh"


@pytest.fixture
def cd_workflow(project_root: Path) -> dict:
    """Load CD workflow YAML."""
    workflow_path = project_root / ".github" / "workflows" / "cd.yml"
    with open(workflow_path) as f:
        return yaml.safe_load(f)


# ============================================================================
# notify-telegram.sh Script Tests
# ============================================================================


class TestNotifyScriptExists:
    """Test that the notification script exists and is properly configured."""

    def test_script_exists(self, notify_script: Path):
        """Script file exists."""
        assert notify_script.exists(), f"Script not found at {notify_script}"

    def test_script_is_executable(self, notify_script: Path):
        """Script has executable permissions."""
        assert os.access(notify_script, os.X_OK), "Script is not executable"

    def test_script_has_shebang(self, notify_script: Path):
        """Script starts with proper shebang."""
        content = notify_script.read_text()
        assert content.startswith("#!/bin/bash"), "Missing bash shebang"

    def test_script_uses_set_e(self, notify_script: Path):
        """Script uses set -e for error handling."""
        content = notify_script.read_text()
        assert "set -e" in content, "Missing 'set -e' for error handling"


class TestNotifyScriptValidation:
    """Test script input validation."""

    def test_requires_telegram_bot_token(self, notify_script: Path):
        """Script fails without TELEGRAM_BOT_TOKEN."""
        result = subprocess.run(
            ["bash", str(notify_script), "success"],
            capture_output=True,
            text=True,
            env={**os.environ, "TELEGRAM_CHAT_ID": "123"},
        )
        assert result.returncode == 1
        assert "TELEGRAM_BOT_TOKEN" in result.stderr

    def test_requires_telegram_chat_id(self, notify_script: Path):
        """Script fails without TELEGRAM_CHAT_ID."""
        result = subprocess.run(
            ["bash", str(notify_script), "success"],
            capture_output=True,
            text=True,
            env={**os.environ, "TELEGRAM_BOT_TOKEN": "123:abc"},
        )
        assert result.returncode == 1
        assert "TELEGRAM_CHAT_ID" in result.stderr


class TestNotifyScriptStatusTypes:
    """Test different status type handling."""

    def test_supports_success_status(self, notify_script: Path):
        """Script accepts 'success' status."""
        content = notify_script.read_text()
        assert "success)" in content
        assert "Deployment Successful" in content

    def test_supports_failure_status(self, notify_script: Path):
        """Script accepts 'failure' status."""
        content = notify_script.read_text()
        assert "failure)" in content
        assert "Deployment Failed" in content

    def test_supports_rollback_status(self, notify_script: Path):
        """Script accepts 'rollback' status."""
        content = notify_script.read_text()
        assert "rollback)" in content
        assert "Deployment Rolled Back" in content

    def test_supports_started_status(self, notify_script: Path):
        """Script accepts 'started' status."""
        content = notify_script.read_text()
        assert "started)" in content
        assert "Deployment Started" in content

    def test_has_default_info_status(self, notify_script: Path):
        """Script has fallback for unknown status."""
        content = notify_script.read_text()
        assert "*)" in content  # Default case
        assert "Deployment Info" in content


class TestNotifyScriptMessageBuilding:
    """Test message content building."""

    def test_includes_repository_info(self, notify_script: Path):
        """Message includes repository name."""
        content = notify_script.read_text()
        assert "GITHUB_REPOSITORY" in content
        assert "*Repository:*" in content

    def test_includes_commit_sha(self, notify_script: Path):
        """Message includes commit SHA (short form)."""
        content = notify_script.read_text()
        assert "GITHUB_SHA" in content
        assert "${GITHUB_SHA:0:7}" in content  # Short SHA

    def test_includes_actor(self, notify_script: Path):
        """Message includes triggering user."""
        content = notify_script.read_text()
        assert "GITHUB_ACTOR" in content
        assert "*Triggered by:*" in content

    def test_includes_workflow_link(self, notify_script: Path):
        """Message includes link to workflow run."""
        content = notify_script.read_text()
        assert "GITHUB_RUN_ID" in content
        assert "View Workflow Run" in content

    def test_includes_timestamp(self, notify_script: Path):
        """Message includes UTC timestamp."""
        content = notify_script.read_text()
        assert "date -u" in content
        assert "UTC" in content


class TestNotifyScriptMarkdown:
    """Test Markdown escaping for Telegram."""

    def test_uses_markdown_v2(self, notify_script: Path):
        """Script uses MarkdownV2 parse mode."""
        content = notify_script.read_text()
        # Script uses escaped quotes in bash JSON
        assert "MarkdownV2" in content
        assert "parse_mode" in content

    def test_escapes_special_characters(self, notify_script: Path):
        """Script escapes Markdown special characters."""
        content = notify_script.read_text()
        assert "escape_markdown" in content
        # Check for common special characters
        assert any(char in content for char in ["\\[", "\\]", "\\(", "\\)"])


class TestNotifyScriptRetry:
    """Test retry logic."""

    def test_has_retry_loop(self, notify_script: Path):
        """Script implements retry logic."""
        content = notify_script.read_text()
        assert "max_retries" in content
        assert "retry" in content.lower()

    def test_retry_count_is_reasonable(self, notify_script: Path):
        """Retry count is reasonable (not too many)."""
        content = notify_script.read_text()
        match = re.search(r"max_retries=(\d+)", content)
        assert match, "max_retries not found"
        retries = int(match.group(1))
        assert 1 <= retries <= 5, f"Retry count {retries} seems unreasonable"


class TestNotifyScriptErrorHandling:
    """Test error handling behavior."""

    def test_continues_on_notification_failure(self, notify_script: Path):
        """Script doesn't fail the pipeline if notification fails."""
        content = notify_script.read_text()
        # After all retries, should still exit 0
        assert "exit 0" in content
        assert "Warning:" in content  # Logs warning but continues


# ============================================================================
# CD Workflow Integration Tests
# ============================================================================


class TestCDWorkflowNotifyJob:
    """Test the notify job in CD workflow."""

    def test_notify_job_exists(self, cd_workflow: dict):
        """CD workflow has a notify job."""
        assert "notify" in cd_workflow["jobs"]

    def test_notify_job_runs_always(self, cd_workflow: dict):
        """Notify job runs regardless of previous job results."""
        notify = cd_workflow["jobs"]["notify"]
        assert notify.get("if") == "always()"

    def test_notify_depends_on_deploy(self, cd_workflow: dict):
        """Notify job depends on deploy job."""
        notify = cd_workflow["jobs"]["notify"]
        assert "deploy" in notify["needs"]

    def test_notify_depends_on_build(self, cd_workflow: dict):
        """Notify job depends on build job for image digest."""
        notify = cd_workflow["jobs"]["notify"]
        assert "build" in notify["needs"]


class TestCDWorkflowNotifySteps:
    """Test notification steps in CD workflow."""

    def test_has_success_notification_step(self, cd_workflow: dict):
        """Workflow has success notification step."""
        notify = cd_workflow["jobs"]["notify"]
        step_names = [s.get("name", "") for s in notify["steps"]]
        assert any("success" in name.lower() for name in step_names)

    def test_has_failure_notification_step(self, cd_workflow: dict):
        """Workflow has failure notification step."""
        notify = cd_workflow["jobs"]["notify"]
        step_names = [s.get("name", "") for s in notify["steps"]]
        assert any("failure" in name.lower() for name in step_names)

    def test_success_step_has_condition(self, cd_workflow: dict):
        """Success notification only runs on success."""
        notify = cd_workflow["jobs"]["notify"]
        success_steps = [
            s for s in notify["steps"]
            if "success" in s.get("name", "").lower()
        ]
        assert len(success_steps) == 1
        assert "success" in success_steps[0].get("if", "")

    def test_failure_step_has_condition(self, cd_workflow: dict):
        """Failure notification only runs on failure."""
        notify = cd_workflow["jobs"]["notify"]
        failure_steps = [
            s for s in notify["steps"]
            if "failure" in s.get("name", "").lower() and "Log" not in s.get("name", "")
        ]
        assert len(failure_steps) == 1
        assert "failure" in failure_steps[0].get("if", "")


class TestCDWorkflowSecrets:
    """Test secrets configuration in CD workflow."""

    def test_uses_telegram_bot_token_secret(self, cd_workflow: dict):
        """Workflow uses TELEGRAM_BOT_TOKEN from secrets."""
        workflow_content = yaml.dump(cd_workflow)
        assert "TELEGRAM_BOT_TOKEN" in workflow_content
        assert "secrets.TELEGRAM_BOT_TOKEN" in workflow_content

    def test_uses_telegram_notify_chat_id_secret(self, cd_workflow: dict):
        """Workflow uses TELEGRAM_NOTIFY_CHAT_ID from secrets."""
        workflow_content = yaml.dump(cd_workflow)
        assert "TELEGRAM_NOTIFY_CHAT_ID" in workflow_content
        assert "secrets.TELEGRAM_NOTIFY_CHAT_ID" in workflow_content

    def test_graceful_without_chat_id(self, cd_workflow: dict):
        """Workflow handles missing TELEGRAM_NOTIFY_CHAT_ID gracefully."""
        notify = cd_workflow["jobs"]["notify"]
        all_runs = [s.get("run", "") for s in notify["steps"] if s.get("run")]
        combined = " ".join(all_runs)
        # Should check if chat ID is set before sending
        assert 'if [[ -n "$TELEGRAM_CHAT_ID"' in combined or \
               "-n" in combined and "TELEGRAM_CHAT_ID" in combined


class TestCDWorkflowEnvironmentVariables:
    """Test environment variable passing in CD workflow."""

    def test_passes_github_sha(self, cd_workflow: dict):
        """Workflow passes GITHUB_SHA to script."""
        notify = cd_workflow["jobs"]["notify"]
        for step in notify["steps"]:
            env = step.get("env", {})
            if "GITHUB_SHA" in env:
                assert env["GITHUB_SHA"] == "${{ github.sha }}"
                return
        pytest.fail("GITHUB_SHA not passed to notification steps")

    def test_passes_github_repository(self, cd_workflow: dict):
        """Workflow passes GITHUB_REPOSITORY to script."""
        notify = cd_workflow["jobs"]["notify"]
        for step in notify["steps"]:
            env = step.get("env", {})
            if "GITHUB_REPOSITORY" in env:
                assert env["GITHUB_REPOSITORY"] == "${{ github.repository }}"
                return
        pytest.fail("GITHUB_REPOSITORY not passed to notification steps")

    def test_passes_github_actor(self, cd_workflow: dict):
        """Workflow passes GITHUB_ACTOR to script."""
        notify = cd_workflow["jobs"]["notify"]
        for step in notify["steps"]:
            env = step.get("env", {})
            if "GITHUB_ACTOR" in env:
                assert env["GITHUB_ACTOR"] == "${{ github.actor }}"
                return
        pytest.fail("GITHUB_ACTOR not passed to notification steps")

    def test_passes_github_run_id(self, cd_workflow: dict):
        """Workflow passes GITHUB_RUN_ID for workflow link."""
        notify = cd_workflow["jobs"]["notify"]
        for step in notify["steps"]:
            env = step.get("env", {})
            if "GITHUB_RUN_ID" in env:
                assert env["GITHUB_RUN_ID"] == "${{ github.run_id }}"
                return
        pytest.fail("GITHUB_RUN_ID not passed to notification steps")


class TestCDWorkflowDeployNotification:
    """Test deployment started notification."""

    def test_deploy_job_sends_started_notification(self, cd_workflow: dict):
        """Deploy job sends 'started' notification."""
        deploy = cd_workflow["jobs"]["deploy"]
        step_names = [s.get("name", "") for s in deploy["steps"]]
        assert any("started" in name.lower() for name in step_names)

    def test_started_notification_before_deploy(self, cd_workflow: dict):
        """Started notification is sent before actual deployment."""
        deploy = cd_workflow["jobs"]["deploy"]
        steps = deploy["steps"]
        started_idx = None
        deploy_idx = None
        for i, s in enumerate(steps):
            if "started" in s.get("name", "").lower():
                started_idx = i
            if "Deploy via SSH" in s.get("name", ""):
                deploy_idx = i
        assert started_idx is not None, "No started notification step"
        assert deploy_idx is not None, "No deploy step"
        assert started_idx < deploy_idx, "Started notification should come before deploy"


# ============================================================================
# T-208 Acceptance Tests
# ============================================================================


class TestT208TelegramDeploymentNotifications:
    """Acceptance tests for T-208: Telegram deployment notifications."""

    def test_notification_script_exists(self, notify_script: Path):
        """AT-208a: Notification script exists and is executable."""
        assert notify_script.exists()
        assert os.access(notify_script, os.X_OK)

    def test_cd_workflow_has_notifications(self, cd_workflow: dict):
        """AT-208b: CD workflow includes notification steps."""
        notify = cd_workflow["jobs"]["notify"]
        step_names = [s.get("name", "") for s in notify["steps"]]
        has_success = any("success" in name.lower() for name in step_names)
        has_failure = any("failure" in name.lower() for name in step_names)
        assert has_success, "Missing success notification"
        assert has_failure, "Missing failure notification"

    def test_notifications_use_telegram_api(self, notify_script: Path):
        """AT-208c: Notifications use Telegram Bot API."""
        content = notify_script.read_text()
        assert "api.telegram.org/bot" in content

    def test_notifications_include_deployment_info(self, notify_script: Path):
        """AT-208d: Notifications include repository, commit, and actor."""
        content = notify_script.read_text()
        assert "GITHUB_REPOSITORY" in content
        assert "GITHUB_SHA" in content
        assert "GITHUB_ACTOR" in content

    def test_notifications_graceful_on_missing_config(self, cd_workflow: dict):
        """AT-208e: Notifications don't fail workflow if not configured."""
        notify = cd_workflow["jobs"]["notify"]
        all_runs = [s.get("run", "") for s in notify["steps"] if s.get("run")]
        combined = " ".join(all_runs)
        # Should check if configured before sending
        assert "if [[ -n" in combined or "-n" in combined


# ============================================================================
# Security Tests
# ============================================================================


class TestNotificationSecurity:
    """Security-related tests for notification system."""

    def test_no_secrets_in_logs(self, notify_script: Path):
        """Script doesn't log sensitive values."""
        content = notify_script.read_text()
        # Should not echo the token or chat ID
        assert "echo $TELEGRAM_BOT_TOKEN" not in content
        assert "echo $TELEGRAM_CHAT_ID" not in content
        assert 'echo "$TELEGRAM_BOT_TOKEN"' not in content
        assert 'echo "$TELEGRAM_CHAT_ID"' not in content

    def test_uses_https_for_api(self, notify_script: Path):
        """Script uses HTTPS for Telegram API."""
        content = notify_script.read_text()
        assert "https://api.telegram.org" in content
        assert "http://api.telegram.org" not in content

    def test_workflow_uses_env_for_secrets(self, cd_workflow: dict):
        """Workflow passes secrets via env, not inline."""
        notify = cd_workflow["jobs"]["notify"]
        for step in notify["steps"]:
            run_cmd = step.get("run", "")
            # Secrets should be passed via env, not interpolated in run
            assert "${{ secrets.TELEGRAM_BOT_TOKEN }}" not in run_cmd
            assert "${{ secrets.TELEGRAM_NOTIFY_CHAT_ID }}" not in run_cmd
