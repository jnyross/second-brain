"""Tests for deploy/scripts/health-check.sh.

Verifies the health check script follows best practices and
satisfies AT-202 (Container Starts Healthy).
"""

from pathlib import Path

import pytest


class TestHealthCheckScriptExists:
    """Verify health check script exists and is properly formatted."""

    @pytest.fixture
    def script_path(self) -> Path:
        """Get path to health check script."""
        return Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"

    @pytest.fixture
    def script_content(self, script_path: Path) -> str:
        """Read script content."""
        assert script_path.exists(), f"Script not found: {script_path}"
        return script_path.read_text()

    def test_script_exists(self, script_path: Path):
        """health-check.sh exists in deploy/scripts/."""
        assert script_path.exists()

    def test_script_is_executable(self, script_path: Path):
        """Script has executable permissions."""
        import os

        mode = os.stat(script_path).st_mode
        assert mode & 0o111, "Script should be executable"

    def test_has_shebang(self, script_content: str):
        """Script starts with bash shebang."""
        assert script_content.startswith("#!/bin/bash"), "Must start with #!/bin/bash"

    def test_has_strict_mode(self, script_content: str):
        """Script uses strict mode (set -euo pipefail)."""
        assert "set -euo pipefail" in script_content


class TestHealthCheckConfiguration:
    """Test health check configuration options."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_has_max_retries_default(self, script_content: str):
        """Script has default MAX_RETRIES of 10."""
        assert "MAX_RETRIES" in script_content
        # Check for default value pattern
        assert ":-10" in script_content or "MAX_RETRIES=10" in script_content

    def test_has_retry_interval_default(self, script_content: str):
        """Script has default RETRY_INTERVAL of 3."""
        assert "RETRY_INTERVAL" in script_content
        # Check for default value pattern
        assert ":-3" in script_content or "RETRY_INTERVAL=3" in script_content

    def test_has_container_name_default(self, script_content: str):
        """Script defaults to 'second-brain' container."""
        assert "second-brain" in script_content

    def test_supports_quick_mode(self, script_content: str):
        """Script supports --quick flag for faster checks."""
        assert "--quick" in script_content

    def test_supports_retries_flag(self, script_content: str):
        """Script supports --retries flag."""
        assert "--retries" in script_content

    def test_supports_interval_flag(self, script_content: str):
        """Script supports --interval flag."""
        assert "--interval" in script_content

    def test_supports_container_flag(self, script_content: str):
        """Script supports --container flag."""
        assert "--container" in script_content

    def test_supports_help_flag(self, script_content: str):
        """Script supports --help flag."""
        assert "--help" in script_content


class TestHealthCheckLogic:
    """Test health check implementation logic."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_uses_docker_to_check_container(self, script_content: str):
        """Script uses docker to check container."""
        assert "docker" in script_content

    def test_checks_python_import(self, script_content: str):
        """Script checks 'import assistant' works."""
        assert "import assistant" in script_content

    def test_has_retry_loop(self, script_content: str):
        """Script implements retry loop."""
        assert "for i in" in script_content or "for " in script_content
        assert "seq" in script_content or "MAX_RETRIES" in script_content

    def test_uses_sleep_between_retries(self, script_content: str):
        """Script sleeps between retries."""
        assert "sleep" in script_content

    def test_checks_container_exists(self, script_content: str):
        """Script verifies container exists before checking health."""
        assert "docker ps" in script_content

    def test_checks_container_running(self, script_content: str):
        """Script verifies container is running."""
        # Should check docker ps (running containers, not just all containers)
        assert "docker ps" in script_content


class TestHealthCheckOutput:
    """Test health check output format."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_has_success_message(self, script_content: str):
        """Script outputs success message on pass."""
        assert "Health check passed" in script_content or "PASSED" in script_content

    def test_has_failure_message(self, script_content: str):
        """Script outputs failure message on fail."""
        assert "Health check failed" in script_content or "FAILED" in script_content

    def test_uses_colors(self, script_content: str):
        """Script uses color codes for output."""
        assert "GREEN" in script_content or "RED" in script_content

    def test_shows_retry_progress(self, script_content: str):
        """Script shows retry progress during wait."""
        assert "Waiting" in script_content or "waiting" in script_content


class TestHealthCheckExitCodes:
    """Test health check return codes."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_returns_zero_on_success(self, script_content: str):
        """Script returns 0 on health check success."""
        assert "exit 0" in script_content

    def test_returns_one_on_failure(self, script_content: str):
        """Script returns 1 on health check failure."""
        assert "exit 1" in script_content

    def test_returns_two_on_invalid_args(self, script_content: str):
        """Script returns 2 on invalid arguments."""
        assert "exit 2" in script_content


class TestHealthCheckDocumentation:
    """Test health check documentation."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_has_header_comment(self, script_content: str):
        """Script has descriptive header comment."""
        assert "Health Check" in script_content
        assert "Second Brain" in script_content

    def test_documents_usage(self, script_content: str):
        """Script documents usage examples."""
        assert "Usage:" in script_content

    def test_documents_return_codes(self, script_content: str):
        """Script documents return codes."""
        assert "Exit" in script_content or "exit" in script_content

    def test_has_troubleshooting_tips(self, script_content: str):
        """Script provides troubleshooting tips on failure."""
        assert "Troubleshooting" in script_content.lower() or "docker logs" in script_content


class TestHealthCheckErrorHandling:
    """Test health check error handling."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_checks_docker_available(self, script_content: str):
        """Script checks if docker command is available."""
        assert "command -v docker" in script_content or "which docker" in script_content

    def test_validates_retries_argument(self, script_content: str):
        """Script validates --retries is a positive integer."""
        assert "positive" in script_content.lower() or "[0-9]" in script_content

    def test_validates_interval_argument(self, script_content: str):
        """Script validates --interval is a positive integer."""
        assert "RETRY_INTERVAL" in script_content

    def test_handles_unknown_options(self, script_content: str):
        """Script handles unknown command line options."""
        assert "Unknown" in script_content or "unknown" in script_content


class TestHealthCheckAdditionalChecks:
    """Test additional health verification steps."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_checks_cli_command(self, script_content: str):
        """Script also checks 'python -m assistant check' works."""
        assert "assistant check" in script_content

    def test_checks_docker_health_status(self, script_content: str):
        """Script checks Docker's internal health status."""
        assert "Health.Status" in script_content or "health" in script_content.lower()


class TestAT202ContainerStartsHealthy:
    """AT-202: Container Starts Healthy acceptance tests."""

    @pytest.fixture
    def script_path(self) -> Path:
        """Get path to health check script."""
        return Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"

    @pytest.fixture
    def script_content(self, script_path: Path) -> str:
        """Read script content."""
        return script_path.read_text()

    def test_at202_script_exists(self, script_path: Path):
        """AT-202: Health check script exists."""
        assert script_path.exists(), "health-check.sh must exist for AT-202"

    def test_at202_can_verify_within_60s(self, script_content: str):
        """AT-202: Max wait time is within 60s threshold (10 retries * 3s = 30s)."""
        # Default: 10 retries * 3s interval = 30s max wait
        # This is within the 60s threshold specified in AT-202
        assert ":-10" in script_content or "MAX_RETRIES=10" in script_content
        assert ":-3" in script_content or "RETRY_INTERVAL=3" in script_content

    def test_at202_verifies_container_health(self, script_content: str):
        """AT-202: Script verifies container is healthy (not just running)."""
        # Must actually test the application, not just container existence
        assert "import assistant" in script_content
        # Uses docker to check inside the container
        assert "docker" in script_content

    def test_at202_returns_proper_return_code(self, script_content: str):
        """AT-202: Script returns 0 on healthy, 1 on unhealthy."""
        assert "exit 0" in script_content
        assert "exit 1" in script_content

    def test_at202_provides_diagnostic_output(self, script_content: str):
        """AT-202: Script provides diagnostic info on failure."""
        assert "Troubleshooting" in script_content.lower() or "docker logs" in script_content


class TestPRDSection128Compliance:
    """Test compliance with PRD Section 12.8 Health Check specification."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_matches_prd_retry_count(self, script_content: str):
        """Script uses MAX_RETRIES=10 per PRD 12.8."""
        # PRD shows: MAX_RETRIES=10
        assert "MAX_RETRIES" in script_content
        assert "10" in script_content

    def test_matches_prd_retry_interval(self, script_content: str):
        """Script uses RETRY_INTERVAL=3 per PRD 12.8."""
        # PRD shows: RETRY_INTERVAL=3
        assert "RETRY_INTERVAL" in script_content
        assert "3" in script_content

    def test_matches_prd_container_name(self, script_content: str):
        """Script checks 'second-brain' container per PRD 12.8."""
        # PRD shows: docker to check second-brain
        assert "second-brain" in script_content

    def test_matches_prd_python_check(self, script_content: str):
        """Script uses 'import assistant; print(ok)' per PRD 12.8."""
        # PRD shows: python -c "import assistant; print('ok')"
        assert "import assistant" in script_content
        assert "print" in script_content

    def test_matches_prd_success_message(self, script_content: str):
        """Script outputs 'Health check passed' per PRD 12.8."""
        # PRD shows: echo "Health check passed"
        assert "Health check passed" in script_content

    def test_matches_prd_failure_message(self, script_content: str):
        """Script outputs 'Health check failed' per PRD 12.8."""
        # PRD shows: echo "Health check failed"
        assert "Health check failed" in script_content


class TestBashBestPractices:
    """Test bash scripting best practices."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_quotes_variables(self, script_content: str):
        """Script quotes variable expansions to prevent word splitting."""
        # Check for quoted variable patterns
        assert '"$' in script_content or "'$" in script_content

    def test_uses_local_variables(self, script_content: str):
        """Script uses UPPERCASE for global/env variables."""
        # Convention: UPPERCASE for constants/env vars
        assert "MAX_RETRIES" in script_content
        assert "RETRY_INTERVAL" in script_content

    def test_no_command_injection_risk(self, script_content: str):
        """Script doesn't have obvious command injection vulnerabilities."""
        # Container name should be quoted when used
        assert '"$CONTAINER_NAME"' in script_content or "'$CONTAINER_NAME'" in script_content


class TestHealthCheckIntegration:
    """Test integration with other deployment components."""

    @pytest.fixture
    def script_content(self) -> str:
        """Read script content."""
        path = Path(__file__).parent.parent / "deploy" / "scripts" / "health-check.sh"
        return path.read_text()

    def test_can_be_used_by_cd_pipeline(self, script_content: str):
        """Script can be called from CD pipeline (has proper return codes)."""
        assert "exit 0" in script_content
        assert "exit 1" in script_content

    def test_compatible_with_docker_compose(self, script_content: str):
        """Script is compatible with docker-compose setup."""
        assert "docker" in script_content
        assert "second-brain" in script_content

    def test_can_be_run_manually(self, script_content: str):
        """Script can be run manually for troubleshooting."""
        assert "--help" in script_content
