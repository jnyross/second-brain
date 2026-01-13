"""WhatsApp Business Cloud API client.

Provides functionality to send and receive messages via the WhatsApp Business
Cloud API. This is the sending/API side of the integration.

WhatsApp Business Cloud API requires:
1. A Meta Business Account
2. A WhatsApp Business Account
3. A Phone Number ID (the business phone number)
4. An Access Token (from Meta for Developers)

See: https://developers.facebook.com/docs/whatsapp/cloud-api/get-started
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

# WhatsApp Cloud API base URL
WHATSAPP_API_BASE = "https://graph.facebook.com/v18.0"

# Default timeout for API requests
DEFAULT_TIMEOUT = 30.0

# Maximum message length for WhatsApp
MAX_MESSAGE_LENGTH = 4096


class MessageType(str, Enum):
    """Types of WhatsApp messages."""

    TEXT = "text"
    AUDIO = "audio"
    DOCUMENT = "document"
    IMAGE = "image"
    STICKER = "sticker"
    VIDEO = "video"
    LOCATION = "location"
    CONTACTS = "contacts"
    INTERACTIVE = "interactive"
    TEMPLATE = "template"


@dataclass
class WhatsAppMessage:
    """A WhatsApp message."""

    message_id: str
    from_number: str
    timestamp: datetime
    message_type: MessageType
    text: str | None = None
    # Audio message fields
    audio_id: str | None = None
    audio_mime_type: str | None = None
    # Location fields
    latitude: float | None = None
    longitude: float | None = None
    location_name: str | None = None
    location_address: str | None = None
    # Metadata
    context_message_id: str | None = None  # If this is a reply
    is_forwarded: bool = False

    @property
    def has_audio(self) -> bool:
        """Check if this message has audio content."""
        return self.audio_id is not None

    @property
    def has_location(self) -> bool:
        """Check if this message has location content."""
        return self.latitude is not None and self.longitude is not None


@dataclass
class SendResult:
    """Result of sending a WhatsApp message."""

    success: bool
    message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class MediaDownloadResult:
    """Result of downloading media from WhatsApp."""

    success: bool
    content: bytes | None = None
    mime_type: str | None = None
    error_message: str | None = None


class WhatsAppClient:
    """WhatsApp Business Cloud API client.

    Handles sending messages, downloading media, and managing the connection
    to the WhatsApp Business Cloud API.

    Args:
        phone_number_id: The WhatsApp Business Phone Number ID
        access_token: Meta access token with whatsapp_business_messaging permission
        api_version: Graph API version (default: v18.0)

    Example:
        >>> client = WhatsAppClient(
        ...     phone_number_id="123456789",
        ...     access_token="EAABc..."
        ... )
        >>> await client.send_text("1234567890", "Hello!")
    """

    def __init__(
        self,
        phone_number_id: str | None = None,
        access_token: str | None = None,
        api_version: str = "v18.0",
    ):
        # Import settings lazily to avoid circular imports
        from assistant.config import settings

        self.phone_number_id = phone_number_id or settings.whatsapp_phone_number_id
        self.access_token = access_token or settings.whatsapp_access_token
        self.api_version = api_version

        self._base_url = f"https://graph.facebook.com/{api_version}/{self.phone_number_id}"
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """Check if WhatsApp credentials are configured."""
        return bool(self.phone_number_id and self.access_token)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def send_text(
        self,
        to: str,
        text: str,
        reply_to_message_id: str | None = None,
        preview_url: bool = False,
    ) -> SendResult:
        """Send a text message.

        Args:
            to: Recipient phone number (with country code, no + or spaces)
            text: Message text (max 4096 characters)
            reply_to_message_id: Optional message ID to reply to
            preview_url: Whether to show URL previews

        Returns:
            SendResult with success status and message_id if successful
        """
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH - 3] + "..."

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": text,
            },
        }

        if reply_to_message_id:
            payload["context"] = {"message_id": reply_to_message_id}

        return await self._send_message(payload)

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "en",
        components: list | None = None,
    ) -> SendResult:
        """Send a template message.

        Template messages are pre-approved message formats that can be sent
        to users who haven't messaged you in the last 24 hours.

        Args:
            to: Recipient phone number
            template_name: Name of the approved template
            language_code: Template language code
            components: Optional template variable components

        Returns:
            SendResult with success status
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }

        if components:
            payload["template"]["components"] = components

        return await self._send_message(payload)

    async def send_interactive_buttons(
        self,
        to: str,
        body_text: str,
        buttons: list[dict[str, str]],
        header_text: str | None = None,
        footer_text: str | None = None,
    ) -> SendResult:
        """Send an interactive message with buttons.

        Args:
            to: Recipient phone number
            body_text: Main message body
            buttons: List of button dicts with 'id' and 'title' keys (max 3)
            header_text: Optional header text
            footer_text: Optional footer text

        Returns:
            SendResult with success status
        """
        interactive = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]  # Max 3 buttons
                ]
            },
        }

        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}
        if footer_text:
            interactive["footer"] = {"text": footer_text}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }

        return await self._send_message(payload)

    async def send_interactive_list(
        self,
        to: str,
        body_text: str,
        button_text: str,
        sections: list[dict],
        header_text: str | None = None,
        footer_text: str | None = None,
    ) -> SendResult:
        """Send an interactive list message.

        Args:
            to: Recipient phone number
            body_text: Main message body
            button_text: Text on the list button (max 20 chars)
            sections: List of section dicts with 'title' and 'rows'
            header_text: Optional header text
            footer_text: Optional footer text

        Returns:
            SendResult with success status
        """
        interactive = {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text[:20],
                "sections": sections,
            },
        }

        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}
        if footer_text:
            interactive["footer"] = {"text": footer_text}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }

        return await self._send_message(payload)

    async def download_media(self, media_id: str) -> MediaDownloadResult:
        """Download media content by ID.

        WhatsApp media download is a two-step process:
        1. Get the media URL from the media ID
        2. Download the actual content from the URL

        Args:
            media_id: WhatsApp media ID

        Returns:
            MediaDownloadResult with content if successful
        """
        client = await self._get_client()

        try:
            # Step 1: Get media URL
            url_response = await client.get(
                f"https://graph.facebook.com/{self.api_version}/{media_id}",
            )
            url_response.raise_for_status()
            media_url = url_response.json().get("url")

            if not media_url:
                return MediaDownloadResult(
                    success=False,
                    error_message="No media URL in response",
                )

            # Step 2: Download content
            content_response = await client.get(media_url)
            content_response.raise_for_status()

            return MediaDownloadResult(
                success=True,
                content=content_response.content,
                mime_type=content_response.headers.get("content-type"),
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Media download HTTP error: {e}")
            return MediaDownloadResult(
                success=False,
                error_message=f"HTTP {e.response.status_code}: {e.response.text}",
            )
        except Exception as e:
            logger.exception(f"Media download failed: {e}")
            return MediaDownloadResult(
                success=False,
                error_message=str(e),
            )

    async def mark_as_read(self, message_id: str) -> bool:
        """Mark a message as read.

        Args:
            message_id: The WhatsApp message ID to mark as read

        Returns:
            True if successful, False otherwise
        """
        client = await self._get_client()

        try:
            response = await client.post(
                f"{self._base_url}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                },
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to mark message as read: {e}")
            return False

    async def _send_message(self, payload: dict) -> SendResult:
        """Send a message using the WhatsApp API.

        Args:
            payload: The message payload

        Returns:
            SendResult with success status
        """
        client = await self._get_client()

        try:
            response = await client.post(
                f"{self._base_url}/messages",
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            messages = data.get("messages", [])

            if messages:
                return SendResult(
                    success=True,
                    message_id=messages[0].get("id"),
                )
            else:
                return SendResult(
                    success=False,
                    error_message="No message ID in response",
                )

        except httpx.HTTPStatusError as e:
            error_data = {}
            try:
                error_data = e.response.json()
            except Exception:
                pass

            error = error_data.get("error", {})
            logger.error(f"WhatsApp API error: {error}")

            return SendResult(
                success=False,
                error_code=str(error.get("code", e.response.status_code)),
                error_message=error.get("message", e.response.text),
            )

        except Exception as e:
            logger.exception(f"Failed to send WhatsApp message: {e}")
            return SendResult(
                success=False,
                error_message=str(e),
            )


# Module-level singleton
_client: WhatsAppClient | None = None


def get_whatsapp_client() -> WhatsAppClient:
    """Get the shared WhatsApp client instance."""
    global _client
    if _client is None:
        _client = WhatsAppClient()
    return _client


async def send_text(to: str, text: str, **kwargs) -> SendResult:
    """Send a text message using the shared client."""
    return await get_whatsapp_client().send_text(to, text, **kwargs)


async def send_template(to: str, template_name: str, **kwargs) -> SendResult:
    """Send a template message using the shared client."""
    return await get_whatsapp_client().send_template(to, template_name, **kwargs)


def is_whatsapp_available() -> bool:
    """Check if WhatsApp integration is configured."""
    return get_whatsapp_client().is_configured
