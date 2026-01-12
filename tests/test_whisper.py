"""Tests for the Whisper transcription service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.services.whisper import (
    TranscriptionError,
    TranscriptionResult,
    WhisperTranscriber,
    transcribe_audio,
)


class TestTranscriptionResult:
    """Tests for TranscriptionResult dataclass."""

    def test_result_creation(self):
        """TranscriptionResult can be created with all fields."""
        result = TranscriptionResult(
            text="Hello world",
            confidence=95,
            language="en",
            duration_seconds=2.5,
            is_low_confidence=False,
        )
        assert result.text == "Hello world"
        assert result.confidence == 95
        assert result.language == "en"
        assert result.duration_seconds == 2.5
        assert result.is_low_confidence is False

    def test_needs_review_high_confidence(self):
        """High confidence should not need review."""
        result = TranscriptionResult(
            text="Test",
            confidence=90,
            language="en",
            duration_seconds=1.0,
            is_low_confidence=False,
        )
        assert result.needs_review is False

    def test_needs_review_low_confidence(self):
        """Low confidence should need review."""
        result = TranscriptionResult(
            text="Test",
            confidence=70,
            language="en",
            duration_seconds=1.0,
            is_low_confidence=True,
        )
        assert result.needs_review is True

    def test_needs_review_confidence_below_80(self):
        """Confidence below 80 should need review."""
        result = TranscriptionResult(
            text="Test",
            confidence=75,
            language="en",
            duration_seconds=1.0,
            is_low_confidence=False,
        )
        assert result.needs_review is True

    def test_needs_review_exactly_80(self):
        """Confidence at exactly 80 should not need review."""
        result = TranscriptionResult(
            text="Test",
            confidence=80,
            language="en",
            duration_seconds=1.0,
            is_low_confidence=False,
        )
        assert result.needs_review is False


class TestWhisperTranscriber:
    """Tests for WhisperTranscriber class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.transcriber = WhisperTranscriber(api_key="test-api-key")
        self.sample_audio = b"\x00" * 1000  # Dummy audio bytes

    # === Initialization Tests ===

    def test_init_with_api_key(self):
        """Transcriber initializes with provided API key."""
        t = WhisperTranscriber(api_key="my-key")
        assert t.api_key == "my-key"

    def test_init_default_model(self):
        """Transcriber uses whisper-1 model by default."""
        t = WhisperTranscriber(api_key="key")
        assert t.model == "whisper-1"

    def test_init_custom_timeout(self):
        """Transcriber accepts custom timeout."""
        t = WhisperTranscriber(api_key="key", timeout_seconds=60.0)
        assert t.timeout == 60.0

    # === Format Validation Tests ===

    @pytest.mark.asyncio
    async def test_unsupported_format_raises_error(self):
        """Unsupported audio format should raise TranscriptionError."""
        with pytest.raises(TranscriptionError) as exc_info:
            await self.transcriber.transcribe(self.sample_audio, "audio.txt")
        assert "Unsupported format" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_supported_formats(self):
        """All documented formats should be supported."""
        supported = ["mp3", "mp4", "m4a", "wav", "ogg", "webm", "oga"]
        for fmt in supported:
            assert fmt in WhisperTranscriber.SUPPORTED_FORMATS

    # === API Error Handling Tests ===

    @pytest.mark.asyncio
    async def test_no_api_key_raises_error(self):
        """Missing API key should raise TranscriptionError."""
        # Explicitly set api_key to empty and override settings fallback
        t = WhisperTranscriber.__new__(WhisperTranscriber)
        t.api_key = ""  # Force empty key
        t.model = "whisper-1"
        t.timeout = 30.0
        with pytest.raises(TranscriptionError) as exc_info:
            await t.transcribe(self.sample_audio, "audio.ogg")
        assert "API key not configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_api_error_response(self):
        """API error response should raise TranscriptionError."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key"

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            with pytest.raises(TranscriptionError) as exc_info:
                await self.transcriber.transcribe(self.sample_audio, "audio.ogg")
            assert "API error 401" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self):
        """Network errors should trigger retries."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Hello",
            "language": "en",
            "duration": 1.0,
            "segments": [{"avg_logprob": -0.3}],
        }

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.TimeoutException("Timeout")
            return mock_response

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = mock_post
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            result = await self.transcriber.transcribe(self.sample_audio, "audio.ogg")
            assert result.text == "Hello"
            assert call_count == 2  # First failed, second succeeded

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Should raise error after max retries exceeded."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = httpx.TimeoutException("Timeout")
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            with pytest.raises(TranscriptionError) as exc_info:
                await self.transcriber.transcribe(self.sample_audio, "audio.ogg")
            assert "failed after 3 attempts" in str(exc_info.value)

    # === Successful Transcription Tests ===

    @pytest.mark.asyncio
    async def test_successful_transcription(self):
        """Successful API response should return TranscriptionResult."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Buy milk tomorrow",
            "language": "en",
            "duration": 2.5,
            "segments": [
                {"avg_logprob": -0.4, "text": "Buy milk"},
                {"avg_logprob": -0.5, "text": "tomorrow"},
            ],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            result = await self.transcriber.transcribe(self.sample_audio, "audio.ogg")

            assert result.text == "Buy milk tomorrow"
            assert result.language == "en"
            assert result.duration_seconds == 2.5
            assert result.confidence >= 90  # High logprob = high confidence

    @pytest.mark.asyncio
    async def test_transcription_with_language_hint(self):
        """Language hint should be passed to API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Bonjour",
            "language": "fr",
            "duration": 1.0,
            "segments": [{"avg_logprob": -0.5}],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            result = await self.transcriber.transcribe(
                self.sample_audio, "audio.mp3", language="fr"
            )

            assert result.language == "fr"
            # Verify language was passed in request
            call_args = mock_instance.post.call_args
            assert "language" in call_args.kwargs.get("data", {})

    # === Confidence Calculation Tests ===

    def test_calculate_confidence_high_logprob(self):
        """High avg_logprob should give high confidence."""
        segments = [{"avg_logprob": -0.3}]
        confidence = self.transcriber._calculate_confidence(segments)
        assert confidence == 100

    def test_calculate_confidence_moderate_logprob(self):
        """Moderate avg_logprob should give moderate confidence."""
        segments = [{"avg_logprob": -1.0}]
        confidence = self.transcriber._calculate_confidence(segments)
        assert 70 <= confidence <= 85

    def test_calculate_confidence_low_logprob(self):
        """Low avg_logprob should give low confidence."""
        segments = [{"avg_logprob": -2.0}]
        confidence = self.transcriber._calculate_confidence(segments)
        assert confidence <= 60

    def test_calculate_confidence_very_low_logprob(self):
        """Very low avg_logprob should give very low confidence."""
        segments = [{"avg_logprob": -3.0}]
        confidence = self.transcriber._calculate_confidence(segments)
        assert confidence == 0

    def test_calculate_confidence_multiple_segments(self):
        """Multiple segments should be averaged."""
        segments = [
            {"avg_logprob": -0.5},
            {"avg_logprob": -1.5},
        ]
        confidence = self.transcriber._calculate_confidence(segments)
        # Average is -1.0, so confidence should be moderate
        assert 70 <= confidence <= 85

    def test_calculate_confidence_empty_segments(self):
        """Empty segments should return uncertain confidence."""
        confidence = self.transcriber._calculate_confidence([])
        assert confidence == 50

    def test_calculate_confidence_no_logprob(self):
        """Segments without avg_logprob should return uncertain confidence."""
        segments = [{"text": "Hello"}]
        confidence = self.transcriber._calculate_confidence(segments)
        assert confidence == 50

    # === Content Type Tests ===

    def test_get_content_type_mp3(self):
        """MP3 files should have audio/mpeg content type."""
        assert self.transcriber._get_content_type("audio.mp3") == "audio/mpeg"

    def test_get_content_type_ogg(self):
        """OGG files should have audio/ogg content type."""
        assert self.transcriber._get_content_type("audio.ogg") == "audio/ogg"

    def test_get_content_type_wav(self):
        """WAV files should have audio/wav content type."""
        assert self.transcriber._get_content_type("audio.wav") == "audio/wav"

    def test_get_content_type_unknown(self):
        """Unknown extensions should default to octet-stream."""
        assert self.transcriber._get_content_type("audio.xyz") == "application/octet-stream"


class TestTranscribeFile:
    """Tests for file-based transcription."""

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        """Non-existent file should raise TranscriptionError."""
        t = WhisperTranscriber(api_key="test-key")
        with pytest.raises(TranscriptionError) as exc_info:
            await t.transcribe_file("/nonexistent/audio.ogg")
        assert "File not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transcribe_file_reads_content(self, tmp_path):
        """transcribe_file should read file and transcribe."""
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"\x00" * 100)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Test transcription",
            "language": "en",
            "duration": 1.0,
            "segments": [{"avg_logprob": -0.5}],
        }

        t = WhisperTranscriber(api_key="test-key")

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            result = await t.transcribe_file(audio_file)
            assert result.text == "Test transcription"


class TestConvenienceFunction:
    """Tests for the transcribe_audio convenience function."""

    @pytest.mark.asyncio
    async def test_transcribe_audio_function(self):
        """Convenience function should work correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Hello",
            "language": "en",
            "duration": 1.0,
            "segments": [{"avg_logprob": -0.5}],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            result = await transcribe_audio(b"\x00" * 100, "audio.ogg", api_key="test-key")
            assert isinstance(result, TranscriptionResult)
            assert result.text == "Hello"


class TestLowConfidenceDetection:
    """Tests for low confidence detection."""

    @pytest.mark.asyncio
    async def test_low_confidence_flag_set(self):
        """Low confidence should set is_low_confidence flag."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "mumble mumble",
            "language": "en",
            "duration": 2.0,
            "segments": [
                {"avg_logprob": -2.5},  # Very low confidence
            ],
        }

        t = WhisperTranscriber(api_key="test-key")

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            result = await t.transcribe(b"\x00" * 100, "audio.ogg")
            assert result.is_low_confidence is True
            assert result.needs_review is True

    @pytest.mark.asyncio
    async def test_high_confidence_flag_not_set(self):
        """High confidence should not set is_low_confidence flag."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Buy milk tomorrow",
            "language": "en",
            "duration": 2.0,
            "segments": [
                {"avg_logprob": -0.3},  # Very high confidence
            ],
        }

        t = WhisperTranscriber(api_key="test-key")

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            result = await t.transcribe(b"\x00" * 100, "audio.ogg")
            assert result.is_low_confidence is False
            assert result.needs_review is False
