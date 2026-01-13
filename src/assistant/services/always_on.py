"""Always-On Listening Mode for Second Brain.

Phase 3 Feature: Continuous voice input when models are ready.

This module defines the interface for always-on listening mode, which will enable
continuous voice capture without requiring the user to press-and-hold or send
individual voice messages. The feature is deferred until AI models are capable of:

1. Reliable Voice Activity Detection (VAD) - distinguishing speech from background noise
2. Wake Word Detection - recognizing "Hey Brain" or similar activation phrases
3. Context-Aware Activation - understanding when the user is addressing the assistant
4. Continuous Transcription - low-latency streaming transcription for natural conversation
5. Ambient Audio Filtering - ignoring TV, music, and other background conversations

Current Implementation Status:
- This module provides a stub/placeholder interface
- The feature is explicitly marked "When models ready" in PRD Section 6.5
- Actual implementation requires local ML models (e.g., Silero VAD, Picovoice Porcupine)
  or advances in cloud-based real-time streaming APIs

Prerequisites for Full Implementation:
- Low-latency streaming transcription API (sub-500ms)
- Local voice activity detection to minimize API costs
- Wake word detection (local processing for privacy)
- Audio device management (microphone access)
- Background service architecture (daemon or system service)
- Power/resource management (mobile-friendly)

Architecture Notes:
When implemented, the always-on listener would:
1. Run as a background service (not triggered by Telegram)
2. Continuously monitor microphone input
3. Use local VAD to detect speech segments
4. Use local wake word detection to filter for relevant speech
5. Stream relevant audio to Whisper API
6. Process transcriptions through the existing MessageProcessor
7. Send responses via Telegram (or local audio output)
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ListenerState(Enum):
    """State of the always-on listener."""

    NOT_AVAILABLE = "not_available"  # Feature not yet implemented
    STOPPED = "stopped"  # Listener is inactive
    LISTENING = "listening"  # Listening for wake word
    ACTIVATED = "activated"  # Wake word detected, capturing command
    PROCESSING = "processing"  # Processing captured audio
    RESPONDING = "responding"  # Playing/sending response


@dataclass
class ListenerConfig:
    """Configuration for always-on listening mode.

    These settings define the behavior of the listener when implemented.
    Current values are placeholders documenting expected configuration options.
    """

    # Wake word configuration
    wake_word: str = "hey brain"
    wake_word_sensitivity: float = 0.5  # 0.0 (strict) to 1.0 (lenient)

    # Voice activity detection
    vad_threshold: float = 0.5  # Speech probability threshold
    vad_min_speech_duration_ms: int = 250  # Minimum speech duration to capture
    vad_max_speech_duration_ms: int = 30000  # Maximum capture duration (30s)
    vad_speech_pad_ms: int = 300  # Padding around detected speech

    # Silence detection for end-of-utterance
    silence_duration_ms: int = 1500  # Silence indicating end of command

    # Audio settings
    sample_rate: int = 16000  # 16kHz is standard for speech
    channels: int = 1  # Mono
    chunk_size_ms: int = 30  # Audio chunk size for processing

    # Privacy settings
    always_local_vad: bool = True  # Always run VAD locally
    always_local_wake_word: bool = True  # Always run wake word locally
    store_audio_locally: bool = False  # Don't store raw audio by default
    audio_retention_hours: int = 0  # Don't retain by default

    # Resource limits
    max_daily_minutes: int = 120  # Daily transcription limit
    max_continuous_minutes: int = 5  # Max single capture duration


@dataclass
class CaptureResult:
    """Result of capturing speech in always-on mode."""

    text: str
    confidence: int
    capture_started: datetime
    capture_ended: datetime
    duration_seconds: float
    wake_word_detected: bool = True
    vad_segments: list[tuple[float, float]] = field(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        """Check if capture is reliable enough for processing."""
        return self.confidence >= 80 and self.duration_seconds > 0.5


class AlwaysOnListener:
    """Always-on voice listener for continuous capture.

    This class provides the interface for the always-on listening feature.
    Current implementation returns NOT_AVAILABLE status since the feature
    requires models and infrastructure that are not yet ready.

    When models are ready, this class will:
    1. Manage microphone input via sounddevice or pyaudio
    2. Run local VAD (e.g., Silero VAD) for speech detection
    3. Run local wake word detection (e.g., Picovoice Porcupine)
    4. Stream detected speech to transcription API
    5. Route transcriptions to MessageProcessor
    """

    def __init__(
        self,
        config: ListenerConfig | None = None,
        on_capture: Callable[[CaptureResult], None] | None = None,
        on_state_change: Callable[[ListenerState], None] | None = None,
    ):
        """Initialize the listener.

        Args:
            config: Listener configuration
            on_capture: Callback when speech is captured and transcribed
            on_state_change: Callback when listener state changes
        """
        self.config = config or ListenerConfig()
        self.on_capture = on_capture
        self.on_state_change = on_state_change
        self._state = ListenerState.NOT_AVAILABLE

    @property
    def state(self) -> ListenerState:
        """Get current listener state."""
        return self._state

    @property
    def is_available(self) -> bool:
        """Check if always-on listening is available.

        Returns False until the feature is fully implemented with:
        - Local VAD model integration
        - Local wake word detection
        - Streaming transcription support
        - Audio device management
        """
        return False

    def start(self) -> bool:
        """Start the always-on listener.

        Returns:
            True if started successfully, False if not available
        """
        if not self.is_available:
            return False

        # When implemented:
        # 1. Initialize audio input device
        # 2. Load VAD model
        # 3. Load wake word model
        # 4. Start audio processing thread
        # 5. Set state to LISTENING
        return False

    def stop(self) -> None:
        """Stop the always-on listener."""
        if self._state != ListenerState.NOT_AVAILABLE:
            self._set_state(ListenerState.STOPPED)
            # When implemented:
            # 1. Stop audio processing thread
            # 2. Release audio device
            # 3. Cleanup resources

    def _set_state(self, new_state: ListenerState) -> None:
        """Update listener state and notify callback."""
        old_state = self._state
        self._state = new_state
        if self.on_state_change and old_state != new_state:
            self.on_state_change(new_state)

    def get_status(self) -> dict:
        """Get listener status for display.

        Returns:
            Status dictionary with state and availability info
        """
        return {
            "state": self._state.value,
            "is_available": self.is_available,
            "reason": self._get_unavailability_reason(),
            "config": {
                "wake_word": self.config.wake_word,
                "vad_threshold": self.config.vad_threshold,
            },
        }

    def _get_unavailability_reason(self) -> str:
        """Get human-readable reason for unavailability."""
        if self.is_available:
            return ""

        return (
            "Always-on listening mode is not yet available. "
            "This feature requires advances in AI models for reliable "
            "voice activity detection and wake word recognition. "
            "See PRD Section 6.5 for details."
        )


class AlwaysOnListenerNotAvailableError(Exception):
    """Raised when always-on listening is attempted but not available."""

    def __init__(self, message: str | None = None):
        super().__init__(
            message
            or "Always-on listening mode is not yet available. "
            "This feature requires AI model improvements for reliable "
            "voice activity detection and wake word recognition."
        )


# Module-level singleton
_listener_instance: AlwaysOnListener | None = None


def get_always_on_listener(
    config: ListenerConfig | None = None,
) -> AlwaysOnListener:
    """Get the singleton AlwaysOnListener instance.

    Args:
        config: Optional configuration (only used on first call)

    Returns:
        AlwaysOnListener instance
    """
    global _listener_instance
    if _listener_instance is None:
        _listener_instance = AlwaysOnListener(config=config)
    return _listener_instance


def is_always_on_available() -> bool:
    """Check if always-on listening is available.

    Returns:
        False - feature not yet implemented (PRD Section 6.5: "When models ready")
    """
    return False


def get_always_on_status() -> dict:
    """Get always-on listener status.

    Returns:
        Status dictionary with availability and state info
    """
    listener = get_always_on_listener()
    return listener.get_status()
