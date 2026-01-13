"""Tests for heartbeat service (T-211 - UptimeRobot monitoring)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from assistant.services.heartbeat import (
    DEFAULT_HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    HeartbeatResult,
    HeartbeatService,
    get_heartbeat_service,
    is_heartbeat_configured,
    send_heartbeat,
)

if TYPE_CHECKING:
    pass


class TestHeartbeatResult:
    """Tests for HeartbeatResult dataclass."""

    def test_successful_result(self) -> None:
        """Test successful heartbeat result."""
        result = HeartbeatResult(
            success=True,
            timestamp=datetime(2026, 1, 12, 10, 0, 0),
            response_code=200,
        )
        assert result.success is True
        assert result.response_code == 200
        assert result.error is None
        assert "10:00:00" in result.status_message

    def test_failed_result(self) -> None:
        """Test failed heartbeat result."""
        result = HeartbeatResult(
            success=False,
            timestamp=datetime(2026, 1, 12, 10, 0, 0),
            error="Connection timeout",
        )
        assert result.success is False
        assert result.error == "Connection timeout"
        assert "failed" in result.status_message.lower()

    def test_http_error_result(self) -> None:
        """Test HTTP error result."""
        result = HeartbeatResult(
            success=False,
            timestamp=datetime.now(),
            response_code=503,
            error="HTTP 503",
        )
        assert result.success is False
        assert result.response_code == 503


class TestHeartbeatServiceInit:
    """Tests for HeartbeatService initialization."""

    def test_init_with_url(self) -> None:
        """Test initialization with heartbeat URL."""
        service = HeartbeatService(heartbeat_url="https://heartbeat.uptimerobot.com/test123")
        assert service.is_configured is True
        assert service.interval == DEFAULT_HEARTBEAT_INTERVAL

    def test_init_without_url(self) -> None:
        """Test initialization without heartbeat URL."""
        with patch("assistant.services.heartbeat.settings") as mock_settings:
            mock_settings.uptimerobot_heartbeat_url = ""
            service = HeartbeatService(heartbeat_url=None)
            assert service.is_configured is False

    def test_init_with_custom_interval(self) -> None:
        """Test initialization with custom interval."""
        service = HeartbeatService(
            heartbeat_url="https://heartbeat.uptimerobot.com/test",
            interval=60,
        )
        assert service.interval == 60

    def test_init_from_settings(self) -> None:
        """Test initialization from settings."""
        with patch("assistant.services.heartbeat.settings") as mock_settings:
            mock_settings.uptimerobot_heartbeat_url = "https://heartbeat.uptimerobot.com/settings"
            service = HeartbeatService()
            assert service.is_configured is True


class TestHeartbeatServiceProperties:
    """Tests for HeartbeatService properties."""

    def test_is_running_initially_false(self) -> None:
        """Test that is_running is initially False."""
        service = HeartbeatService(heartbeat_url="https://test.com")
        assert service.is_running is False

    def test_last_result_initially_none(self) -> None:
        """Test that last_result is initially None."""
        service = HeartbeatService(heartbeat_url="https://test.com")
        assert service.last_result is None


class TestHeartbeatServiceSendHeartbeat:
    """Tests for HeartbeatService.send_heartbeat()."""

    @pytest.mark.asyncio
    async def test_send_heartbeat_not_configured(self) -> None:
        """Test send_heartbeat when URL not configured."""
        service = HeartbeatService(heartbeat_url=None)
        # Set the internal URL to None directly
        service._heartbeat_url = None

        result = await service.send_heartbeat()

        assert result.success is False
        assert "not configured" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_heartbeat_success(self) -> None:
        """Test successful heartbeat send."""
        service = HeartbeatService(heartbeat_url="https://heartbeat.uptimerobot.com/test")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(service, "_client", new_callable=AsyncMock) as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)

            result = await service.send_heartbeat()

            assert result.success is True
            assert result.response_code == 200
            assert service.last_result == result

    @pytest.mark.asyncio
    async def test_send_heartbeat_http_error(self) -> None:
        """Test heartbeat with HTTP error response."""
        service = HeartbeatService(heartbeat_url="https://heartbeat.uptimerobot.com/test")

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch.object(service, "_client", new_callable=AsyncMock) as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)

            result = await service.send_heartbeat()

            assert result.success is False
            assert result.response_code == 500

    @pytest.mark.asyncio
    async def test_send_heartbeat_timeout(self) -> None:
        """Test heartbeat with timeout error."""
        service = HeartbeatService(heartbeat_url="https://heartbeat.uptimerobot.com/test")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        service._client = mock_client

        result = await service.send_heartbeat()

        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_heartbeat_request_error(self) -> None:
        """Test heartbeat with request error."""
        service = HeartbeatService(heartbeat_url="https://heartbeat.uptimerobot.com/test")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.RequestError("Connection failed", request=MagicMock())
        )
        service._client = mock_client

        result = await service.send_heartbeat()

        assert result.success is False
        assert "error" in result.error.lower()


class TestHeartbeatServiceStartStop:
    """Tests for HeartbeatService start/stop."""

    @pytest.mark.asyncio
    async def test_start_not_configured(self) -> None:
        """Test start when not configured."""
        service = HeartbeatService(heartbeat_url=None)
        service._heartbeat_url = None

        await service.start()

        # Should not start running when not configured
        assert service.is_running is False

    @pytest.mark.asyncio
    async def test_start_configured(self) -> None:
        """Test start when configured."""
        service = HeartbeatService(
            heartbeat_url="https://heartbeat.uptimerobot.com/test",
            interval=1,  # Short interval for testing
        )

        # Mock the HTTP client
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(service, "_client", new_callable=AsyncMock) as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)

            await service.start()

            # Should be running
            assert service.is_running is True

            # Wait a tiny bit to let it send initial heartbeat
            await asyncio.sleep(0.1)

            # Stop it
            await service.stop()

            assert service.is_running is False

    @pytest.mark.asyncio
    async def test_start_double_start(self) -> None:
        """Test that starting twice doesn't create multiple loops."""
        service = HeartbeatService(
            heartbeat_url="https://heartbeat.uptimerobot.com/test",
            interval=10,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(service, "_client", new_callable=AsyncMock) as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)

            await service.start()
            task1 = service._task

            await service.start()  # Second start
            task2 = service._task

            # Should be same task (not started twice)
            assert task1 is task2

            await service.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self) -> None:
        """Test stop when not running."""
        service = HeartbeatService(heartbeat_url="https://test.com")

        # Should not raise
        await service.stop()

        assert service.is_running is False


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_heartbeat_service_singleton(self) -> None:
        """Test that get_heartbeat_service returns singleton."""
        # Reset module state
        import assistant.services.heartbeat as hb_module

        hb_module._heartbeat_service = None

        service1 = get_heartbeat_service()
        service2 = get_heartbeat_service()

        assert service1 is service2

    @pytest.mark.asyncio
    async def test_send_heartbeat_function(self) -> None:
        """Test send_heartbeat convenience function."""
        import assistant.services.heartbeat as hb_module

        hb_module._heartbeat_service = None

        with patch.object(HeartbeatService, "send_heartbeat", new_callable=AsyncMock) as mock:
            mock.return_value = HeartbeatResult(success=True, timestamp=datetime.now())
            result = await send_heartbeat()
            assert result.success is True

    def test_is_heartbeat_configured_function(self) -> None:
        """Test is_heartbeat_configured function."""
        import assistant.services.heartbeat as hb_module

        # Create service with URL
        hb_module._heartbeat_service = HeartbeatService(
            heartbeat_url="https://heartbeat.uptimerobot.com/test"
        )

        assert is_heartbeat_configured() is True

        # Reset
        hb_module._heartbeat_service = None


class TestConstants:
    """Tests for module constants."""

    def test_default_interval(self) -> None:
        """Test default heartbeat interval."""
        assert DEFAULT_HEARTBEAT_INTERVAL == 300  # 5 minutes

    def test_heartbeat_timeout(self) -> None:
        """Test heartbeat timeout value."""
        assert HEARTBEAT_TIMEOUT == 10.0


class TestT211Acceptance:
    """Acceptance tests for T-211: UptimeRobot monitoring."""

    @pytest.mark.asyncio
    async def test_heartbeat_service_lifecycle(self) -> None:
        """Test complete heartbeat service lifecycle.

        Verifies:
        1. Service can be configured with URL
        2. Heartbeat can be sent successfully
        3. Service tracks last result
        4. Start/stop lifecycle works
        """
        service = HeartbeatService(
            heartbeat_url="https://heartbeat.uptimerobot.com/test",
            interval=60,
        )

        # 1. Verify configuration
        assert service.is_configured is True
        assert service.interval == 60

        # 2. Mock successful heartbeat
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(service, "_client", new_callable=AsyncMock) as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)

            result = await service.send_heartbeat()
            assert result.success is True

            # 3. Verify last result tracking
            assert service.last_result == result
            assert service.last_result.success is True

            # 4. Start and verify running
            await service.start()
            assert service.is_running is True

            # Stop and verify stopped
            await service.stop()
            assert service.is_running is False

    @pytest.mark.asyncio
    async def test_telegram_alert_trigger_scenario(self) -> None:
        """Test scenario that would trigger Telegram alert.

        When heartbeat fails repeatedly, UptimeRobot sends alert.
        We verify the failure is correctly captured.
        """
        service = HeartbeatService(
            heartbeat_url="https://heartbeat.uptimerobot.com/test",
        )

        # Simulate network failure
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Network down"))
        service._client = mock_client

        result = await service.send_heartbeat()

        # Failure should be recorded
        assert result.success is False
        assert "timed out" in result.error.lower()
        assert service.last_result.success is False

        # In real scenario, UptimeRobot would send Telegram alert after
        # multiple missed heartbeats

    def test_configuration_via_environment(self) -> None:
        """Test that configuration can be loaded from environment."""
        from assistant.config import Settings

        # Verify Settings has the expected attributes
        settings = Settings(
            uptimerobot_heartbeat_url="https://heartbeat.uptimerobot.com/env-test",
            uptimerobot_heartbeat_interval=120,
        )

        assert settings.uptimerobot_heartbeat_url == "https://heartbeat.uptimerobot.com/env-test"
        assert settings.uptimerobot_heartbeat_interval == 120
        assert settings.has_uptimerobot is True

    def test_configuration_disabled_by_default(self) -> None:
        """Test that heartbeat is disabled when not configured."""
        from assistant.config import Settings

        settings = Settings(uptimerobot_heartbeat_url="")

        assert settings.has_uptimerobot is False


class TestBotIntegration:
    """Tests for heartbeat integration with Telegram bot."""

    def test_bot_imports_heartbeat_functions(self) -> None:
        """Test that bot module imports heartbeat functions."""
        import importlib

        # Verify the module has the heartbeat imports
        spec = importlib.util.find_spec("assistant.telegram.bot")
        assert spec is not None

        # Read the source to verify imports
        import os

        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src",
            "assistant",
            "telegram",
            "bot.py",
        )

        with open(bot_path) as f:
            content = f.read()

        assert "start_heartbeat" in content
        assert "stop_heartbeat" in content
        assert "from assistant.services.heartbeat import" in content

    def test_bot_start_method_calls_heartbeat(self) -> None:
        """Test that bot start method has heartbeat calls in the code."""
        import os

        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src",
            "assistant",
            "telegram",
            "bot.py",
        )

        with open(bot_path) as f:
            content = f.read()

        # Verify start_heartbeat is called in start method
        assert "await start_heartbeat()" in content
        # Verify stop_heartbeat is called in finally block
        assert "await stop_heartbeat()" in content


class TestDocumentation:
    """Tests for UptimeRobot setup documentation."""

    def test_documentation_exists(self) -> None:
        """Test that setup documentation exists."""
        import os

        docs_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "docs",
            "uptimerobot-setup.md",
        )

        assert os.path.exists(docs_path), f"Documentation not found at {docs_path}"

    def test_documentation_contains_key_sections(self) -> None:
        """Test documentation contains required sections."""
        import os

        docs_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "docs",
            "uptimerobot-setup.md",
        )

        with open(docs_path) as f:
            content = f.read().lower()

        assert "uptimerobot" in content
        assert "heartbeat" in content
        assert "telegram" in content
        assert "setup" in content
        assert "environment" in content
