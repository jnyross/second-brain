"""Whisper transcription service for Second Brain.

Transcribes voice messages using OpenAI's Whisper API.
Returns transcription with confidence score for quality assessment.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import httpx

from assistant.config import settings


@dataclass
class TranscriptionResult:
    """Result of a Whisper transcription."""

    text: str
    confidence: int  # 0-100 score based on avg_logprob
    language: str
    duration_seconds: float
    is_low_confidence: bool  # True if transcription quality is uncertain

    @property
    def needs_review(self) -> bool:
        """Check if transcription needs human review."""
        return self.is_low_confidence or self.confidence < 80


class WhisperTranscriber:
    """Transcribes audio using OpenAI's Whisper API.

    Features:
    - Async transcription with retry logic
    - Confidence scoring from Whisper's log probabilities
    - Support for various audio formats (mp3, mp4, m4a, wav, ogg, webm)
    - Low-confidence detection for flagging uncertain transcriptions
    """

    # OpenAI Whisper API endpoint
    API_URL = "https://api.openai.com/v1/audio/transcriptions"

    # Supported audio formats
    SUPPORTED_FORMATS = frozenset(["mp3", "mp4", "m4a", "wav", "ogg", "webm", "oga"])

    # Default model (whisper-1 is the only currently available model)
    DEFAULT_MODEL = "whisper-1"

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 1.0

    # Confidence thresholds based on avg_logprob
    # Whisper's avg_logprob is typically between -1.0 (good) and -2.0+ (poor)
    LOGPROB_GOOD = -0.5  # Excellent confidence
    LOGPROB_MODERATE = -1.0  # Good confidence
    LOGPROB_LOW = -1.5  # Needs review

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 30.0,
    ):
        """Initialize the transcriber.

        Args:
            api_key: OpenAI API key. Uses settings.openai_api_key if not provided.
            model: Whisper model to use (default: whisper-1)
            timeout_seconds: Request timeout in seconds
        """
        self.api_key = api_key or settings.openai_api_key
        self.model = model
        self.timeout = timeout_seconds

    async def transcribe(
        self,
        audio_data: bytes,
        filename: str = "audio.ogg",
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio data.

        Args:
            audio_data: Raw audio bytes
            filename: Filename with extension for format detection
            language: Optional language hint (ISO 639-1 code, e.g., "en")

        Returns:
            TranscriptionResult with text, confidence, and metadata

        Raises:
            TranscriptionError: If transcription fails after retries
        """
        if not self.api_key:
            raise TranscriptionError("OpenAI API key not configured")

        # Validate format
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension not in self.SUPPORTED_FORMATS:
            raise TranscriptionError(
                f"Unsupported format: {extension}. Supported: {', '.join(self.SUPPORTED_FORMATS)}"
            )

        # Attempt transcription with retries
        last_error: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return await self._transcribe_request(audio_data, filename, language)
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAY_SECONDS * (attempt + 1))

        raise TranscriptionError(
            f"Transcription failed after {self.MAX_RETRIES} attempts: {last_error}"
        )

    async def transcribe_file(
        self,
        file_path: str | Path,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file.

        Args:
            file_path: Path to the audio file
            language: Optional language hint

        Returns:
            TranscriptionResult with text and metadata
        """
        path = Path(file_path)
        if not path.exists():
            raise TranscriptionError(f"File not found: {file_path}")

        audio_data = path.read_bytes()
        return await self.transcribe(audio_data, path.name, language)

    async def _transcribe_request(
        self,
        audio_data: bytes,
        filename: str,
        language: str | None,
    ) -> TranscriptionResult:
        """Make the actual API request."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        # Use verbose_json to get timestamps and confidence
        data = {
            "model": self.model,
            "response_format": "verbose_json",
        }
        if language:
            data["language"] = language

        # Create multipart form data
        files = {
            "file": (filename, audio_data, self._get_content_type(filename)),
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.API_URL,
                headers=headers,
                data=data,
                files=files,
            )

            if response.status_code != 200:
                error_detail = response.text
                raise TranscriptionError(f"API error {response.status_code}: {error_detail}")

            result = response.json()

        # Extract results
        text = result.get("text", "").strip()
        language_detected = result.get("language", "unknown")
        duration = result.get("duration", 0.0)

        # Calculate confidence from segments' avg_logprob
        confidence = self._calculate_confidence(result.get("segments", []))
        is_low_confidence = confidence < 80

        return TranscriptionResult(
            text=text,
            confidence=confidence,
            language=language_detected,
            duration_seconds=duration,
            is_low_confidence=is_low_confidence,
        )

    def _calculate_confidence(self, segments: list[dict]) -> int:
        """Calculate confidence score from segment log probabilities.

        Whisper's avg_logprob indicates transcription confidence:
        - Values closer to 0 indicate higher confidence
        - Values below -1.5 indicate lower confidence

        Returns:
            Confidence score 0-100
        """
        if not segments:
            return 50  # No segments = uncertain

        # Collect avg_logprob from all segments
        logprobs = [seg.get("avg_logprob", -1.0) for seg in segments if "avg_logprob" in seg]

        if not logprobs:
            return 50

        # Calculate average log probability
        avg_logprob = sum(logprobs) / len(logprobs)

        # Convert to 0-100 scale
        # -0.5 or higher = 100, -2.0 or lower = 0
        if avg_logprob >= self.LOGPROB_GOOD:
            return 100
        elif avg_logprob <= -2.0:
            return max(0, int((avg_logprob + 3.0) * 50))  # -3.0 = 0, -2.0 = 50
        else:
            # Linear interpolation between -0.5 and -2.0
            # -0.5 = 100, -2.0 = 50
            normalized = (avg_logprob - (-2.0)) / (self.LOGPROB_GOOD - (-2.0))
            return int(50 + normalized * 50)

    def _get_content_type(self, filename: str) -> str:
        """Get MIME content type for audio file."""
        extension = Path(filename).suffix.lower().lstrip(".")
        content_types = {
            "mp3": "audio/mpeg",
            "mp4": "audio/mp4",
            "m4a": "audio/mp4",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
            "oga": "audio/ogg",
            "webm": "audio/webm",
        }
        return content_types.get(extension, "application/octet-stream")


class TranscriptionError(Exception):
    """Error during transcription."""

    pass


# Convenience function
async def transcribe_audio(
    audio_data: bytes,
    filename: str = "audio.ogg",
    language: str | None = None,
    api_key: str | None = None,
) -> TranscriptionResult:
    """Convenience function to transcribe audio.

    Args:
        audio_data: Raw audio bytes
        filename: Filename with extension for format detection
        language: Optional language hint
        api_key: Optional API key override

    Returns:
        TranscriptionResult with text and metadata
    """
    transcriber = WhisperTranscriber(api_key=api_key)
    return await transcriber.transcribe(audio_data, filename, language)
