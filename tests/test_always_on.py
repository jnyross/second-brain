"""Tests for Always-On Listening Mode (T-131).

This module tests the stub/placeholder interface for always-on listening.
The feature is explicitly marked "When models ready" in PRD Section 6.5
and is not yet fully implemented.

Tests verify:
1. Interface is properly defined and documented
2. Availability correctly returns False until models are ready
3. Configuration options are properly structured
4. State machine is correctly defined
5. Module exports work correctly
"""

from datetime import datetime


class TestListenerState:
    """Tests for ListenerState enum."""

    def test_has_not_available_state(self):
        """State enum includes NOT_AVAILABLE for feature not ready."""
        from assistant.services.always_on import ListenerState

        assert ListenerState.NOT_AVAILABLE.value == "not_available"

    def test_has_stopped_state(self):
        """State enum includes STOPPED for inactive listener."""
        from assistant.services.always_on import ListenerState

        assert ListenerState.STOPPED.value == "stopped"

    def test_has_listening_state(self):
        """State enum includes LISTENING for wake word detection."""
        from assistant.services.always_on import ListenerState

        assert ListenerState.LISTENING.value == "listening"

    def test_has_activated_state(self):
        """State enum includes ACTIVATED for command capture."""
        from assistant.services.always_on import ListenerState

        assert ListenerState.ACTIVATED.value == "activated"

    def test_has_processing_state(self):
        """State enum includes PROCESSING for audio processing."""
        from assistant.services.always_on import ListenerState

        assert ListenerState.PROCESSING.value == "processing"

    def test_has_responding_state(self):
        """State enum includes RESPONDING for response delivery."""
        from assistant.services.always_on import ListenerState

        assert ListenerState.RESPONDING.value == "responding"


class TestListenerConfig:
    """Tests for ListenerConfig dataclass."""

    def test_default_wake_word(self):
        """Default wake word is 'hey brain'."""
        from assistant.services.always_on import ListenerConfig

        config = ListenerConfig()
        assert config.wake_word == "hey brain"

    def test_default_vad_threshold(self):
        """Default VAD threshold is 0.5."""
        from assistant.services.always_on import ListenerConfig

        config = ListenerConfig()
        assert config.vad_threshold == 0.5

    def test_default_sample_rate(self):
        """Default sample rate is 16kHz (speech standard)."""
        from assistant.services.always_on import ListenerConfig

        config = ListenerConfig()
        assert config.sample_rate == 16000

    def test_default_channels(self):
        """Default is mono audio."""
        from assistant.services.always_on import ListenerConfig

        config = ListenerConfig()
        assert config.channels == 1

    def test_privacy_defaults(self):
        """Privacy settings default to local processing and no storage."""
        from assistant.services.always_on import ListenerConfig

        config = ListenerConfig()
        assert config.always_local_vad is True
        assert config.always_local_wake_word is True
        assert config.store_audio_locally is False
        assert config.audio_retention_hours == 0

    def test_resource_limits(self):
        """Resource limits are reasonable defaults."""
        from assistant.services.always_on import ListenerConfig

        config = ListenerConfig()
        assert config.max_daily_minutes == 120  # 2 hours
        assert config.max_continuous_minutes == 5

    def test_custom_config(self):
        """Custom configuration is respected."""
        from assistant.services.always_on import ListenerConfig

        config = ListenerConfig(
            wake_word="hey assistant",
            vad_threshold=0.7,
            sample_rate=44100,
        )
        assert config.wake_word == "hey assistant"
        assert config.vad_threshold == 0.7
        assert config.sample_rate == 44100


class TestCaptureResult:
    """Tests for CaptureResult dataclass."""

    def test_capture_result_creation(self):
        """CaptureResult can be created with required fields."""
        from assistant.services.always_on import CaptureResult

        now = datetime.now()
        result = CaptureResult(
            text="Buy milk tomorrow",
            confidence=90,
            capture_started=now,
            capture_ended=now,
            duration_seconds=1.5,
        )
        assert result.text == "Buy milk tomorrow"
        assert result.confidence == 90
        assert result.duration_seconds == 1.5

    def test_is_reliable_high_confidence(self):
        """High confidence with sufficient duration is reliable."""
        from assistant.services.always_on import CaptureResult

        now = datetime.now()
        result = CaptureResult(
            text="Call dentist",
            confidence=85,
            capture_started=now,
            capture_ended=now,
            duration_seconds=1.0,
        )
        assert result.is_reliable is True

    def test_is_reliable_low_confidence(self):
        """Low confidence is not reliable."""
        from assistant.services.always_on import CaptureResult

        now = datetime.now()
        result = CaptureResult(
            text="...",
            confidence=50,
            capture_started=now,
            capture_ended=now,
            duration_seconds=2.0,
        )
        assert result.is_reliable is False

    def test_is_reliable_short_duration(self):
        """Very short duration is not reliable."""
        from assistant.services.always_on import CaptureResult

        now = datetime.now()
        result = CaptureResult(
            text="hi",
            confidence=95,
            capture_started=now,
            capture_ended=now,
            duration_seconds=0.3,  # Less than 0.5s threshold
        )
        assert result.is_reliable is False


class TestAlwaysOnListener:
    """Tests for AlwaysOnListener class."""

    def test_listener_creation(self):
        """AlwaysOnListener can be created."""
        from assistant.services.always_on import AlwaysOnListener

        listener = AlwaysOnListener()
        assert listener is not None

    def test_listener_with_config(self):
        """AlwaysOnListener accepts custom config."""
        from assistant.services.always_on import AlwaysOnListener, ListenerConfig

        config = ListenerConfig(wake_word="hey test")
        listener = AlwaysOnListener(config=config)
        assert listener.config.wake_word == "hey test"

    def test_is_not_available(self):
        """Listener is not available until models are ready (PRD 6.5)."""
        from assistant.services.always_on import AlwaysOnListener

        listener = AlwaysOnListener()
        assert listener.is_available is False

    def test_initial_state_is_not_available(self):
        """Initial state is NOT_AVAILABLE."""
        from assistant.services.always_on import AlwaysOnListener, ListenerState

        listener = AlwaysOnListener()
        assert listener.state == ListenerState.NOT_AVAILABLE

    def test_start_returns_false_when_not_available(self):
        """Start returns False when feature is not available."""
        from assistant.services.always_on import AlwaysOnListener

        listener = AlwaysOnListener()
        result = listener.start()
        assert result is False

    def test_stop_does_not_crash(self):
        """Stop can be called safely even when not started."""
        from assistant.services.always_on import AlwaysOnListener

        listener = AlwaysOnListener()
        listener.stop()  # Should not raise

    def test_get_status(self):
        """Get status returns availability info."""
        from assistant.services.always_on import AlwaysOnListener

        listener = AlwaysOnListener()
        status = listener.get_status()

        assert status["state"] == "not_available"
        assert status["is_available"] is False
        assert "PRD Section 6.5" in status["reason"]
        assert "wake_word" in status["config"]

    def test_callbacks_can_be_set(self):
        """Callbacks can be configured."""
        from assistant.services.always_on import AlwaysOnListener, CaptureResult

        capture_results: list[CaptureResult] = []
        state_changes: list[str] = []

        listener = AlwaysOnListener(
            on_capture=lambda r: capture_results.append(r),
            on_state_change=lambda s: state_changes.append(s.value),
        )
        assert listener.on_capture is not None
        assert listener.on_state_change is not None


class TestAlwaysOnListenerNotAvailableError:
    """Tests for AlwaysOnListenerNotAvailableError exception."""

    def test_exception_with_default_message(self):
        """Exception has descriptive default message."""
        from assistant.services.always_on import AlwaysOnListenerNotAvailableError

        exc = AlwaysOnListenerNotAvailableError()
        assert "not yet available" in str(exc)
        assert "voice activity detection" in str(exc)

    def test_exception_with_custom_message(self):
        """Exception accepts custom message."""
        from assistant.services.always_on import AlwaysOnListenerNotAvailableError

        exc = AlwaysOnListenerNotAvailableError("Custom reason")
        assert str(exc) == "Custom reason"


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_always_on_listener_returns_singleton(self):
        """get_always_on_listener returns singleton instance."""
        from assistant.services.always_on import get_always_on_listener

        listener1 = get_always_on_listener()
        listener2 = get_always_on_listener()
        assert listener1 is listener2

    def test_is_always_on_available_returns_false(self):
        """is_always_on_available returns False (PRD 6.5)."""
        from assistant.services.always_on import is_always_on_available

        assert is_always_on_available() is False

    def test_get_always_on_status_returns_dict(self):
        """get_always_on_status returns status dictionary."""
        from assistant.services.always_on import get_always_on_status

        status = get_always_on_status()
        assert isinstance(status, dict)
        assert "state" in status
        assert "is_available" in status


class TestModuleExports:
    """Tests for module exports via services.__init__."""

    def test_exports_listener_state(self):
        """ListenerState is exported from services."""
        from assistant.services import ListenerState

        assert ListenerState.NOT_AVAILABLE is not None

    def test_exports_listener_config(self):
        """ListenerConfig is exported from services."""
        from assistant.services import ListenerConfig

        config = ListenerConfig()
        assert config.wake_word == "hey brain"

    def test_exports_always_on_listener(self):
        """AlwaysOnListener is exported from services."""
        from assistant.services import AlwaysOnListener

        listener = AlwaysOnListener()
        assert listener.is_available is False

    def test_exports_capture_result(self):
        """CaptureResult is exported from services."""
        from assistant.services import CaptureResult

        assert CaptureResult is not None

    def test_exports_convenience_functions(self):
        """Convenience functions are exported from services."""
        from assistant.services import (
            get_always_on_listener,
            get_always_on_status,
            is_always_on_available,
        )

        assert is_always_on_available() is False
        assert isinstance(get_always_on_status(), dict)
        assert get_always_on_listener() is not None


class TestPRDSection65Compliance:
    """Tests verifying PRD Section 6.5 compliance."""

    def test_feature_marked_as_future(self):
        """Feature documentation references PRD Section 6.5."""
        from assistant.services import always_on

        docstring = always_on.__doc__
        assert "Phase 3" in docstring
        assert "models are ready" in docstring.lower()

    def test_unavailability_reason_references_prd(self):
        """Unavailability reason references PRD for context."""
        from assistant.services.always_on import AlwaysOnListener

        listener = AlwaysOnListener()
        status = listener.get_status()
        assert "PRD Section 6.5" in status["reason"]

    def test_prerequisites_documented(self):
        """Prerequisites for implementation are documented."""
        from assistant.services import always_on

        docstring = always_on.__doc__
        # Key prerequisites should be mentioned
        assert "Voice Activity Detection" in docstring or "VAD" in docstring
        assert "Wake Word" in docstring.lower() or "wake word" in docstring
        assert "streaming" in docstring.lower()

    def test_privacy_first_design(self):
        """Default config prioritizes privacy (local processing)."""
        from assistant.services.always_on import ListenerConfig

        config = ListenerConfig()
        # Privacy settings default to local processing
        assert config.always_local_vad is True
        assert config.always_local_wake_word is True
        assert config.store_audio_locally is False


class TestT131AcceptanceTest:
    """Acceptance tests for T-131: Always-on listening mode."""

    def test_interface_defined(self):
        """Interface for always-on listening is defined."""
        from assistant.services.always_on import (
            AlwaysOnListener,
            ListenerConfig,
            ListenerState,
        )

        # Classes exist and can be instantiated
        config = ListenerConfig()
        listener = AlwaysOnListener(config=config)

        assert listener.state == ListenerState.NOT_AVAILABLE
        assert listener.config.wake_word == "hey brain"

    def test_not_available_until_models_ready(self):
        """Feature correctly reports as not available (PRD 6.5)."""
        from assistant.services.always_on import is_always_on_available

        # PRD 6.5: "When models are more capable: Always-on listening mode"
        assert is_always_on_available() is False

    def test_status_provides_context(self):
        """Status provides helpful context about unavailability."""
        from assistant.services.always_on import get_always_on_status

        status = get_always_on_status()
        assert "reason" in status
        assert len(status["reason"]) > 50  # Has meaningful explanation

    def test_stub_does_not_block_execution(self):
        """Stub implementation doesn't block or raise unexpected errors."""
        from assistant.services.always_on import get_always_on_listener

        listener = get_always_on_listener()

        # These operations should all be safe even though feature unavailable
        listener.start()  # Returns False, doesn't raise
        listener.stop()  # No-op, doesn't raise
        listener.get_status()  # Returns dict, doesn't raise
