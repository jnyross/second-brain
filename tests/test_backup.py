"""Tests for deploy/scripts/backup.sh - backup script with 7-day retention.

T-209: Create backup script
PRD Section 12.9 requirements:
- Backup: ~/.second-brain/queue/, google_token.json, nudges/sent.json
- Storage: /opt/second-brain/backups/ with timestamped tar.gz
- Retention: 7 days (delete older backups)
"""

import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Path to the backup script
SCRIPT_PATH = Path(__file__).parent.parent / "deploy" / "scripts" / "backup.sh"


class TestBackupScriptExists:
    """Test that the backup script exists and is properly structured."""

    def test_script_exists(self):
        """Backup script exists at expected path."""
        assert SCRIPT_PATH.exists(), f"Script not found at {SCRIPT_PATH}"

    def test_script_is_executable(self):
        """Script has executable permissions."""
        assert os.access(SCRIPT_PATH, os.X_OK), "Script is not executable"

    def test_script_has_shebang(self):
        """Script starts with proper shebang."""
        content = SCRIPT_PATH.read_text()
        assert content.startswith("#!/bin/bash"), "Missing bash shebang"

    def test_script_has_set_flags(self):
        """Script uses strict mode (set -euo pipefail)."""
        content = SCRIPT_PATH.read_text()
        assert "set -euo pipefail" in content, "Missing strict mode flags"


class TestBackupHelpOption:
    """Test --help option functionality."""

    def test_help_option(self):
        """--help shows usage information."""
        result = subprocess.run(
            [str(SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--backup-dir" in result.stdout
        assert "--data-dir" in result.stdout
        assert "--retention" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--list" in result.stdout
        assert "--restore" in result.stdout

    def test_short_help_option(self):
        """-h also shows help."""
        result = subprocess.run(
            [str(SCRIPT_PATH), "-h"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--backup-dir" in result.stdout


class TestBackupCommandLineOptions:
    """Test command line option parsing."""

    def test_unknown_option_fails(self):
        """Unknown options cause exit code 2."""
        result = subprocess.run(
            [str(SCRIPT_PATH), "--unknown-option"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "Unknown option" in result.stderr

    def test_backup_dir_option(self):
        """--backup-dir sets backup destination."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert str(backup_dir) in result.stdout

    def test_retention_option(self):
        """--retention sets retention period."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    tmpdir,
                    "--data-dir",
                    tmpdir,
                    "--retention",
                    "14",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "14 days" in result.stdout


class TestBackupDryRunMode:
    """Test --dry-run mode."""

    def test_dry_run_no_changes(self):
        """--dry-run shows what would be done without doing it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "test.txt").write_text("test")

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "DRY-RUN" in result.stdout
            assert not backup_dir.exists()  # Directory not created


class TestBackupCreation:
    """Test backup creation functionality."""

    def test_creates_backup_file(self):
        """Backup creates tar.gz file with timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "queue").mkdir()
            (data_dir / "queue" / "pending.jsonl").write_text('{"id": 1}')

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

            # Check backup file was created
            backups = list(backup_dir.glob("state-*.tar.gz"))
            assert len(backups) == 1
            assert "Backup created successfully" in result.stdout

    def test_backup_contains_queue(self):
        """Backup includes queue/ directory per PRD 12.9."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "queue").mkdir()
            (data_dir / "queue" / "pending.jsonl").write_text('{"test": true}')

            subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
                text=True,
            )

            # Check backup contents
            backup_file = list(backup_dir.glob("state-*.tar.gz"))[0]
            result = subprocess.run(
                ["tar", "-tzf", str(backup_file)],
                capture_output=True,
                text=True,
            )
            assert "queue" in result.stdout
            assert "pending.jsonl" in result.stdout

    def test_backup_contains_google_token(self):
        """Backup includes google_token.json per PRD 12.9."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "google_token.json").write_text('{"token": "xxx"}')

            subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
                text=True,
            )

            backup_file = list(backup_dir.glob("state-*.tar.gz"))[0]
            result = subprocess.run(
                ["tar", "-tzf", str(backup_file)],
                capture_output=True,
                text=True,
            )
            assert "google_token.json" in result.stdout

    def test_backup_contains_nudges(self):
        """Backup includes nudges/sent.json per PRD 12.9."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "nudges").mkdir()
            (data_dir / "nudges" / "sent.json").write_text('{"sent": []}')

            subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
                text=True,
            )

            backup_file = list(backup_dir.glob("state-*.tar.gz"))[0]
            result = subprocess.run(
                ["tar", "-tzf", str(backup_file)],
                capture_output=True,
                text=True,
            )
            assert "nudges" in result.stdout
            assert "sent.json" in result.stdout

    def test_no_files_to_backup(self):
        """Handles empty data directory gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()  # Empty directory

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "No files found to backup" in result.stdout

    def test_data_dir_missing(self):
        """Handles missing data directory gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "nonexistent"

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "does not exist" in result.stdout
            assert "Nothing to backup" in result.stdout


class TestBackupRetention:
    """Test 7-day retention policy per PRD 12.9."""

    def test_deletes_old_backups(self):
        """Deletes backups older than retention period."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "test.txt").write_text("test")

            # Create an "old" backup (we can't easily fake mtime, so just verify the logic)
            old_backup = backup_dir / "state-20200101-000000.tar.gz"
            old_backup.write_bytes(b"old")

            # Manually set old modification time (8 days ago)
            old_time = (datetime.now() - timedelta(days=8)).timestamp()
            os.utime(old_backup, (old_time, old_time))

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                    "--retention",
                    "7",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

            # Old backup should be deleted
            assert not old_backup.exists()
            assert "Deleted" in result.stdout or "old backup" in result.stdout.lower()

    def test_keeps_recent_backups(self):
        """Keeps backups within retention period."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "test.txt").write_text("test")

            # Create a recent backup
            recent_backup = backup_dir / "state-recent.tar.gz"
            recent_backup.write_bytes(b"recent")

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                    "--retention",
                    "7",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

            # Recent backup should still exist
            assert recent_backup.exists()

    def test_default_retention_is_7_days(self):
        """Default retention is 7 days per PRD 12.9."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    tmpdir,
                    "--data-dir",
                    tmpdir,
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
            )
            assert "7 days" in result.stdout


class TestBackupList:
    """Test --list mode."""

    def test_list_no_backups(self):
        """--list handles empty backup directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    tmpdir,
                    "--list",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "No backups found" in result.stdout

    def test_list_shows_backups(self):
        """--list shows available backups."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir)
            (backup_dir / "state-20240101-120000.tar.gz").write_bytes(b"test1")
            (backup_dir / "state-20240102-120000.tar.gz").write_bytes(b"test2")

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--list",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "state-20240101-120000.tar.gz" in result.stdout
            assert "state-20240102-120000.tar.gz" in result.stdout
            assert "Total: 2" in result.stdout

    def test_list_nonexistent_dir(self):
        """--list handles nonexistent backup directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    f"{tmpdir}/nonexistent",
                    "--list",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "No backups found" in result.stdout


class TestBackupRestore:
    """Test --restore functionality."""

    def test_restore_not_found(self):
        """--restore fails gracefully for missing backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    tmpdir,
                    "--restore",
                    "nonexistent.tar.gz",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 1
            assert "not found" in result.stderr.lower()

    def test_restore_dry_run(self):
        """--restore --dry-run shows what would be restored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "test.txt").write_text("original")

            # Create a backup first
            subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
            )

            backup_file = list(backup_dir.glob("state-*.tar.gz"))[0]

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                    "--restore",
                    backup_file.name,
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "DRY-RUN" in result.stdout
            assert "test.txt" in result.stdout


class TestBackupTimestampFormat:
    """Test backup file naming."""

    def test_timestamp_format(self):
        """Backup file uses YYYYMMDD-HHMMSS format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "test.txt").write_text("test")

            subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
            )

            backups = list(backup_dir.glob("state-*.tar.gz"))
            assert len(backups) == 1

            filename = backups[0].name
            # Match state-YYYYMMDD-HHMMSS.tar.gz
            pattern = r"^state-\d{8}-\d{6}\.tar\.gz$"
            assert re.match(pattern, filename), f"Filename {filename} doesn't match pattern"


class TestBackupPRD129Compliance:
    """Test PRD Section 12.9 specific requirements."""

    def test_prd_backup_files_specified(self):
        """Script mentions PRD-specified files in help or logs."""
        content = SCRIPT_PATH.read_text()
        # Script should reference PRD files: queue/, google_token.json, nudges/sent.json
        assert "queue" in content
        assert "google_token" in content or "token" in content
        assert "nudges" in content or "sent.json" in content

    def test_prd_default_backup_path(self):
        """Default backup path matches PRD 12.9 (/opt/second-brain/backups)."""
        content = SCRIPT_PATH.read_text()
        assert "/opt/second-brain/backups" in content

    def test_prd_default_data_path(self):
        """Default data path matches PRD 12.9 (/opt/second-brain/data)."""
        content = SCRIPT_PATH.read_text()
        assert "/opt/second-brain/data" in content

    def test_prd_7_day_retention_default(self):
        """Default retention is 7 days per PRD 12.9."""
        content = SCRIPT_PATH.read_text()
        assert "RETENTION_DAYS" in content
        # Check that 7 is the default
        assert re.search(r"RETENTION_DAYS.*[=:].*7", content)


class TestBackupExitCodes:
    """Test documented exit codes."""

    def test_exit_0_success(self):
        """Exit code 0 on success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "test.txt").write_text("test")

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
            )
            assert result.returncode == 0

    def test_exit_2_invalid_args(self):
        """Exit code 2 on invalid arguments."""
        result = subprocess.run(
            [str(SCRIPT_PATH), "--invalid-option"],
            capture_output=True,
        )
        assert result.returncode == 2


class TestBackupEnvironmentVariables:
    """Test environment variable support."""

    def test_backup_dir_env_var(self):
        """BACKUP_DIR environment variable is respected."""
        content = SCRIPT_PATH.read_text()
        assert "BACKUP_DIR" in content
        assert re.search(r"BACKUP_DIR.*\$\{BACKUP_DIR:-", content)

    def test_data_dir_env_var(self):
        """DATA_DIR environment variable is respected."""
        content = SCRIPT_PATH.read_text()
        assert "DATA_DIR" in content
        assert re.search(r"DATA_DIR.*\$\{DATA_DIR:-", content)

    def test_retention_days_env_var(self):
        """RETENTION_DAYS environment variable is respected."""
        content = SCRIPT_PATH.read_text()
        assert "RETENTION_DAYS" in content


class TestT209AcceptanceTests:
    """Acceptance tests for T-209: Create backup script."""

    def test_complete_backup_workflow(self):
        """Full backup workflow: create backup, list, verify contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            data_dir = Path(tmpdir) / "data"

            # Create PRD-specified data structure
            data_dir.mkdir()
            (data_dir / "queue").mkdir()
            (data_dir / "queue" / "pending.jsonl").write_text('{"id": "test-1"}\n')
            (data_dir / "google_token.json").write_text('{"access_token": "xxx"}')
            (data_dir / "nudges").mkdir()
            (data_dir / "nudges" / "sent.json").write_text('{"sent": ["id1", "id2"]}')

            # Create backup
            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "Backup created successfully" in result.stdout

            # List backups
            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--list",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "Total: 1" in result.stdout

            # Verify backup contents
            backup_file = list(backup_dir.glob("state-*.tar.gz"))[0]
            result = subprocess.run(
                ["tar", "-tzf", str(backup_file)],
                capture_output=True,
                text=True,
            )
            assert "queue" in result.stdout
            assert "pending.jsonl" in result.stdout
            assert "google_token.json" in result.stdout
            assert "nudges" in result.stdout
            assert "sent.json" in result.stdout

    def test_retention_policy_enforced(self):
        """7-day retention policy deletes old backups."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "test.txt").write_text("test")

            # Create "old" backups (8+ days old)
            for i in range(3):
                old_backup = backup_dir / f"state-old-{i}.tar.gz"
                old_backup.write_bytes(b"old data")
                old_time = (datetime.now() - timedelta(days=10 + i)).timestamp()
                os.utime(old_backup, (old_time, old_time))

            # Create "recent" backup (1 day old)
            recent_backup = backup_dir / "state-recent.tar.gz"
            recent_backup.write_bytes(b"recent data")
            recent_time = (datetime.now() - timedelta(days=1)).timestamp()
            os.utime(recent_backup, (recent_time, recent_time))

            # Run backup (should clean up old ones)
            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--backup-dir",
                    str(backup_dir),
                    "--data-dir",
                    str(data_dir),
                    "--retention",
                    "7",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

            # Old backups should be gone
            remaining = list(backup_dir.glob("state-*.tar.gz"))
            remaining_names = [f.name for f in remaining]

            # Should have: new backup + recent backup
            assert len(remaining) == 2
            assert "state-recent.tar.gz" in remaining_names
            for old_name in ["state-old-0.tar.gz", "state-old-1.tar.gz", "state-old-2.tar.gz"]:
                assert old_name not in remaining_names
