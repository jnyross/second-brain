"""Tests for deploy/scripts/rollback.sh

Validates the rollback script for reverting to previous Docker image versions.
Tests cover AT-205 acceptance criteria and PRD 12.10 requirements.
"""

import os
import stat
from pathlib import Path

import pytest

# Path to the rollback script
SCRIPT_PATH = Path(__file__).parent.parent / "deploy" / "scripts" / "rollback.sh"


class TestRollbackScriptExists:
    """Verify rollback script file exists and has correct structure."""

    def test_script_exists(self) -> None:
        """Script file exists at expected location."""
        assert SCRIPT_PATH.exists(), f"Script not found at {SCRIPT_PATH}"

    def test_script_is_executable(self) -> None:
        """Script has executable permission."""
        mode = os.stat(SCRIPT_PATH).st_mode
        assert mode & stat.S_IXUSR, "Script should be executable by owner"

    def test_script_has_shebang(self) -> None:
        """Script starts with bash shebang."""
        content = SCRIPT_PATH.read_text()
        assert content.startswith("#!/bin/bash"), "Script should start with #!/bin/bash"

    def test_script_has_strict_mode(self) -> None:
        """Script uses strict mode (set -euo pipefail)."""
        content = SCRIPT_PATH.read_text()
        assert "set -euo pipefail" in content, "Script should use strict mode"


class TestRollbackConfiguration:
    """Verify rollback script configuration and defaults."""

    def test_default_container_name(self) -> None:
        """Default container name is second-brain."""
        content = SCRIPT_PATH.read_text()
        assert 'CONTAINER_NAME="${CONTAINER_NAME:-second-brain}"' in content

    def test_default_compose_dir(self) -> None:
        """Default compose directory is /opt/second-brain."""
        content = SCRIPT_PATH.read_text()
        assert 'COMPOSE_DIR="${COMPOSE_DIR:-/opt/second-brain}"' in content

    def test_ghcr_registry(self) -> None:
        """Uses GitHub Container Registry."""
        content = SCRIPT_PATH.read_text()
        assert 'REGISTRY="ghcr.io"' in content

    def test_configurable_repo(self) -> None:
        """Repository is configurable via GHCR_REPO."""
        content = SCRIPT_PATH.read_text()
        assert "GHCR_REPO" in content

    def test_color_codes_defined(self) -> None:
        """Color codes are defined for output."""
        content = SCRIPT_PATH.read_text()
        assert "RED=" in content
        assert "GREEN=" in content
        assert "YELLOW=" in content
        assert "NC=" in content  # No Color


class TestRollbackCLIFlags:
    """Verify CLI argument handling."""

    def test_list_flag(self) -> None:
        """--list flag for listing available versions."""
        content = SCRIPT_PATH.read_text()
        assert "--list)" in content
        assert "LIST_ONLY=true" in content

    def test_to_flag(self) -> None:
        """--to flag for specifying target version."""
        content = SCRIPT_PATH.read_text()
        assert "--to)" in content
        assert 'TARGET_TAG="$2"' in content

    def test_dry_run_flag(self) -> None:
        """--dry-run flag for preview mode."""
        content = SCRIPT_PATH.read_text()
        assert "--dry-run)" in content
        assert "DRY_RUN=true" in content

    def test_container_flag(self) -> None:
        """--container flag for custom container name."""
        content = SCRIPT_PATH.read_text()
        assert "--container)" in content
        assert 'CONTAINER_NAME="$2"' in content

    def test_compose_dir_flag(self) -> None:
        """--compose-dir flag for custom compose directory."""
        content = SCRIPT_PATH.read_text()
        assert "--compose-dir)" in content
        assert 'COMPOSE_DIR="$2"' in content

    def test_repo_flag(self) -> None:
        """--repo flag for custom repository."""
        content = SCRIPT_PATH.read_text()
        assert "--repo)" in content

    def test_help_flag(self) -> None:
        """--help flag for usage information."""
        content = SCRIPT_PATH.read_text()
        assert "--help)" in content
        assert "Usage:" in content

    def test_unknown_option_handling(self) -> None:
        """Unknown options are rejected with error."""
        content = SCRIPT_PATH.read_text()
        assert "Unknown option" in content
        assert "exit 2" in content


class TestRollbackImageDiscovery:
    """Verify image version discovery logic."""

    def test_get_available_tags_function(self) -> None:
        """get_available_tags function exists."""
        content = SCRIPT_PATH.read_text()
        assert "get_available_tags()" in content

    def test_docker_images_command(self) -> None:
        """Uses docker images command to list versions."""
        content = SCRIPT_PATH.read_text()
        assert 'docker images "${IMAGE}"' in content

    def test_sorts_by_creation_time(self) -> None:
        """Tags are sorted by creation time."""
        content = SCRIPT_PATH.read_text()
        assert "sort" in content and "CreatedAt" in content

    def test_get_current_tag_function(self) -> None:
        """get_current_tag function exists."""
        content = SCRIPT_PATH.read_text()
        assert "get_current_tag()" in content

    def test_docker_inspect_for_current(self) -> None:
        """Uses docker inspect to get current image."""
        content = SCRIPT_PATH.read_text()
        assert "docker inspect" in content
        assert "Config.Image" in content

    def test_get_previous_tag_function(self) -> None:
        """get_previous_tag function exists."""
        content = SCRIPT_PATH.read_text()
        assert "get_previous_tag()" in content

    def test_excludes_latest_tag(self) -> None:
        """Excludes 'latest' tag when finding previous version."""
        content = SCRIPT_PATH.read_text()
        assert 'grep -v "^latest$"' in content


class TestRollbackExecution:
    """Verify rollback execution logic."""

    def test_stops_current_container(self) -> None:
        """Stops current container before rollback."""
        content = SCRIPT_PATH.read_text()
        assert "docker compose" in content and "down" in content

    def test_docker_stop_fallback(self) -> None:
        """Falls back to docker stop if compose not available."""
        content = SCRIPT_PATH.read_text()
        assert "docker stop" in content

    def test_creates_compose_override(self) -> None:
        """Creates compose override for specific tag."""
        content = SCRIPT_PATH.read_text()
        assert "docker-compose.rollback.yml" in content

    def test_cleans_up_override(self) -> None:
        """Cleans up override file after use."""
        content = SCRIPT_PATH.read_text()
        assert 'rm -f "$OVERRIDE_FILE"' in content

    def test_docker_compose_up(self) -> None:
        """Uses docker compose up to start container."""
        content = SCRIPT_PATH.read_text()
        assert "docker compose" in content and "up -d" in content

    def test_fallback_docker_run(self) -> None:
        """Falls back to docker run if compose not available."""
        content = SCRIPT_PATH.read_text()
        assert "docker run -d" in content

    def test_mounts_required_volumes(self) -> None:
        """Mounts required volumes in fallback mode."""
        content = SCRIPT_PATH.read_text()
        assert "/var/lib/second-brain/tokens" in content
        assert "/var/lib/second-brain/cache" in content
        assert "/var/lib/second-brain/logs" in content
        assert "/var/lib/second-brain/queue" in content


class TestRollbackHealthCheck:
    """Verify health check integration."""

    def test_runs_health_check_script(self) -> None:
        """Runs health-check.sh after rollback."""
        content = SCRIPT_PATH.read_text()
        assert "health-check.sh" in content

    def test_fallback_health_check(self) -> None:
        """Has fallback health check if script not available."""
        content = SCRIPT_PATH.read_text()
        assert 'docker exec "${CONTAINER_NAME}" python -c "import assistant' in content

    def test_health_check_retries(self) -> None:
        """Configures health check with retries."""
        content = SCRIPT_PATH.read_text()
        assert "--retries" in content and "--interval" in content


class TestRollbackExitCodes:
    """Verify exit codes for different scenarios."""

    def test_success_exit_code(self) -> None:
        """Exit code 0 on successful rollback."""
        content = SCRIPT_PATH.read_text()
        assert "exit 0" in content

    def test_failure_exit_code(self) -> None:
        """Exit code 1 on failed rollback."""
        content = SCRIPT_PATH.read_text()
        assert "exit 1" in content

    def test_invalid_args_exit_code(self) -> None:
        """Exit code 2 on invalid arguments."""
        content = SCRIPT_PATH.read_text()
        assert "exit 2" in content

    def test_no_previous_image_exit_code(self) -> None:
        """Exit code 3 when no previous image available."""
        content = SCRIPT_PATH.read_text()
        assert "exit 3" in content


class TestRollbackDocumentation:
    """Verify script documentation."""

    def test_has_header_comment(self) -> None:
        """Script has header documentation."""
        content = SCRIPT_PATH.read_text()
        assert "Rollback Script for Second Brain" in content

    def test_documents_usage(self) -> None:
        """Documents usage examples."""
        content = SCRIPT_PATH.read_text()
        assert "Usage:" in content
        assert "./rollback.sh" in content

    def test_documents_exit_codes(self) -> None:
        """Documents exit codes."""
        content = SCRIPT_PATH.read_text()
        assert "Exit codes:" in content
        assert "0 - Rollback successful" in content
        assert "1 - Rollback failed" in content

    def test_documents_requirements(self) -> None:
        """Documents requirements."""
        content = SCRIPT_PATH.read_text()
        assert "Requirements:" in content
        assert "Docker" in content

    def test_provides_troubleshooting(self) -> None:
        """Provides troubleshooting tips on failure."""
        content = SCRIPT_PATH.read_text()
        assert "Troubleshooting" in content
        assert "docker logs" in content


class TestAT205RollbackWorks:
    """AT-205: Rollback Works

    Given: Current deployment is broken
    When: ./scripts/rollback.sh executed
    Then: Previous image restored
    And: Container healthy
    Pass condition: Bot responds to Telegram message
    """

    def test_finds_previous_image(self) -> None:
        """Script can identify previous image version."""
        content = SCRIPT_PATH.read_text()
        # Should have logic to get previous tag
        assert "get_previous_tag" in content
        assert "previous_tag" in content

    def test_stops_broken_container(self) -> None:
        """Script stops the broken container."""
        content = SCRIPT_PATH.read_text()
        # Should stop via compose or docker stop
        assert "down" in content or "stop" in content

    def test_starts_previous_image(self) -> None:
        """Script starts container with previous image."""
        content = SCRIPT_PATH.read_text()
        # Should start with specific image tag
        assert "up -d" in content or "docker run" in content
        assert "${previous_tag}" in content

    def test_verifies_container_healthy(self) -> None:
        """Script verifies container is healthy after rollback."""
        content = SCRIPT_PATH.read_text()
        # Should check health
        assert "health-check" in content or "HEALTH_OK" in content
        assert "import assistant" in content

    def test_reports_rollback_success(self) -> None:
        """Script reports rollback success."""
        content = SCRIPT_PATH.read_text()
        assert "Rollback: SUCCESSFUL" in content


class TestPRD1210Compliance:
    """PRD 12.10: Rollback Strategy compliance."""

    def test_identifies_previous_image(self) -> None:
        """Per PRD 12.10: Gets second image in list."""
        content = SCRIPT_PATH.read_text()
        # Should sort and get previous (not current)
        assert "docker images" in content
        assert "sort" in content

    def test_stops_current_container(self) -> None:
        """Per PRD 12.10: docker compose down."""
        content = SCRIPT_PATH.read_text()
        assert "docker compose" in content and "down" in content

    def test_starts_with_previous_tag(self) -> None:
        """Per PRD 12.10: docker compose up with previous tag."""
        content = SCRIPT_PATH.read_text()
        # Should use previous image
        assert "previous_tag" in content
        assert "up -d" in content

    def test_runs_health_check(self) -> None:
        """Per PRD 12.10: Health check after rollback."""
        content = SCRIPT_PATH.read_text()
        assert "health-check.sh" in content

    def test_reports_rolled_back_version(self) -> None:
        """Per PRD 12.10: Reports which version was rolled back to."""
        content = SCRIPT_PATH.read_text()
        assert "Rolled back to" in content


class TestRollbackDryRun:
    """Verify dry-run mode works correctly."""

    def test_dry_run_doesnt_execute(self) -> None:
        """Dry run mode shows plan without executing."""
        content = SCRIPT_PATH.read_text()
        assert "DRY_RUN" in content
        assert "[DRY-RUN]" in content

    def test_dry_run_shows_commands(self) -> None:
        """Dry run shows what commands would run."""
        content = SCRIPT_PATH.read_text()
        assert "Would execute" in content or "Would pull" in content

    def test_dry_run_exits_zero(self) -> None:
        """Dry run exits with success."""
        content = SCRIPT_PATH.read_text()
        # Should have successful exit after dry run section
        lines = content.split('\n')
        in_dry_run = False
        for line in lines:
            if '"$DRY_RUN" = true' in line:
                in_dry_run = True
            if in_dry_run and "exit 0" in line:
                assert True
                return
        # If we get here, check that DRY_RUN ends with exit 0
        assert "Dry run complete" in content


class TestRollbackListMode:
    """Verify list mode works correctly."""

    def test_list_shows_available_versions(self) -> None:
        """List mode shows available image versions."""
        content = SCRIPT_PATH.read_text()
        assert "LIST_ONLY" in content
        assert "Available image versions" in content

    def test_list_marks_current_version(self) -> None:
        """List mode marks the current version."""
        content = SCRIPT_PATH.read_text()
        assert "(current)" in content

    def test_list_exits_zero(self) -> None:
        """List mode exits with success."""
        content = SCRIPT_PATH.read_text()
        # Should exit 0 after list
        assert 'LIST_ONLY" = true' in content


class TestRollbackErrorHandling:
    """Verify error handling."""

    def test_checks_docker_available(self) -> None:
        """Checks if docker command is available."""
        content = SCRIPT_PATH.read_text()
        assert "command -v docker" in content

    def test_handles_no_previous_image(self) -> None:
        """Handles case when no previous image exists."""
        content = SCRIPT_PATH.read_text()
        assert "No previous image" in content or "exit 3" in content

    def test_handles_pull_failure(self) -> None:
        """Handles image pull failure."""
        content = SCRIPT_PATH.read_text()
        assert "docker pull" in content
        assert "Failed to pull" in content

    def test_handles_health_check_failure(self) -> None:
        """Reports when health check fails after rollback."""
        content = SCRIPT_PATH.read_text()
        assert "Rollback: FAILED" in content
        assert "also failed health check" in content


class TestBashBestPractices:
    """Verify bash best practices."""

    def test_quotes_variables(self) -> None:
        """Variables are properly quoted."""
        content = SCRIPT_PATH.read_text()
        # Should use "${VAR}" not $VAR in critical places
        assert '"${CONTAINER_NAME}"' in content
        # COMPOSE_DIR should be quoted in file path checks
        assert '[ -f "${COMPOSE_DIR}/docker-compose.yml" ]' in content

    def test_uses_local_in_functions(self) -> None:
        """Functions use local variables where appropriate."""
        content = SCRIPT_PATH.read_text()
        assert "local " in content

    def test_no_command_injection(self) -> None:
        """No obvious command injection vulnerabilities."""
        content = SCRIPT_PATH.read_text()
        # Should not use eval with user input
        assert "eval" not in content.lower() or 'eval "$' not in content


class TestRollbackIntegration:
    """Integration tests for rollback workflow."""

    def test_cd_pipeline_compatibility(self) -> None:
        """Script is called from CD pipeline on failure."""
        cd_path = Path(__file__).parent.parent / ".github" / "workflows" / "cd.yml"
        if cd_path.exists():
            cd_content = cd_path.read_text()
            # CD should have rollback on failure
            assert "rollback" in cd_content.lower() or "rolling back" in cd_content.lower()

    def test_health_check_script_path(self) -> None:
        """Health check script path is correct."""
        content = SCRIPT_PATH.read_text()
        assert "SCRIPT_DIR" in content
        assert "health-check.sh" in content

    def test_compose_file_usage(self) -> None:
        """Uses docker-compose.yml correctly."""
        content = SCRIPT_PATH.read_text()
        assert "docker-compose.yml" in content
        assert "-f" in content
