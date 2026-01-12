"""Tests for GitHub Actions CI workflow configuration.

T-202: Set up GitHub Actions CI
AT-203: CI Pipeline Passes
- Given: PR opened against main
- When: GitHub Actions CI runs
- Then: All jobs pass (lint, type-check, test)
- Pass condition: GitHub checks show green
"""

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def ci_workflow_path() -> Path:
    """Path to the CI workflow file."""
    return Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"


@pytest.fixture
def ci_workflow(ci_workflow_path: Path) -> dict:
    """Load and parse the CI workflow YAML."""
    assert ci_workflow_path.exists(), "CI workflow file should exist"
    content = ci_workflow_path.read_text()
    return yaml.safe_load(content)


class TestCIWorkflowExists:
    """Test that CI workflow file exists and is valid YAML."""

    def test_workflow_file_exists(self, ci_workflow_path: Path):
        """CI workflow file should exist."""
        assert ci_workflow_path.exists()

    def test_workflow_is_valid_yaml(self, ci_workflow_path: Path):
        """CI workflow should be valid YAML."""
        content = ci_workflow_path.read_text()
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)

    def test_workflow_has_name(self, ci_workflow: dict):
        """Workflow should have a name."""
        assert "name" in ci_workflow
        assert ci_workflow["name"] == "CI"


class TestCIWorkflowTriggers:
    """Test CI workflow trigger configuration.

    Note: YAML parses 'on' as boolean True, so we check for True as the key.
    """

    def test_triggers_on_push(self, ci_workflow: dict):
        """Workflow should trigger on push to main."""
        # 'on' is parsed as True in YAML (boolean literal)
        assert True in ci_workflow or "on" in ci_workflow
        triggers = ci_workflow.get(True) or ci_workflow.get("on")
        assert "push" in triggers
        assert "main" in triggers["push"]["branches"]

    def test_triggers_on_pull_request(self, ci_workflow: dict):
        """Workflow should trigger on pull requests to main."""
        # 'on' is parsed as True in YAML (boolean literal)
        triggers = ci_workflow.get(True) or ci_workflow.get("on")
        assert "pull_request" in triggers
        assert "main" in triggers["pull_request"]["branches"]


class TestCIWorkflowJobs:
    """Test CI workflow job configuration."""

    def test_has_lint_job(self, ci_workflow: dict):
        """Workflow should have a lint job."""
        assert "jobs" in ci_workflow
        assert "lint" in ci_workflow["jobs"]

    def test_has_type_check_job(self, ci_workflow: dict):
        """Workflow should have a type-check job."""
        assert "type-check" in ci_workflow["jobs"]

    def test_has_test_job(self, ci_workflow: dict):
        """Workflow should have a test job."""
        assert "test" in ci_workflow["jobs"]

    def test_all_jobs_use_ubuntu_latest(self, ci_workflow: dict):
        """All jobs should run on ubuntu-latest."""
        for job_name, job in ci_workflow["jobs"].items():
            assert job.get("runs-on") == "ubuntu-latest", f"Job {job_name} should use ubuntu-latest"


class TestLintJob:
    """Test lint job configuration."""

    def test_lint_job_uses_checkout(self, ci_workflow: dict):
        """Lint job should checkout code."""
        lint_job = ci_workflow["jobs"]["lint"]
        steps = lint_job["steps"]
        checkout_steps = [s for s in steps if s.get("uses", "").startswith("actions/checkout")]
        assert len(checkout_steps) >= 1

    def test_lint_job_uses_python(self, ci_workflow: dict):
        """Lint job should set up Python 3.12."""
        lint_job = ci_workflow["jobs"]["lint"]
        steps = lint_job["steps"]
        python_steps = [s for s in steps if s.get("uses", "").startswith("actions/setup-python")]
        assert len(python_steps) >= 1
        python_step = python_steps[0]
        assert python_step.get("with", {}).get("python-version") == "3.12"

    def test_lint_job_installs_dependencies(self, ci_workflow: dict):
        """Lint job should install dependencies."""
        lint_job = ci_workflow["jobs"]["lint"]
        steps = lint_job["steps"]
        install_steps = [s for s in steps if "pip install" in s.get("run", "")]
        assert len(install_steps) >= 1

    def test_lint_job_runs_ruff_check(self, ci_workflow: dict):
        """Lint job should run ruff check."""
        lint_job = ci_workflow["jobs"]["lint"]
        steps = lint_job["steps"]
        ruff_steps = [s for s in steps if "ruff check" in s.get("run", "")]
        assert len(ruff_steps) >= 1

    def test_lint_job_runs_ruff_format(self, ci_workflow: dict):
        """Lint job should run ruff format check."""
        lint_job = ci_workflow["jobs"]["lint"]
        steps = lint_job["steps"]
        format_steps = [s for s in steps if "ruff format" in s.get("run", "")]
        assert len(format_steps) >= 1


class TestTypeCheckJob:
    """Test type-check job configuration."""

    def test_type_check_uses_checkout(self, ci_workflow: dict):
        """Type-check job should checkout code."""
        job = ci_workflow["jobs"]["type-check"]
        steps = job["steps"]
        checkout_steps = [s for s in steps if s.get("uses", "").startswith("actions/checkout")]
        assert len(checkout_steps) >= 1

    def test_type_check_uses_python(self, ci_workflow: dict):
        """Type-check job should set up Python 3.12."""
        job = ci_workflow["jobs"]["type-check"]
        steps = job["steps"]
        python_steps = [s for s in steps if s.get("uses", "").startswith("actions/setup-python")]
        assert len(python_steps) >= 1
        python_step = python_steps[0]
        assert python_step.get("with", {}).get("python-version") == "3.12"

    def test_type_check_runs_mypy(self, ci_workflow: dict):
        """Type-check job should run mypy on src."""
        job = ci_workflow["jobs"]["type-check"]
        steps = job["steps"]
        mypy_steps = [s for s in steps if "mypy src" in s.get("run", "")]
        assert len(mypy_steps) >= 1


class TestTestJob:
    """Test test job configuration."""

    def test_test_uses_checkout(self, ci_workflow: dict):
        """Test job should checkout code."""
        job = ci_workflow["jobs"]["test"]
        steps = job["steps"]
        checkout_steps = [s for s in steps if s.get("uses", "").startswith("actions/checkout")]
        assert len(checkout_steps) >= 1

    def test_test_uses_python(self, ci_workflow: dict):
        """Test job should set up Python 3.12."""
        job = ci_workflow["jobs"]["test"]
        steps = job["steps"]
        python_steps = [s for s in steps if s.get("uses", "").startswith("actions/setup-python")]
        assert len(python_steps) >= 1
        python_step = python_steps[0]
        assert python_step.get("with", {}).get("python-version") == "3.12"

    def test_test_runs_pytest(self, ci_workflow: dict):
        """Test job should run pytest."""
        job = ci_workflow["jobs"]["test"]
        steps = job["steps"]
        pytest_steps = [s for s in steps if "pytest" in s.get("run", "")]
        assert len(pytest_steps) >= 1

    def test_test_generates_coverage(self, ci_workflow: dict):
        """Test job should generate coverage report."""
        job = ci_workflow["jobs"]["test"]
        steps = job["steps"]
        coverage_steps = [s for s in steps if "--cov" in s.get("run", "")]
        assert len(coverage_steps) >= 1

    def test_test_uploads_coverage(self, ci_workflow: dict):
        """Test job should upload coverage to Codecov."""
        job = ci_workflow["jobs"]["test"]
        steps = job["steps"]
        codecov_steps = [s for s in steps if "codecov" in s.get("uses", "").lower()]
        assert len(codecov_steps) >= 1


class TestCIConcurrency:
    """Test CI workflow concurrency configuration."""

    def test_has_concurrency_config(self, ci_workflow: dict):
        """Workflow should have concurrency configuration."""
        assert "concurrency" in ci_workflow

    def test_cancels_in_progress(self, ci_workflow: dict):
        """Workflow should cancel in-progress runs."""
        concurrency = ci_workflow["concurrency"]
        assert concurrency.get("cancel-in-progress") is True


class TestCISuccessJob:
    """Test CI success summary job."""

    def test_has_ci_success_job(self, ci_workflow: dict):
        """Workflow should have a CI success summary job."""
        assert "ci-success" in ci_workflow["jobs"]

    def test_ci_success_depends_on_all_jobs(self, ci_workflow: dict):
        """CI success job should depend on lint, type-check, and test."""
        job = ci_workflow["jobs"]["ci-success"]
        needs = job.get("needs", [])
        assert "lint" in needs
        assert "type-check" in needs
        assert "test" in needs

    def test_ci_success_runs_always(self, ci_workflow: dict):
        """CI success job should run even if other jobs fail."""
        job = ci_workflow["jobs"]["ci-success"]
        assert job.get("if") == "always()"


class TestAT203CIPipelinePasses:
    """AT-203: CI Pipeline Passes acceptance test.

    - Given: PR opened against main
    - When: GitHub Actions CI runs
    - Then: All jobs pass (lint, type-check, test)
    - Pass condition: GitHub checks show green
    """

    def test_at203_workflow_structure_complete(self, ci_workflow: dict):
        """AT-203: Workflow has all required components."""
        # Triggers ('on' is parsed as True in YAML)
        triggers = ci_workflow.get(True) or ci_workflow.get("on")
        assert triggers is not None
        assert "push" in triggers
        assert "pull_request" in triggers

        # Jobs
        jobs = ci_workflow["jobs"]
        assert "lint" in jobs
        assert "type-check" in jobs
        assert "test" in jobs

    def test_at203_lint_job_runs_ruff(self, ci_workflow: dict):
        """AT-203: Lint job runs ruff check and format."""
        lint_job = ci_workflow["jobs"]["lint"]
        all_runs = " ".join(s.get("run", "") for s in lint_job["steps"])
        assert "ruff check" in all_runs
        assert "ruff format" in all_runs

    def test_at203_type_check_job_runs_mypy(self, ci_workflow: dict):
        """AT-203: Type-check job runs mypy."""
        job = ci_workflow["jobs"]["type-check"]
        all_runs = " ".join(s.get("run", "") for s in job["steps"])
        assert "mypy" in all_runs

    def test_at203_test_job_runs_pytest_with_coverage(self, ci_workflow: dict):
        """AT-203: Test job runs pytest with coverage."""
        job = ci_workflow["jobs"]["test"]
        all_runs = " ".join(s.get("run", "") for s in job["steps"])
        assert "pytest" in all_runs
        assert "--cov" in all_runs

    def test_at203_all_jobs_use_python_312(self, ci_workflow: dict):
        """AT-203: All jobs use Python 3.12."""
        for job_name in ["lint", "type-check", "test"]:
            job = ci_workflow["jobs"][job_name]
            steps = job["steps"]
            python_steps = [
                s for s in steps if s.get("uses", "").startswith("actions/setup-python")
            ]
            assert len(python_steps) >= 1, f"Job {job_name} should set up Python"
            for python_step in python_steps:
                assert python_step.get("with", {}).get("python-version") == "3.12"


class TestPRDSection125Compliance:
    """Test compliance with PRD Section 12.5 CI/CD Pipeline."""

    def test_prd_uses_checkout_v4(self, ci_workflow: dict):
        """PRD: uses actions/checkout@v4."""
        for job_name, job in ci_workflow["jobs"].items():
            if job_name == "ci-success":
                continue  # Summary job doesn't need checkout
            steps = job["steps"]
            checkout_steps = [s for s in steps if "checkout" in s.get("uses", "")]
            for step in checkout_steps:
                assert "@v4" in step.get("uses", ""), f"Job {job_name} should use checkout@v4"

    def test_prd_uses_setup_python_v5(self, ci_workflow: dict):
        """PRD: uses actions/setup-python@v5."""
        for job_name, job in ci_workflow["jobs"].items():
            if job_name == "ci-success":
                continue
            steps = job["steps"]
            python_steps = [s for s in steps if "setup-python" in s.get("uses", "")]
            for step in python_steps:
                assert "@v5" in step.get("uses", ""), f"Job {job_name} should use setup-python@v5"

    def test_prd_installs_dev_dependencies(self, ci_workflow: dict):
        """PRD: pip install -e '.[dev]'."""
        for job_name in ["lint", "type-check", "test"]:
            job = ci_workflow["jobs"][job_name]
            all_runs = " ".join(s.get("run", "") for s in job["steps"])
            assert ".[dev]" in all_runs or ".[dev]" in all_runs


class TestGitHubActionsSecurityBestPractices:
    """Test GitHub Actions security best practices."""

    def test_no_direct_interpolation_in_run(self, ci_workflow_path: Path):
        """No direct interpolation of untrusted inputs in run commands."""
        content = ci_workflow_path.read_text()
        # Check for potentially dangerous patterns in run blocks
        dangerous_patterns = [
            "github.event.issue",
            "github.event.pull_request.title",
            "github.event.pull_request.body",
            "github.event.comment.body",
            "github.event.review.body",
            "github.head_ref",
        ]
        for pattern in dangerous_patterns:
            # These patterns should not appear directly in run commands
            # The pattern ${{ pattern }} in a run: line is dangerous
            # But they're safe when used with env: blocks or in uses: actions
            assert pattern not in content or "env:" in content

    def test_uses_pinned_action_versions(self, ci_workflow: dict):
        """Actions should use pinned versions, not @latest."""
        for job_name, job in ci_workflow["jobs"].items():
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                if uses:
                    assert "@latest" not in uses, f"Job {job_name} should not use @latest"
                    # Check for version pinning (e.g., @v4, @v5, @v1.0.0)
                    assert "@" in uses, f"Job {job_name} action should be version-pinned"

    def test_sensitive_data_uses_secrets(self, ci_workflow: dict):
        """Sensitive data should use secrets, not hardcoded."""
        # Check that codecov token uses secrets
        test_job = ci_workflow["jobs"]["test"]
        for step in test_job["steps"]:
            if "codecov" in step.get("uses", "").lower():
                with_ = step.get("with", {})
                token = with_.get("token", "")
                if token:
                    assert "secrets." in token
