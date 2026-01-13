"""Heartbeat service for UptimeRobot monitoring (T-211).

This module provides heartbeat functionality for external uptime monitoring.
Instead of exposing an HTTP endpoint (which would require port opening and
firewall changes for a Telegram long-polling bot), this uses UptimeRobot's
"Heartbeat" monitoring type where the bot pushes a signal periodically.

Usage:
    1. Create a "Heartbeat" monitor in UptimeRobot dashboard
    2. Copy the heartbeat URL (format: https://heartbeat.uptimerobot.com/xxx)
    3. Set UPTIMEROBOT_HEARTBEAT_URL environment variable
    4. Call send_heartbeat() periodically (e.g., every 5 minutes)

The heartbeat is automatically sent on bot startup and periodically thereafter.
If no heartbeat is received within the configured interval, UptimeRobot sends
a Telegram alert (configured in UptimeRobot dashboard).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from assistant.config import settings

logger = logging.getLogger(__name__)

# Default heartbeat interval in seconds (5 minutes)
DEFAULT_HEARTBEAT_INTERVAL = 300

# Timeout for heartbeat request
HEARTBEAT_TIMEOUT = 10.0


@dataclass
class HeartbeatResult:
    """Result of a heartbeat attempt."""

    success: bool
    timestamp: datetime
    response_code: int | None = None
    error: str | None = None

    @property
    def status_message(self) -> str:
        """Human-readable status message."""
        if self.success:
            return f"Heartbeat sent at {self.timestamp.strftime('%H:%M:%S')}"
        return f"Heartbeat failed: {self.error}"


class HeartbeatService:
    """Service for sending heartbeats to UptimeRobot.

    UptimeRobot's Heartbeat monitoring expects periodic HTTP GET requests
    to a unique URL. If no request is received within the configured interval,
    UptimeRobot marks the monitor as DOWN and sends alerts.

    Advantages over HTTP endpoint monitoring:
    - No ports need to be opened
    - Works behind firewalls and NAT
    - No additional web server required
    - Simpler Docker/security configuration
    """

    def __init__(
        self,
        heartbeat_url: str | None = None,
        interval: int = DEFAULT_HEARTBEAT_INTERVAL,
    ):
        """Initialize heartbeat service.

        Args:
            heartbeat_url: UptimeRobot heartbeat URL (or from settings)
            interval: Seconds between heartbeats (default 300 = 5 min)
        """
        self._heartbeat_url = heartbeat_url or getattr(
            settings, "uptimerobot_heartbeat_url", None
        )
        self._interval = interval
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_result: HeartbeatResult | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """Check if heartbeat URL is configured."""
        return bool(self._heartbeat_url)

    @property
    def is_running(self) -> bool:
        """Check if heartbeat loop is running."""
        return self._running

    @property
    def last_result(self) -> HeartbeatResult | None:
        """Get the last heartbeat result."""
        return self._last_result

    @property
    def interval(self) -> int:
        """Get heartbeat interval in seconds."""
        return self._interval

    async def send_heartbeat(self) -> HeartbeatResult:
        """Send a single heartbeat to UptimeRobot.

        Returns:
            HeartbeatResult with success status and details
        """
        if not self._heartbeat_url:
            return HeartbeatResult(
                success=False,
                timestamp=datetime.now(),
                error="Heartbeat URL not configured",
            )

        try:
            if self._client is None:
                self._client = httpx.AsyncClient()

            response = await self._client.get(
                self._heartbeat_url,
                timeout=HEARTBEAT_TIMEOUT,
                follow_redirects=True,
            )

            result = HeartbeatResult(
                success=response.status_code == 200,
                timestamp=datetime.now(),
                response_code=response.status_code,
                error=None if response.status_code == 200 else f"HTTP {response.status_code}",
            )

            self._last_result = result

            if result.success:
                logger.debug("Heartbeat sent successfully")
            else:
                logger.warning(f"Heartbeat failed: HTTP {response.status_code}")

            return result

        except httpx.TimeoutException:
            result = HeartbeatResult(
                success=False,
                timestamp=datetime.now(),
                error="Request timed out",
            )
            self._last_result = result
            logger.warning("Heartbeat failed: timeout")
            return result

        except httpx.RequestError as e:
            result = HeartbeatResult(
                success=False,
                timestamp=datetime.now(),
                error=f"Request error: {e}",
            )
            self._last_result = result
            logger.warning(f"Heartbeat failed: {e}")
            return result

    async def start(self) -> None:
        """Start the heartbeat loop.

        Sends an immediate heartbeat, then continues at the configured interval.
        """
        if not self.is_configured:
            logger.info("Heartbeat monitoring not configured (UPTIMEROBOT_HEARTBEAT_URL not set)")
            return

        if self._running:
            logger.warning("Heartbeat loop already running")
            return

        self._running = True
        logger.info(f"Starting heartbeat loop (interval: {self._interval}s)")

        # Send initial heartbeat immediately
        await self.send_heartbeat()

        # Start background loop
        self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop the heartbeat loop."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._client:
            await self._client.aclose()
            self._client = None

        logger.info("Heartbeat loop stopped")

    async def _heartbeat_loop(self) -> None:
        """Background loop that sends heartbeats periodically."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                if self._running:  # Check again after sleep
                    await self.send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                # Continue running even if one heartbeat fails


# Module-level singleton for convenience
_heartbeat_service: HeartbeatService | None = None


def get_heartbeat_service() -> HeartbeatService:
    """Get or create the heartbeat service singleton."""
    global _heartbeat_service
    if _heartbeat_service is None:
        _heartbeat_service = HeartbeatService()
    return _heartbeat_service


async def send_heartbeat() -> HeartbeatResult:
    """Send a single heartbeat (convenience function)."""
    return await get_heartbeat_service().send_heartbeat()


async def start_heartbeat() -> None:
    """Start the heartbeat loop (convenience function)."""
    await get_heartbeat_service().start()


async def stop_heartbeat() -> None:
    """Stop the heartbeat loop (convenience function)."""
    await get_heartbeat_service().stop()


def is_heartbeat_configured() -> bool:
    """Check if heartbeat monitoring is configured."""
    return get_heartbeat_service().is_configured
