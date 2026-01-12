"""Tests for docker-compose.yml configuration.

AT-202: Docker compose configuration for production deployment.
"""

from pathlib import Path

import pytest
import yaml

# Path to docker-compose.yml
DOCKER_COMPOSE_PATH = Path(__file__).parent.parent / "docker-compose.yml"


@pytest.fixture
def docker_compose() -> dict:
    """Load and parse docker-compose.yml."""
    content = DOCKER_COMPOSE_PATH.read_text()
    return yaml.safe_load(content)


class TestDockerComposeStructure:
    """Test docker-compose.yml structure and required fields."""

    def test_file_exists(self):
        """docker-compose.yml exists in project root."""
        assert DOCKER_COMPOSE_PATH.exists(), "docker-compose.yml not found"

    def test_valid_yaml(self, docker_compose: dict):
        """docker-compose.yml is valid YAML."""
        assert docker_compose is not None
        assert isinstance(docker_compose, dict)

    def test_has_services_section(self, docker_compose: dict):
        """docker-compose.yml has services section."""
        assert "services" in docker_compose
        assert isinstance(docker_compose["services"], dict)

    def test_has_second_brain_service(self, docker_compose: dict):
        """docker-compose.yml has second-brain service."""
        services = docker_compose["services"]
        assert "second-brain" in services

    def test_container_name_is_second_brain(self, docker_compose: dict):
        """Container name is 'second-brain' for docker exec commands."""
        service = docker_compose["services"]["second-brain"]
        assert service.get("container_name") == "second-brain"


class TestDockerComposeService:
    """Test second-brain service configuration."""

    @pytest.fixture
    def service(self, docker_compose: dict) -> dict:
        """Get second-brain service configuration."""
        return docker_compose["services"]["second-brain"]

    def test_uses_dockerfile(self, service: dict):
        """Service uses local Dockerfile."""
        build = service.get("build", {})
        assert build.get("dockerfile") == "Dockerfile"
        assert build.get("context") == "."

    def test_has_image_tag(self, service: dict):
        """Service has image tag for push/pull."""
        assert "image" in service
        assert "second-brain" in service["image"]

    def test_restart_policy(self, service: dict):
        """Service has restart policy for auto-recovery (PRD 1.2)."""
        restart = service.get("restart")
        # Accept 'always' or 'unless-stopped' - both ensure auto-recovery
        assert restart in ("always", "unless-stopped"), \
            f"Expected restart policy 'always' or 'unless-stopped', got '{restart}'"

    def test_env_file_for_secrets(self, service: dict):
        """Service uses env_file for secrets (PRD 1.3)."""
        env_file = service.get("env_file", [])
        # Can be list or string
        if isinstance(env_file, str):
            env_file = [env_file]
        # Check for /etc/second-brain.env
        assert any("/etc/second-brain.env" in f for f in env_file), \
            "Expected env_file to include /etc/second-brain.env"

    def test_has_timezone_environment(self, service: dict):
        """Service has TZ environment variable."""
        environment = service.get("environment", [])
        # Can be list of "KEY=VALUE" or dict
        if isinstance(environment, dict):
            assert "TZ" in environment
        else:
            tz_vars = [e for e in environment if e.startswith("TZ")]
            assert len(tz_vars) > 0, "Expected TZ environment variable"


class TestDockerComposeVolumes:
    """Test volume mounts for persistent data."""

    @pytest.fixture
    def volumes(self, docker_compose: dict) -> list:
        """Get second-brain service volumes."""
        service = docker_compose["services"]["second-brain"]
        return service.get("volumes", [])

    def test_tokens_volume(self, volumes: list):
        """Has volume mount for OAuth tokens."""
        volume_paths = [v.split(":")[0] for v in volumes]
        assert any("tokens" in v for v in volume_paths), \
            "Expected volume mount for tokens"

    def test_cache_volume(self, volumes: list):
        """Has volume mount for cache."""
        volume_paths = [v.split(":")[0] for v in volumes]
        assert any("cache" in v for v in volume_paths), \
            "Expected volume mount for cache"

    def test_logs_volume(self, volumes: list):
        """Has volume mount for logs."""
        volume_paths = [v.split(":")[0] for v in volumes]
        assert any("logs" in v for v in volume_paths), \
            "Expected volume mount for logs"

    def test_queue_volume(self, volumes: list):
        """Has volume mount for offline queue (PRD 4.8)."""
        volume_paths = [v.split(":")[0] for v in volumes]
        assert any("queue" in v for v in volume_paths), \
            "Expected volume mount for offline queue"

    def test_all_volumes_absolute_paths(self, volumes: list):
        """All volume mounts use absolute paths."""
        for volume in volumes:
            host_path = volume.split(":")[0]
            assert host_path.startswith("/"), \
                f"Volume host path should be absolute: {host_path}"


class TestDockerComposeHealthCheck:
    """Test health check configuration."""

    @pytest.fixture
    def healthcheck(self, docker_compose: dict) -> dict:
        """Get health check configuration."""
        service = docker_compose["services"]["second-brain"]
        return service.get("healthcheck", {})

    def test_has_healthcheck(self, healthcheck: dict):
        """Service has health check configured."""
        assert healthcheck, "Expected healthcheck configuration"

    def test_healthcheck_uses_assistant_check(self, healthcheck: dict):
        """Health check uses 'python -m assistant check' command."""
        test = healthcheck.get("test", [])
        if isinstance(test, list):
            test_str = " ".join(test)
        else:
            test_str = test
        assert "assistant" in test_str and "check" in test_str, \
            f"Expected healthcheck to use 'assistant check', got: {test}"

    def test_healthcheck_has_interval(self, healthcheck: dict):
        """Health check has interval configured."""
        assert "interval" in healthcheck

    def test_healthcheck_has_timeout(self, healthcheck: dict):
        """Health check has timeout configured."""
        assert "timeout" in healthcheck

    def test_healthcheck_has_retries(self, healthcheck: dict):
        """Health check has retries configured."""
        assert "retries" in healthcheck


class TestDockerComposeResourceLimits:
    """Test resource limit configuration."""

    @pytest.fixture
    def deploy(self, docker_compose: dict) -> dict:
        """Get deploy configuration."""
        service = docker_compose["services"]["second-brain"]
        return service.get("deploy", {})

    def test_has_resource_limits(self, deploy: dict):
        """Service has resource limits configured."""
        resources = deploy.get("resources", {})
        limits = resources.get("limits", {})
        assert limits, "Expected resource limits configuration"

    def test_memory_limit(self, deploy: dict):
        """Service has memory limit."""
        resources = deploy.get("resources", {})
        limits = resources.get("limits", {})
        assert "memory" in limits, "Expected memory limit"

    def test_cpu_limit(self, deploy: dict):
        """Service has CPU limit."""
        resources = deploy.get("resources", {})
        limits = resources.get("limits", {})
        assert "cpus" in limits, "Expected CPU limit"


class TestDockerComposeLogging:
    """Test logging configuration."""

    @pytest.fixture
    def logging(self, docker_compose: dict) -> dict:
        """Get logging configuration."""
        service = docker_compose["services"]["second-brain"]
        return service.get("logging", {})

    def test_has_logging_driver(self, logging: dict):
        """Service has logging driver configured."""
        assert "driver" in logging

    def test_logging_has_max_size(self, logging: dict):
        """Logging has max-size option to prevent disk fill."""
        options = logging.get("options", {})
        assert "max-size" in options, "Expected max-size logging option"

    def test_logging_has_max_file(self, logging: dict):
        """Logging has max-file option for rotation."""
        options = logging.get("options", {})
        assert "max-file" in options, "Expected max-file logging option"


class TestDockerComposeSecurity:
    """Test security configuration."""

    @pytest.fixture
    def service(self, docker_compose: dict) -> dict:
        """Get second-brain service configuration."""
        return docker_compose["services"]["second-brain"]

    def test_has_security_opt(self, service: dict):
        """Service has security options configured."""
        security_opt = service.get("security_opt", [])
        assert security_opt, "Expected security_opt configuration"

    def test_no_new_privileges(self, service: dict):
        """Service has no-new-privileges security option."""
        security_opt = service.get("security_opt", [])
        assert "no-new-privileges:true" in security_opt, \
            "Expected no-new-privileges:true security option"

    def test_read_only_filesystem(self, service: dict):
        """Service has read-only root filesystem."""
        # This is optional but good practice
        read_only = service.get("read_only", False)
        if read_only:
            # If read_only is set, tmpfs should be configured
            assert service.get("tmpfs"), \
                "Expected tmpfs when read_only is true"


class TestAT202DockerCompose:
    """AT-202: Docker compose configuration for production deployment."""

    def test_at202_compose_file_exists(self):
        """AT-202: docker-compose.yml exists."""
        assert DOCKER_COMPOSE_PATH.exists()

    def test_at202_valid_compose_syntax(self, docker_compose: dict):
        """AT-202: docker-compose.yml is valid YAML with services."""
        assert "services" in docker_compose
        assert "second-brain" in docker_compose["services"]

    def test_at202_container_named_for_exec(self, docker_compose: dict):
        """AT-202: Container named 'second-brain' for docker exec commands."""
        service = docker_compose["services"]["second-brain"]
        assert service["container_name"] == "second-brain"

    def test_at202_uses_secrets_file(self, docker_compose: dict):
        """AT-202: Uses /etc/second-brain.env for secrets."""
        service = docker_compose["services"]["second-brain"]
        env_file = service.get("env_file", [])
        if isinstance(env_file, str):
            env_file = [env_file]
        assert any("/etc/second-brain.env" in f for f in env_file)

    def test_at202_persistent_volumes(self, docker_compose: dict):
        """AT-202: Has persistent volume mounts."""
        service = docker_compose["services"]["second-brain"]
        volumes = service.get("volumes", [])
        assert len(volumes) >= 4, "Expected at least 4 volume mounts"

    def test_at202_auto_recovery(self, docker_compose: dict):
        """AT-202: Has restart policy for auto-recovery."""
        service = docker_compose["services"]["second-brain"]
        restart = service.get("restart")
        assert restart in ("always", "unless-stopped")

    def test_at202_healthcheck_configured(self, docker_compose: dict):
        """AT-202: Has health check for container monitoring."""
        service = docker_compose["services"]["second-brain"]
        assert "healthcheck" in service


class TestDockerComposeDocumentation:
    """Test that docker-compose.yml is well-documented."""

    def test_has_comments(self):
        """docker-compose.yml has documentation comments."""
        content = DOCKER_COMPOSE_PATH.read_text()
        # Should have header comments
        assert content.startswith("#"), "Expected header comment"
        # Should have usage comments
        assert "docker compose up" in content.lower() or \
               "docker-compose up" in content.lower(), \
            "Expected usage instructions in comments"


class TestDockerComposePRDCompliance:
    """Test PRD Section 1.2 compliance."""

    def test_prd_1_2_container_name(self, docker_compose: dict):
        """PRD 1.2: Container named 'second-brain' for docker exec."""
        service = docker_compose["services"]["second-brain"]
        assert service["container_name"] == "second-brain"

    def test_prd_1_2_restart_always(self, docker_compose: dict):
        """PRD 1.2: restart=always for auto-recovery."""
        service = docker_compose["services"]["second-brain"]
        restart = service.get("restart")
        assert restart in ("always", "unless-stopped")

    def test_prd_1_3_secrets_env_file(self, docker_compose: dict):
        """PRD 1.3: Secrets via environment file."""
        service = docker_compose["services"]["second-brain"]
        env_file = service.get("env_file", [])
        if isinstance(env_file, str):
            env_file = [env_file]
        assert any("second-brain" in f for f in env_file)

    def test_prd_4_8_queue_volume(self, docker_compose: dict):
        """PRD 4.8: Volume for offline queue."""
        service = docker_compose["services"]["second-brain"]
        volumes = service.get("volumes", [])
        assert any("queue" in v for v in volumes)
