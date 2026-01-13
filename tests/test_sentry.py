"""Tests for Sentry error tracking integration.

These tests verify the Sentry module works correctly both when sentry-sdk
is installed and when it's not (graceful degradation).
"""

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from assistant.sentry import (
    SENTRY_AVAILABLE,
    _before_send,
    _scrub_dict,
    add_breadcrumb,
    capture_exception,
    capture_message,
    flush,
    init_sentry,
    is_enabled,
    set_context,
    set_tag,
    set_user_context,
)


# ============================================================
# Test SDK Availability
# ============================================================


class TestSentryAvailability:
    """Test Sentry SDK availability detection."""

    def test_sentry_available_is_bool(self) -> None:
        """SENTRY_AVAILABLE should be a boolean."""
        assert isinstance(SENTRY_AVAILABLE, bool)

    def test_is_enabled_before_init(self) -> None:
        """is_enabled should return False before initialization."""
        # Reset module state for clean test
        import assistant.sentry

        assistant.sentry._initialized = False
        assert is_enabled() is False


# ============================================================
# Test Initialization (when SDK not available)
# ============================================================


class TestSentryInitNoSDK:
    """Test Sentry initialization when SDK is not available."""

    def setup_method(self) -> None:
        """Reset module state before each test."""
        import assistant.sentry

        assistant.sentry._initialized = False

    def test_init_without_dsn_returns_false(self) -> None:
        """init_sentry without DSN should return False."""
        result = init_sentry(dsn="")
        assert result is False
        assert is_enabled() is False

    def test_init_with_none_dsn_returns_false(self) -> None:
        """init_sentry with None DSN should return False."""
        with patch.dict("os.environ", {"SENTRY_DSN": ""}, clear=False):
            result = init_sentry(dsn=None)
            assert result is False

    def test_init_returns_false_without_sdk(self) -> None:
        """init_sentry should return False when SDK not available."""
        if not SENTRY_AVAILABLE:
            result = init_sentry(dsn="https://test@sentry.io/12345")
            assert result is False


# ============================================================
# Test Data Scrubbing
# ============================================================


class TestDataScrubbing:
    """Test sensitive data scrubbing."""

    def test_scrub_token(self) -> None:
        """Should scrub 'token' key."""
        data = {"token": "secret123", "name": "test"}
        _scrub_dict(data)
        assert data["token"] == "[REDACTED]"
        assert data["name"] == "test"

    def test_scrub_api_key(self) -> None:
        """Should scrub 'api_key' key."""
        data = {"api_key": "sk-abc123", "value": "safe"}
        _scrub_dict(data)
        assert data["api_key"] == "[REDACTED]"

    def test_scrub_password(self) -> None:
        """Should scrub 'password' key."""
        data = {"password": "hunter2", "user": "admin"}
        _scrub_dict(data)
        assert data["password"] == "[REDACTED]"

    def test_scrub_nested_dicts(self) -> None:
        """Should scrub nested dictionaries."""
        data = {
            "outer": {
                "token": "secret",
                "value": "ok",
            },
            "api_key": "also_secret",
        }
        _scrub_dict(data)
        assert data["outer"]["token"] == "[REDACTED]"
        assert data["outer"]["value"] == "ok"
        assert data["api_key"] == "[REDACTED]"

    def test_scrub_case_insensitive(self) -> None:
        """Should scrub keys case-insensitively."""
        data = {"TOKEN": "secret", "ApiKey": "also_secret"}
        _scrub_dict(data)
        # Keys are matched case-insensitively
        assert data["TOKEN"] == "[REDACTED]"

    def test_scrub_specific_keys(self) -> None:
        """Should scrub project-specific sensitive keys."""
        data = {
            "notion_api_key": "ntn_xxx",
            "telegram_bot_token": "12345:ABCdef",
            "openai_api_key": "sk-xxx",
            "sentry_dsn": "https://xxx@sentry.io/123",
        }
        _scrub_dict(data)
        assert all(v == "[REDACTED]" for v in data.values())


# ============================================================
# Test Before Send Filter
# ============================================================


class TestBeforeSend:
    """Test the before_send filter callback."""

    def test_filters_timeout_errors(self) -> None:
        """Should filter out TimeoutError exceptions."""
        event: dict = {"exception": {}}
        hint = {"exc_info": (TimeoutError, TimeoutError("timeout"), None)}

        result = _before_send(event, hint)
        assert result is None

    def test_filters_connection_errors(self) -> None:
        """Should filter out ConnectionError exceptions."""
        event: dict = {"exception": {}}
        hint = {"exc_info": (ConnectionError, ConnectionError("conn"), None)}

        result = _before_send(event, hint)
        assert result is None

    def test_passes_other_exceptions(self) -> None:
        """Should pass through other exceptions."""
        event: dict = {"exception": {}}
        hint = {"exc_info": (RuntimeError, RuntimeError("error"), None)}

        result = _before_send(event, hint)
        assert result is event

    def test_filters_user_input_validation(self) -> None:
        """Should filter validation errors for user input."""
        event: dict = {"exception": {}}
        hint = {"exc_info": (ValueError, ValueError("Invalid user input"), None)}

        result = _before_send(event, hint)
        assert result is None

    def test_passes_other_validation_errors(self) -> None:
        """Should pass validation errors not related to user input."""
        event: dict = {"exception": {}}
        hint = {"exc_info": (ValueError, ValueError("Config error"), None)}

        result = _before_send(event, hint)
        assert result is event

    def test_scrubs_request_data(self) -> None:
        """Should scrub sensitive data from request."""
        event = {
            "request": {
                "headers": {"authorization": "Bearer xxx"},
                "token": "secret",
            }
        }
        hint: dict = {}

        result = _before_send(event, hint)
        assert result is not None
        assert result["request"]["token"] == "[REDACTED]"

    def test_scrubs_breadcrumb_data(self) -> None:
        """Should scrub sensitive data from breadcrumbs."""
        event = {
            "breadcrumbs": {
                "values": [
                    {"data": {"api_key": "secret", "msg": "ok"}},
                    {"data": {"password": "hunter2"}},
                ]
            }
        }
        hint: dict = {}

        result = _before_send(event, hint)
        assert result is not None
        assert result["breadcrumbs"]["values"][0]["data"]["api_key"] == "[REDACTED]"
        assert result["breadcrumbs"]["values"][0]["data"]["msg"] == "ok"
        assert result["breadcrumbs"]["values"][1]["data"]["password"] == "[REDACTED]"


# ============================================================
# Test Context Functions (graceful degradation)
# ============================================================


class TestContextFunctions:
    """Test Sentry context helper functions."""

    def setup_method(self) -> None:
        """Reset module state before each test."""
        import assistant.sentry

        assistant.sentry._initialized = False

    def test_set_user_context_when_not_initialized(self) -> None:
        """set_user_context should be no-op when not initialized."""
        # Should not raise
        set_user_context(chat_id=12345, username="testuser")

    def test_set_tag_when_not_initialized(self) -> None:
        """set_tag should be no-op when not initialized."""
        set_tag("key", "value")

    def test_set_context_when_not_initialized(self) -> None:
        """set_context should be no-op when not initialized."""
        set_context("notion", {"db_id": "xxx"})


# ============================================================
# Test Breadcrumb Functions (graceful degradation)
# ============================================================


class TestBreadcrumbs:
    """Test Sentry breadcrumb functions."""

    def setup_method(self) -> None:
        """Reset module state before each test."""
        import assistant.sentry

        assistant.sentry._initialized = False

    def test_add_breadcrumb_when_not_initialized(self) -> None:
        """add_breadcrumb should be no-op when not initialized."""
        add_breadcrumb("test message", category="test")


# ============================================================
# Test Capture Functions (graceful degradation)
# ============================================================


class TestCaptureFunctions:
    """Test Sentry capture functions."""

    def setup_method(self) -> None:
        """Reset module state before each test."""
        import assistant.sentry

        assistant.sentry._initialized = False

    def test_capture_exception_when_not_initialized(self) -> None:
        """capture_exception should return None when not initialized."""
        result = capture_exception(Exception("test"))
        assert result is None

    def test_capture_message_when_not_initialized(self) -> None:
        """capture_message should return None when not initialized."""
        result = capture_message("test message")
        assert result is None


# ============================================================
# Test Flush Function (graceful degradation)
# ============================================================


class TestFlush:
    """Test Sentry flush function."""

    def setup_method(self) -> None:
        """Reset module state before each test."""
        import assistant.sentry

        assistant.sentry._initialized = False

    def test_flush_when_not_initialized(self) -> None:
        """flush should be no-op when not initialized."""
        flush()  # Should not raise


# ============================================================
# Test Integration with Config
# ============================================================


class TestConfigIntegration:
    """Test Sentry integration with settings."""

    def test_settings_has_sentry_property(self) -> None:
        """Settings should have has_sentry property."""
        from assistant.config import Settings

        # Without DSN
        s1 = Settings(sentry_dsn="")
        assert s1.has_sentry is False

        # With DSN
        s2 = Settings(sentry_dsn="https://xxx@sentry.io/123")
        assert s2.has_sentry is True

    def test_settings_has_sentry_environment(self) -> None:
        """Settings should have sentry_environment field."""
        from assistant.config import Settings

        # Default
        s1 = Settings()
        assert s1.sentry_environment == "production"

        # Custom
        s2 = Settings(sentry_environment="staging")
        assert s2.sentry_environment == "staging"


# ============================================================
# Test CLI Integration
# ============================================================


class TestCLIIntegration:
    """Test Sentry integration in CLI."""

    def test_cli_imports_sentry(self) -> None:
        """CLI should import Sentry functions."""
        from assistant.cli import init_sentry, sentry_flush

        assert init_sentry is not None
        assert sentry_flush is not None


# ============================================================
# Test PRD Compliance
# ============================================================


class TestPRDCompliance:
    """Test compliance with PRD Section 12.8."""

    def test_sentry_in_dependencies(self) -> None:
        """sentry-sdk should be in project dependencies."""
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            config = tomllib.load(f)

        deps = config["project"]["dependencies"]
        assert any("sentry-sdk" in d for d in deps), "sentry-sdk not in dependencies"

    def test_sentry_config_in_settings(self) -> None:
        """Settings should have Sentry configuration fields."""
        from assistant.config import Settings

        s = Settings()
        assert hasattr(s, "sentry_dsn")
        assert hasattr(s, "sentry_environment")
        assert hasattr(s, "has_sentry")

    def test_error_tracking_disabled_by_default(self) -> None:
        """Error tracking should be disabled without DSN (safe for development)."""
        from assistant.config import Settings

        s = Settings()
        assert s.has_sentry is False  # Default is empty DSN


# ============================================================
# Test with SDK mocked (when available)
# ============================================================


@pytest.mark.skipif(not SENTRY_AVAILABLE, reason="sentry-sdk not installed")
class TestSentryWithSDK:
    """Tests that require sentry-sdk to be installed."""

    def setup_method(self) -> None:
        """Reset module state before each test."""
        import assistant.sentry

        assistant.sentry._initialized = False

    def test_init_with_dsn_initializes(self) -> None:
        """init_sentry with DSN should initialize SDK."""
        with patch("assistant.sentry.sentry_sdk") as mock_sentry:
            result = init_sentry(
                dsn="https://test@sentry.io/12345",
                environment="test",
            )
            assert result is True
            assert is_enabled() is True
            mock_sentry.init.assert_called_once()

    def test_set_user_context_when_initialized(self) -> None:
        """set_user_context should call sentry_sdk.set_user when initialized."""
        import assistant.sentry

        assistant.sentry._initialized = True

        with patch("assistant.sentry.sentry_sdk") as mock_sentry:
            set_user_context(chat_id=12345, username="testuser", user_id=67890)
            mock_sentry.set_user.assert_called_once_with(
                {"id": "12345", "username": "testuser", "user_id": "67890"}
            )

    def test_set_tag_when_initialized(self) -> None:
        """set_tag should call sentry_sdk.set_tag when initialized."""
        import assistant.sentry

        assistant.sentry._initialized = True

        with patch("assistant.sentry.sentry_sdk") as mock_sentry:
            set_tag("command", "briefing")
            mock_sentry.set_tag.assert_called_once_with("command", "briefing")

    def test_capture_exception_when_initialized(self) -> None:
        """capture_exception should call sentry_sdk.capture_exception."""
        import assistant.sentry

        assistant.sentry._initialized = True

        with patch("assistant.sentry.sentry_sdk") as mock_sentry:
            mock_sentry.capture_exception.return_value = "event-123"
            exc = Exception("test error")
            result = capture_exception(exc)
            mock_sentry.capture_exception.assert_called_once_with(exc)
            assert result == "event-123"

    def test_flush_when_initialized(self) -> None:
        """flush should call sentry_sdk.flush when initialized."""
        import assistant.sentry

        assistant.sentry._initialized = True

        with patch("assistant.sentry.sentry_sdk") as mock_sentry:
            flush(timeout=5.0)
            mock_sentry.flush.assert_called_once_with(5.0)
