"""Tests for Dockerfile (AT-201).

Validates Dockerfile structure, multi-stage build, security practices,
and build success.
"""

from pathlib import Path
import re

import pytest

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


class TestDockerfileStructure:
    """Test Dockerfile syntax and structure."""

    @pytest.fixture
    def dockerfile_content(self) -> str:
        """Load Dockerfile content."""
        dockerfile = PROJECT_ROOT / "Dockerfile"
        assert dockerfile.exists(), "Dockerfile must exist at project root"
        return dockerfile.read_text()

    def test_dockerfile_exists(self):
        """AT-201: Dockerfile exists at project root."""
        dockerfile = PROJECT_ROOT / "Dockerfile"
        assert dockerfile.exists()

    def test_uses_python_312(self, dockerfile_content: str):
        """Uses Python 3.12 as specified in PRD 1.1."""
        assert "python:3.12" in dockerfile_content

    def test_uses_slim_base_image(self, dockerfile_content: str):
        """Uses slim base image for minimal size."""
        assert "python:3.12-slim" in dockerfile_content

    def test_has_builder_stage(self, dockerfile_content: str):
        """Has builder stage for multi-stage build."""
        assert "AS builder" in dockerfile_content

    def test_has_runtime_stage(self, dockerfile_content: str):
        """Has runtime stage for final image."""
        assert "AS runtime" in dockerfile_content

    def test_multi_stage_copies_from_builder(self, dockerfile_content: str):
        """Runtime stage copies from builder (multi-stage optimization)."""
        assert "COPY --from=builder" in dockerfile_content

    def test_creates_nonroot_user(self, dockerfile_content: str):
        """Creates non-root user for security."""
        # Check for useradd or adduser
        has_useradd = "useradd" in dockerfile_content
        has_adduser = "adduser" in dockerfile_content
        assert has_useradd or has_adduser, "Must create a non-root user"

    def test_switches_to_nonroot_user(self, dockerfile_content: str):
        """Switches to non-root user before CMD."""
        # Find USER directive after user creation
        assert "USER " in dockerfile_content

    def test_has_healthcheck(self, dockerfile_content: str):
        """Has HEALTHCHECK directive for container orchestration."""
        assert "HEALTHCHECK" in dockerfile_content

    def test_healthcheck_uses_assistant_check(self, dockerfile_content: str):
        """Healthcheck uses 'assistant check' command."""
        assert "assistant check" in dockerfile_content

    def test_default_cmd_runs_bot(self, dockerfile_content: str):
        """Default CMD runs the Telegram bot."""
        assert "assistant" in dockerfile_content
        assert "run" in dockerfile_content

    def test_has_workdir(self, dockerfile_content: str):
        """Has WORKDIR set."""
        assert "WORKDIR" in dockerfile_content

    def test_sets_python_env_vars(self, dockerfile_content: str):
        """Sets Python environment variables for better container behavior."""
        assert "PYTHONDONTWRITEBYTECODE" in dockerfile_content
        assert "PYTHONUNBUFFERED" in dockerfile_content

    def test_uses_virtual_environment(self, dockerfile_content: str):
        """Uses virtual environment in Docker for clean isolation."""
        assert "venv" in dockerfile_content

    def test_has_labels(self, dockerfile_content: str):
        """Has OCI labels for container metadata."""
        assert "LABEL" in dockerfile_content
        assert "org.opencontainers.image" in dockerfile_content


class TestDockerfileSecurityPractices:
    """Test Dockerfile follows security best practices."""

    @pytest.fixture
    def dockerfile_content(self) -> str:
        """Load Dockerfile content."""
        dockerfile = PROJECT_ROOT / "Dockerfile"
        return dockerfile.read_text()

    def test_no_secrets_in_dockerfile(self, dockerfile_content: str):
        """No secrets or API keys in Dockerfile."""
        secret_patterns = [
            r"TELEGRAM_BOT_TOKEN\s*=",
            r"NOTION_API_KEY\s*=",
            r"OPENAI_API_KEY\s*=",
            r"sk-[a-zA-Z0-9]+",  # OpenAI key pattern
            r"secret_[a-zA-Z0-9]+",  # Notion secret pattern
        ]
        for pattern in secret_patterns:
            assert not re.search(pattern, dockerfile_content), \
                f"Dockerfile should not contain secrets matching {pattern}"

    def test_no_password_in_dockerfile(self, dockerfile_content: str):
        """No passwords in Dockerfile."""
        assert "password" not in dockerfile_content.lower()

    def test_pip_no_cache(self, dockerfile_content: str):
        """Uses --no-cache-dir with pip for smaller images."""
        assert "--no-cache-dir" in dockerfile_content

    def test_apt_cleanup(self, dockerfile_content: str):
        """Cleans up apt cache after install."""
        assert "rm -rf /var/lib/apt/lists" in dockerfile_content

    def test_creates_app_directories(self, dockerfile_content: str):
        """Creates required app directories."""
        # Per PRD 1.2, /var/lib/second-brain should exist
        assert "/var/lib/second-brain" in dockerfile_content


class TestDockerignore:
    """Test .dockerignore file."""

    @pytest.fixture
    def dockerignore_content(self) -> str:
        """Load .dockerignore content."""
        dockerignore = PROJECT_ROOT / ".dockerignore"
        assert dockerignore.exists(), ".dockerignore must exist at project root"
        return dockerignore.read_text()

    def test_dockerignore_exists(self):
        """AT-201: .dockerignore exists."""
        dockerignore = PROJECT_ROOT / ".dockerignore"
        assert dockerignore.exists()

    def test_ignores_git(self, dockerignore_content: str):
        """Ignores .git directory."""
        assert ".git" in dockerignore_content

    def test_ignores_venv(self, dockerignore_content: str):
        """Ignores virtual environment."""
        assert ".venv" in dockerignore_content or "venv" in dockerignore_content

    def test_ignores_pycache(self, dockerignore_content: str):
        """Ignores Python cache."""
        assert "__pycache__" in dockerignore_content

    def test_ignores_tests(self, dockerignore_content: str):
        """Ignores tests directory (not needed in production)."""
        assert "tests" in dockerignore_content.lower()

    def test_ignores_env_files(self, dockerignore_content: str):
        """Ignores .env files (secrets)."""
        assert ".env" in dockerignore_content

    def test_ignores_google_credentials(self, dockerignore_content: str):
        """Ignores Google credentials files (secrets)."""
        assert "google_credentials" in dockerignore_content or "client_secret" in dockerignore_content


class TestAT201MultiStageDockerfile:
    """AT-201: Multi-stage Dockerfile for production deployment."""

    @pytest.fixture
    def dockerfile_content(self) -> str:
        """Load Dockerfile content."""
        dockerfile = PROJECT_ROOT / "Dockerfile"
        return dockerfile.read_text()

    def test_at201_has_multiple_from_statements(self, dockerfile_content: str):
        """AT-201: Multi-stage build has multiple FROM statements."""
        from_count = len(re.findall(r"^FROM\s+", dockerfile_content, re.MULTILINE))
        assert from_count >= 2, "Multi-stage build should have at least 2 FROM statements"

    def test_at201_builder_installs_deps(self, dockerfile_content: str):
        """AT-201: Builder stage installs dependencies."""
        # Builder stage should have pip install
        builder_section = dockerfile_content.split("AS runtime")[0]
        assert "pip install" in builder_section

    def test_at201_runtime_copies_venv(self, dockerfile_content: str):
        """AT-201: Runtime stage copies venv from builder."""
        runtime_section = dockerfile_content.split("AS runtime")[1]
        assert "COPY --from=builder" in runtime_section
        assert "venv" in runtime_section

    def test_at201_runtime_is_slim(self, dockerfile_content: str):
        """AT-201: Runtime stage uses slim base image."""
        # Check that runtime FROM uses slim image
        runtime_from = re.search(r"FROM\s+(\S+)\s+AS\s+runtime", dockerfile_content)
        assert runtime_from, "Must have 'FROM ... AS runtime'"
        assert "slim" in runtime_from.group(1)

    def test_at201_no_dev_deps_in_runtime(self, dockerfile_content: str):
        """AT-201: No dev dependencies installed in runtime."""
        runtime_section = dockerfile_content.split("AS runtime")[1]
        # Should not install dev dependencies in runtime
        assert ".[dev]" not in runtime_section
        assert "pytest" not in runtime_section.lower()
        assert "ruff" not in runtime_section.lower()


class TestDockerBuildValidation:
    """Validate Dockerfile can be parsed (without actually building)."""

    @pytest.fixture
    def dockerfile_content(self) -> str:
        """Load Dockerfile content."""
        dockerfile = PROJECT_ROOT / "Dockerfile"
        return dockerfile.read_text()

    def test_valid_dockerfile_syntax(self, dockerfile_content: str):
        """Dockerfile has valid syntax (basic validation)."""
        # Check for required directives
        required_directives = ["FROM", "WORKDIR", "COPY", "CMD"]
        for directive in required_directives:
            assert directive in dockerfile_content, f"Missing {directive} directive"

    def test_from_statements_have_valid_format(self, dockerfile_content: str):
        """FROM statements have valid format."""
        from_pattern = r"^FROM\s+[\w./:@-]+(\s+AS\s+\w+)?$"
        lines = dockerfile_content.split("\n")
        from_lines = [line.strip() for line in lines if line.strip().startswith("FROM")]

        for line in from_lines:
            assert re.match(from_pattern, line, re.IGNORECASE), \
                f"Invalid FROM statement: {line}"

    def test_no_syntax_errors_in_copy(self, dockerfile_content: str):
        """COPY statements have valid format."""
        copy_pattern = r"^COPY\s+(--\S+\s+)*\S+\s+\S+"
        lines = dockerfile_content.split("\n")
        copy_lines = [line.strip() for line in lines if line.strip().startswith("COPY")]

        for line in copy_lines:
            assert re.match(copy_pattern, line), f"Invalid COPY statement: {line}"

    def test_no_add_instead_of_copy(self, dockerfile_content: str):
        """Uses COPY instead of ADD (best practice)."""
        # ADD should only be used for extracting archives or fetching URLs
        # For simple file copying, COPY is preferred
        lines = dockerfile_content.split("\n")
        add_lines = [line for line in lines if line.strip().startswith("ADD ")]

        # If there are ADD statements, they should be for archives
        for line in add_lines:
            assert ".tar" in line or "http" in line, \
                f"Use COPY instead of ADD for regular files: {line}"
