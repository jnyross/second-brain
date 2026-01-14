"""Sentry error tracking integration for Second Brain.

This module provides Sentry SDK initialization and context helpers for
production error tracking and alerting.

Usage:
    # Early in application startup (before other imports if possible)
    from assistant.sentry import init_sentry
    init_sentry()

    # In Telegram handlers, add user context
    from assistant.sentry import set_user_context
    set_user_context(chat_id=message.chat.id, username=message.from_user.username)

    # Capture exceptions manually
    from assistant.sentry import capture_exception
    try:
        risky_operation()
    except Exception as e:
        capture_exception(e)
        raise
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

# Sentry SDK is optional - gracefully handle if not installed
try:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    sentry_sdk = None
    LoggingIntegration = None

if TYPE_CHECKING:
    from sentry_sdk._types import Event, Hint

logger = logging.getLogger(__name__)

# Module state
_initialized = False


def init_sentry(
    dsn: str | None = None,
    environment: str = "production",
    release: str | None = None,
    traces_sample_rate: float = 0.1,
    profiles_sample_rate: float = 0.1,
    debug: bool = False,
) -> bool:
    """Initialize Sentry SDK for error tracking.

    Args:
        dsn: Sentry DSN. If None, reads from SENTRY_DSN env var.
             Empty/None DSN disables Sentry (safe for development).
        environment: Environment name (production, staging, development).
        release: Release version. If None, auto-detected from package version.
        traces_sample_rate: Sample rate for performance tracing (0.0-1.0).
        profiles_sample_rate: Sample rate for profiling (0.0-1.0).
        debug: Enable Sentry debug mode for troubleshooting.

    Returns:
        True if Sentry was initialized, False if skipped/unavailable.
    """
    global _initialized

    if _initialized:
        logger.debug("Sentry already initialized")
        return True

    if not SENTRY_AVAILABLE:
        logger.info("Sentry SDK not installed, error tracking disabled")
        return False

    # Get DSN from environment if not provided
    if dsn is None:
        import os

        dsn = os.environ.get("SENTRY_DSN", "")

    # Empty DSN disables Sentry (expected in development)
    if not dsn:
        logger.info("No SENTRY_DSN configured, error tracking disabled")
        return False

    # Auto-detect release version from package
    if release is None:
        try:
            from importlib.metadata import version

            release = f"second-brain@{version('second-brain')}"
        except Exception:
            release = "second-brain@unknown"

    # Configure logging integration to capture errors and warnings
    logging_integration = LoggingIntegration(
        level=logging.INFO,  # Capture INFO and above as breadcrumbs
        event_level=logging.ERROR,  # Send ERROR and above to Sentry
    )

    # Initialize Sentry SDK
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        profiles_sample_rate=profiles_sample_rate,
        debug=debug,
        integrations=[logging_integration],
        # Don't send PII by default
        send_default_pii=False,
        # Attach stacktrace to all messages
        attach_stacktrace=True,
        # Filter out sensitive data
        before_send=_before_send,
    )

    _initialized = True
    logger.info(f"Sentry initialized: environment={environment}, release={release}")
    return True


def _before_send(event: Event, hint: Hint) -> Event | None:
    """Filter/modify events before sending to Sentry.

    This callback allows us to:
    - Remove sensitive data (API keys, tokens)
    - Filter out noisy errors
    - Add custom context
    """
    # Filter out expected/handled exceptions that shouldn't alert
    if "exc_info" in hint:
        exc_type, exc_value, _ = hint["exc_info"]

        # Don't report expected network errors (will retry)
        if exc_type.__name__ in ("TimeoutError", "ConnectionError"):
            return None

        # Don't report user-facing validation errors
        if exc_type.__name__ in ("ValueError", "ValidationError"):
            # Only skip if it's a user input validation
            if "user input" in str(exc_value).lower():
                return None

    # Scrub sensitive data from request/breadcrumbs
    if "request" in event:
        _scrub_dict(cast(dict[str, Any], event["request"]))

    if "breadcrumbs" in event:
        breadcrumbs = cast(dict[str, Any], event["breadcrumbs"])
        if "values" in breadcrumbs:
            for breadcrumb in breadcrumbs["values"]:
                if "data" in breadcrumb:
                    _scrub_dict(breadcrumb["data"])

    return event


def _scrub_dict(data: dict[str, Any]) -> None:
    """Scrub sensitive keys from a dictionary in-place."""
    sensitive_keys = {
        "token",
        "api_key",
        "apikey",
        "secret",
        "password",
        "authorization",
        "bearer",
        "notion_api_key",
        "telegram_bot_token",
        "openai_api_key",
        "sentry_dsn",
        "google_client_secret",
    }

    for key in list(data.keys()):
        if key.lower() in sensitive_keys:
            data[key] = "[REDACTED]"
        elif isinstance(data[key], dict):
            _scrub_dict(data[key])


def set_user_context(
    chat_id: int | str | None = None,
    username: str | None = None,
    user_id: int | str | None = None,
) -> None:
    """Set Sentry user context for the current scope.

    This helps correlate errors with specific users/chats.

    Args:
        chat_id: Telegram chat ID.
        username: Telegram username (without @).
        user_id: Telegram user ID.
    """
    if not SENTRY_AVAILABLE or not _initialized:
        return

    user_data: dict[str, Any] = {}
    if chat_id is not None:
        user_data["id"] = str(chat_id)
    if username is not None:
        user_data["username"] = username
    if user_id is not None:
        user_data["user_id"] = str(user_id)

    if user_data:
        sentry_sdk.set_user(user_data)


def set_tag(key: str, value: str) -> None:
    """Set a tag on the current Sentry scope.

    Tags are indexed and searchable in Sentry.

    Args:
        key: Tag name.
        value: Tag value.
    """
    if not SENTRY_AVAILABLE or not _initialized:
        return

    sentry_sdk.set_tag(key, value)


def set_context(name: str, data: dict[str, Any]) -> None:
    """Set additional context data on the current Sentry scope.

    Args:
        name: Context name (e.g., "notion", "telegram").
        data: Context data dictionary.
    """
    if not SENTRY_AVAILABLE or not _initialized:
        return

    sentry_sdk.set_context(name, data)


def add_breadcrumb(
    message: str,
    category: str = "default",
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    """Add a breadcrumb to help debug issues.

    Breadcrumbs are attached to error events to show what happened
    leading up to an error.

    Args:
        message: Breadcrumb message.
        category: Category for grouping (e.g., "telegram", "notion", "parser").
        level: Log level (debug, info, warning, error, critical).
        data: Additional data to attach.
    """
    if not SENTRY_AVAILABLE or not _initialized:
        return

    sentry_sdk.add_breadcrumb(
        message=message,
        category=category,
        level=level,
        data=data or {},
    )


def capture_exception(exception: BaseException | None = None) -> str | None:
    """Capture an exception and send to Sentry.

    Args:
        exception: The exception to capture. If None, captures current exception.

    Returns:
        Event ID if captured, None otherwise.
    """
    if not SENTRY_AVAILABLE or not _initialized:
        return None

    return sentry_sdk.capture_exception(exception)


def capture_message(message: str, level: str = "info") -> str | None:
    """Capture a message and send to Sentry.

    Args:
        message: Message to send.
        level: Log level (debug, info, warning, error, fatal).

    Returns:
        Event ID if captured, None otherwise.
    """
    if not SENTRY_AVAILABLE or not _initialized:
        return None

    return sentry_sdk.capture_message(message, level=level)


def flush(timeout: float = 2.0) -> None:
    """Flush pending Sentry events.

    Call this before shutdown to ensure all events are sent.

    Args:
        timeout: Seconds to wait for flush to complete.
    """
    if not SENTRY_AVAILABLE or not _initialized:
        return

    sentry_sdk.flush(timeout=timeout)


def is_enabled() -> bool:
    """Check if Sentry is enabled and initialized."""
    return SENTRY_AVAILABLE and _initialized
