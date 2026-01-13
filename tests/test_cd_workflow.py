"""Tests for GitHub Actions CD workflow configuration.

Validates that cd.yml follows PRD 12.5 requirements and GitHub Actions best practices.
"""

from pathlib import Path

import pytest
import yaml

# Path to the CD workflow file
CD_WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "cd.yml"


@pytest.fixture
def workflow_content():
    """Load the CD workflow file content."""
    if not CD_WORKFLOW_PATH.exists():
        pytest.skip(f"CD workflow not found at {CD_WORKFLOW_PATH}")
    return CD_WORKFLOW_PATH.read_text()


@pytest.fixture
def workflow(workflow_content):
    """Parse the CD workflow as YAML."""
    return yaml.safe_load(workflow_content)


class TestCDWorkflowExists:
    """Verify CD workflow file exists and is valid YAML."""

    def test_cd_workflow_file_exists(self):
        """CD workflow file should exist at .github/workflows/cd.yml."""
        assert CD_WORKFLOW_PATH.exists(), f"CD workflow not found at {CD_WORKFLOW_PATH}"

    def test_cd_workflow_is_valid_yaml(self, workflow_content):
        """CD workflow should be valid YAML."""
        try:
            yaml.safe_load(workflow_content)
        except yaml.YAMLError as e:
            pytest.fail(f"CD workflow is not valid YAML: {e}")

    def test_cd_workflow_has_name(self, workflow):
        """CD workflow should have a name."""
        assert "name" in workflow
        assert workflow["name"] == "CD"


class TestCDWorkflowTriggers:
    """Verify CD workflow trigger configuration."""

    def test_triggers_on_ci_workflow_completion(self, workflow):
        """CD workflow should trigger when CI workflow completes on main."""
        # 'on' is parsed as True in YAML, so check for True key
        triggers = workflow.get(True, workflow.get("on", {}))
        assert "workflow_run" in triggers
        workflow_run = triggers["workflow_run"]
        assert "CI" in workflow_run.get("workflows", [])
        assert "completed" in workflow_run.get("types", [])
        assert "main" in workflow_run.get("branches", [])

    def test_has_manual_trigger(self, workflow):
        """CD workflow should have workflow_dispatch for manual deploys."""
        triggers = workflow.get(True, workflow.get("on", {}))
        assert "workflow_dispatch" in triggers

    def test_does_not_trigger_on_pull_request(self, workflow):
        """CD workflow should NOT trigger on pull requests."""
        triggers = workflow.get(True, workflow.get("on", {}))
        assert "pull_request" not in triggers


class TestCDWorkflowJobs:
    """Verify CD workflow job structure."""

    def test_has_build_job(self, workflow):
        """CD workflow should have a build job."""
        assert "jobs" in workflow
        assert "build" in workflow["jobs"]

    def test_has_deploy_job(self, workflow):
        """CD workflow should have a deploy job."""
        assert "deploy" in workflow["jobs"]

    def test_jobs_run_on_ubuntu_latest(self, workflow):
        """All jobs should run on ubuntu-latest."""
        for job_name, job in workflow["jobs"].items():
            assert job.get("runs-on") == "ubuntu-latest", f"{job_name} should run on ubuntu-latest"


class TestCIGatingViaWorkflowRun:
    """Verify CI gating via workflow_run trigger."""

    def test_build_only_runs_on_ci_success(self, workflow):
        """Build job should only run when CI succeeds (or manual dispatch)."""
        build = workflow["jobs"]["build"]
        if_condition = build.get("if", "")
        # Should check for workflow_run success or manual dispatch
        assert "workflow_run.conclusion" in if_condition or "workflow_dispatch" in if_condition

    def test_build_checks_ci_success_conclusion(self, workflow):
        """Build should check that CI workflow concluded successfully."""
        build = workflow["jobs"]["build"]
        if_condition = build.get("if", "")
        assert "success" in if_condition


class TestBuildJob:
    """Verify Docker build job configuration."""

    def test_build_has_checkout_step(self, workflow):
        """Build job should checkout repository."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        checkout_step = next((s for s in steps if "checkout" in str(s.get("uses", ""))), None)
        assert checkout_step is not None

    def test_build_has_docker_login(self, workflow):
        """Build job should log in to GHCR."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        login_step = next(
            (s for s in steps if "docker/login-action" in str(s.get("uses", ""))), None
        )
        assert login_step is not None
        assert login_step["with"]["registry"] == "ghcr.io"

    def test_build_has_build_push(self, workflow):
        """Build job should use docker/build-push-action."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        build_step = next((s for s in steps if "build-push-action" in str(s.get("uses", ""))), None)
        assert build_step is not None

    def test_build_pushes_image(self, workflow):
        """Build job should push the image."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        build_step = next((s for s in steps if "build-push-action" in str(s.get("uses", ""))), None)
        assert build_step["with"]["push"] is True

    def test_build_uses_root_dockerfile(self, workflow):
        """Build job should use Dockerfile from root."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        build_step = next((s for s in steps if "build-push-action" in str(s.get("uses", ""))), None)
        dockerfile = build_step["with"].get("file", "Dockerfile")
        assert dockerfile in ["./Dockerfile", "Dockerfile"]

    def test_build_has_packages_permission(self, workflow):
        """Build job should have packages write permission for GHCR."""
        build = workflow["jobs"]["build"]
        permissions = build.get("permissions", {})
        assert permissions.get("packages") == "write"

    def test_build_outputs_image_digest(self, workflow):
        """Build job should output image digest for tracking."""
        build = workflow["jobs"]["build"]
        outputs = build.get("outputs", {})
        assert "image_digest" in outputs


class TestDeployJob:
    """Verify deployment job configuration."""

    def test_deploy_depends_on_build(self, workflow):
        """Deploy job should depend on build job."""
        deploy = workflow["jobs"]["deploy"]
        assert "needs" in deploy
        needs = deploy["needs"]
        if isinstance(needs, list):
            assert "build" in needs
        else:
            assert needs == "build"

    def test_deploy_uses_ssh_action(self, workflow):
        """Deploy job should use SSH action for DigitalOcean deployment."""
        deploy = workflow["jobs"]["deploy"]
        steps = deploy.get("steps", [])
        ssh_step = next((s for s in steps if "ssh-action" in str(s.get("uses", ""))), None)
        assert ssh_step is not None

    def test_deploy_uses_secrets_for_ssh(self, workflow):
        """Deploy job should use secrets for SSH credentials."""
        deploy = workflow["jobs"]["deploy"]
        steps = deploy.get("steps", [])
        ssh_step = next((s for s in steps if "ssh-action" in str(s.get("uses", ""))), None)
        with_config = ssh_step.get("with", {})
        assert "secrets.DO_HOST" in str(with_config.get("host", ""))
        assert "secrets.DO_USER" in str(with_config.get("username", ""))
        assert "secrets.DO_SSH_KEY" in str(with_config.get("key", ""))

    def test_deploy_script_pulls_image(self, workflow):
        """Deploy script should pull the new Docker image."""
        deploy = workflow["jobs"]["deploy"]
        steps = deploy.get("steps", [])
        ssh_step = next((s for s in steps if "ssh-action" in str(s.get("uses", ""))), None)
        script = ssh_step.get("with", {}).get("script", "")
        assert "docker compose pull" in script

    def test_deploy_script_starts_container(self, workflow):
        """Deploy script should start the container."""
        deploy = workflow["jobs"]["deploy"]
        steps = deploy.get("steps", [])
        ssh_step = next((s for s in steps if "ssh-action" in str(s.get("uses", ""))), None)
        script = ssh_step.get("with", {}).get("script", "")
        assert "docker compose up -d" in script

    def test_deploy_script_has_health_check(self, workflow):
        """Deploy script should verify health after deployment."""
        deploy = workflow["jobs"]["deploy"]
        steps = deploy.get("steps", [])
        ssh_step = next((s for s in steps if "ssh-action" in str(s.get("uses", ""))), None)
        script = ssh_step.get("with", {}).get("script", "")
        assert "docker exec" in script or "health" in script.lower()

    def test_deploy_has_environment(self, workflow):
        """Deploy job should specify production environment."""
        deploy = workflow["jobs"]["deploy"]
        assert deploy.get("environment") == "production"


class TestConcurrencyConfig:
    """Verify concurrency settings."""

    def test_has_concurrency_config(self, workflow):
        """CD workflow should have concurrency configuration."""
        assert "concurrency" in workflow

    def test_cancels_in_progress(self, workflow):
        """CD workflow should cancel in-progress runs."""
        concurrency = workflow["concurrency"]
        assert concurrency.get("cancel-in-progress") is True


class TestAT204CDPipelineDeploys:
    """Acceptance test: AT-204 - CD Pipeline Deploys.

    PRD requirement:
    - Given: Merge to main branch
    - When: GitHub Actions CD runs
    - Then: New image pushed to GHCR
    - And: Container restarted on server
    """

    def test_at204_triggers_after_ci_on_main(self, workflow):
        """AT-204: CD should trigger after CI completes on main branch."""
        triggers = workflow.get(True, workflow.get("on", {}))
        assert "workflow_run" in triggers
        workflow_run = triggers["workflow_run"]
        assert "main" in workflow_run.get("branches", [])

    def test_at204_pushes_to_ghcr(self, workflow):
        """AT-204: CD should push image to GHCR."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        login_step = next(
            (s for s in steps if "docker/login-action" in str(s.get("uses", ""))), None
        )
        assert login_step is not None
        assert login_step["with"]["registry"] == "ghcr.io"

        build_step = next((s for s in steps if "build-push-action" in str(s.get("uses", ""))), None)
        assert build_step is not None
        assert build_step["with"]["push"] is True

    def test_at204_restarts_container(self, workflow):
        """AT-204: CD should restart container on server."""
        deploy = workflow["jobs"]["deploy"]
        steps = deploy.get("steps", [])
        ssh_step = next((s for s in steps if "ssh-action" in str(s.get("uses", ""))), None)
        script = ssh_step.get("with", {}).get("script", "")
        # Should pull and restart
        assert "docker compose pull" in script
        assert "docker compose up" in script


class TestPRD125CDCompliance:
    """Verify compliance with PRD Section 12.5 CD requirements."""

    def test_prd_uses_checkout_v4(self, workflow):
        """PRD 12.5: Should use actions/checkout@v4."""
        all_steps = []
        for job in workflow["jobs"].values():
            all_steps.extend(job.get("steps", []))

        checkout_steps = [s for s in all_steps if "checkout" in str(s.get("uses", ""))]
        for step in checkout_steps:
            uses = step.get("uses", "")
            assert "checkout@v4" in uses or "checkout@v5" in uses

    def test_prd_uses_docker_login_v3(self, workflow):
        """PRD 12.5: Should use docker/login-action@v3."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        login_step = next(
            (s for s in steps if "docker/login-action" in str(s.get("uses", ""))), None
        )
        assert "login-action@v3" in login_step.get("uses", "")

    def test_prd_uses_build_push_v5(self, workflow):
        """PRD 12.5: Should use docker/build-push-action@v5."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        build_step = next((s for s in steps if "build-push-action" in str(s.get("uses", ""))), None)
        assert "build-push-action@v5" in build_step.get("uses", "")

    def test_prd_uses_ssh_action(self, workflow):
        """PRD 12.5: Should use appleboy/ssh-action."""
        deploy = workflow["jobs"]["deploy"]
        steps = deploy.get("steps", [])
        ssh_step = next((s for s in steps if "ssh-action" in str(s.get("uses", ""))), None)
        assert ssh_step is not None
        assert "appleboy/ssh-action" in ssh_step.get("uses", "")


class TestGitHubActionsSecurityBestPractices:
    """Verify GitHub Actions security best practices."""

    def test_no_command_injection_risk(self, workflow_content):
        """No direct interpolation of untrusted inputs in run commands."""
        # These are unsafe patterns - user-controlled inputs directly in run commands
        unsafe_patterns = [
            "github.event.issue.title",
            "github.event.issue.body",
            "github.event.pull_request.title",
            "github.event.pull_request.body",
            "github.event.comment.body",
            "github.head_ref",
        ]
        for pattern in unsafe_patterns:
            assert pattern not in workflow_content, f"Unsafe pattern found: {pattern}"

    def test_uses_pinned_action_versions(self, workflow):
        """Actions should use pinned versions (not @main or @master)."""
        all_steps = []
        for job in workflow["jobs"].values():
            all_steps.extend(job.get("steps", []))

        for step in all_steps:
            uses = step.get("uses", "")
            if uses:
                # Should have @ with version/tag
                assert "@" in uses, f"Action should be pinned: {uses}"
                # Should not use @main or @master
                assert "@main" not in uses.lower(), f"Should not use @main: {uses}"
                assert "@master" not in uses.lower(), f"Should not use @master: {uses}"

    def test_secrets_not_logged(self, workflow_content):
        """Secrets should not be echoed to logs."""
        # Check for patterns that might log secrets
        lines = workflow_content.lower().split("\n")
        for line in lines:
            if "echo" in line:
                assert "secrets." not in line, f"Potential secret logging: {line}"


class TestDockerBuildOptimizations:
    """Verify Docker build optimizations."""

    def test_uses_buildx(self, workflow):
        """Build should use Docker Buildx for advanced features."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        buildx_step = next(
            (s for s in steps if "setup-buildx-action" in str(s.get("uses", ""))), None
        )
        assert buildx_step is not None

    def test_uses_cache(self, workflow):
        """Build should use GitHub Actions cache."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        build_step = next((s for s in steps if "build-push-action" in str(s.get("uses", ""))), None)
        with_config = build_step.get("with", {})
        # Check for GHA cache
        cache_from = with_config.get("cache-from", "")
        assert "gha" in cache_from.lower() or "type=gha" in cache_from

    def test_specifies_platform(self, workflow):
        """Build should specify target platform."""
        build = workflow["jobs"]["build"]
        steps = build.get("steps", [])
        build_step = next((s for s in steps if "build-push-action" in str(s.get("uses", ""))), None)
        with_config = build_step.get("with", {})
        assert "platforms" in with_config


class TestNotifyJob:
    """Verify notification job configuration."""

    def test_notify_job_exists(self, workflow):
        """Notify job should exist."""
        assert "notify" in workflow["jobs"]

    def test_notify_runs_always(self, workflow):
        """Notify job should run regardless of previous job results."""
        notify = workflow["jobs"]["notify"]
        assert notify.get("if") == "always()"

    def test_notify_depends_on_build_and_deploy(self, workflow):
        """Notify job should depend on build and deploy."""
        notify = workflow["jobs"]["notify"]
        needs = notify.get("needs", [])
        assert "build" in needs
        assert "deploy" in needs
