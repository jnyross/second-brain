"""WhatsApp Business Cloud API webhook handler.

This module handles incoming webhook events from the WhatsApp Business Cloud API.
WhatsApp uses webhooks to notify your server about incoming messages and delivery
status updates.

Webhook Setup:
1. Create a webhook endpoint at your server (e.g., /webhook/whatsapp)
2. Configure the webhook URL in Meta Developer Console
3. Verify the webhook with the challenge/response handshake
4. Process incoming message events

See: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components
"""

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from assistant.whatsapp.client import MessageType, WhatsAppMessage

logger = logging.getLogger(__name__)


class WebhookEventType(str, Enum):
    """Types of webhook events."""

    MESSAGE = "message"
    STATUS = "status"
    ERROR = "error"
    UNKNOWN = "unknown"


class MessageStatus(str, Enum):
    """Message delivery status values."""

    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


@dataclass
class StatusUpdate:
    """A message status update from webhook."""

    message_id: str
    status: MessageStatus
    timestamp: datetime
    recipient_id: str
    # Error info if status is failed
    error_code: str | None = None
    error_title: str | None = None


@dataclass
class WebhookEvent:
    """A parsed webhook event."""

    event_type: WebhookEventType
    timestamp: datetime
    # Only one of these will be set based on event_type
    message: WhatsAppMessage | None = None
    status: StatusUpdate | None = None
    error: dict | None = None
    # Raw data for debugging
    raw_data: dict = field(default_factory=dict)

    @property
    def is_message(self) -> bool:
        """Check if this is a message event."""
        return self.event_type == WebhookEventType.MESSAGE

    @property
    def is_status(self) -> bool:
        """Check if this is a status update event."""
        return self.event_type == WebhookEventType.STATUS


class WebhookVerificationError(Exception):
    """Raised when webhook verification fails."""

    pass


class WebhookParseError(Exception):
    """Raised when webhook payload cannot be parsed."""

    pass


class WhatsAppWebhook:
    """WhatsApp Business Cloud API webhook handler.

    Handles webhook verification and parsing of incoming events.

    Args:
        verify_token: Token to verify webhook setup (you define this)
        app_secret: Meta App Secret for signature verification (optional but recommended)

    Example:
        >>> webhook = WhatsAppWebhook(
        ...     verify_token="my_verify_token",
        ...     app_secret="app_secret_from_meta"
        ... )
        >>> # Verification (GET request)
        >>> challenge = webhook.verify_webhook(
        ...     mode="subscribe",
        ...     token="my_verify_token",
        ...     challenge="challenge_string"
        ... )
        >>> # Parse incoming event (POST request)
        >>> events = webhook.parse_payload(request_body, signature_header)
    """

    def __init__(
        self,
        verify_token: str | None = None,
        app_secret: str | None = None,
    ):
        # Import settings lazily
        from assistant.config import settings

        self.verify_token = verify_token or settings.whatsapp_verify_token
        self.app_secret = app_secret or settings.whatsapp_app_secret

    def verify_webhook(
        self,
        mode: str | None,
        token: str | None,
        challenge: str | None,
    ) -> str:
        """Verify webhook subscription request.

        This handles the initial webhook setup verification from Meta.
        Meta sends a GET request with hub.mode, hub.verify_token, and hub.challenge.

        Args:
            mode: Should be "subscribe"
            token: Should match your verify_token
            challenge: Random string to echo back

        Returns:
            The challenge string to echo back

        Raises:
            WebhookVerificationError: If verification fails
        """
        if mode != "subscribe":
            raise WebhookVerificationError(f"Invalid mode: {mode}")

        if token != self.verify_token:
            raise WebhookVerificationError("Token mismatch")

        if not challenge:
            raise WebhookVerificationError("No challenge provided")

        logger.info("Webhook verified successfully")
        return challenge

    def verify_signature(
        self,
        payload: bytes,
        signature_header: str | None,
    ) -> bool:
        """Verify the webhook payload signature.

        Meta signs webhook payloads with your App Secret.
        The signature is in the X-Hub-Signature-256 header.

        Args:
            payload: Raw request body bytes
            signature_header: Value of X-Hub-Signature-256 header

        Returns:
            True if signature is valid, False otherwise
        """
        if not self.app_secret:
            logger.warning("No app_secret configured, skipping signature verification")
            return True

        if not signature_header:
            logger.warning("No signature header provided")
            return False

        # Signature format: "sha256=<hex_signature>"
        if not signature_header.startswith("sha256="):
            return False

        expected_signature = signature_header[7:]  # Remove "sha256=" prefix

        # Compute HMAC-SHA256
        computed_hash = hmac.new(
            self.app_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(computed_hash, expected_signature)

    def parse_payload(
        self,
        payload: bytes | str | dict,
        signature_header: str | None = None,
    ) -> list[WebhookEvent]:
        """Parse a webhook payload into events.

        Args:
            payload: Request body (bytes, string, or already-parsed dict)
            signature_header: X-Hub-Signature-256 header value (optional)

        Returns:
            List of WebhookEvent objects

        Raises:
            WebhookVerificationError: If signature verification fails
            WebhookParseError: If payload cannot be parsed
        """
        # Handle different payload types
        if isinstance(payload, bytes):
            if signature_header and not self.verify_signature(payload, signature_header):
                raise WebhookVerificationError("Invalid signature")
            try:
                data = json.loads(payload.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise WebhookParseError(f"Invalid JSON: {e}")
        elif isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
            if signature_header and not self.verify_signature(payload_bytes, signature_header):
                raise WebhookVerificationError("Invalid signature")
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as e:
                raise WebhookParseError(f"Invalid JSON: {e}")
        else:
            data = payload

        return self._parse_data(data)

    def _parse_data(self, data: dict) -> list[WebhookEvent]:
        """Parse webhook data structure into events."""
        events: list[WebhookEvent] = []

        # WhatsApp webhook structure:
        # {
        #   "object": "whatsapp_business_account",
        #   "entry": [
        #     {
        #       "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
        #       "changes": [
        #         {
        #           "value": { ... },
        #           "field": "messages"
        #         }
        #       ]
        #     }
        #   ]
        # }

        if data.get("object") != "whatsapp_business_account":
            logger.warning(f"Unexpected webhook object type: {data.get('object')}")
            return events

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue

                value = change.get("value", {})
                events.extend(self._parse_value(value))

        return events

    def _parse_value(self, value: dict) -> list[WebhookEvent]:
        """Parse the 'value' object from a change."""
        events: list[WebhookEvent] = []

        # Parse messages
        for message_data in value.get("messages", []):
            try:
                event = self._parse_message(message_data, value)
                events.append(event)
            except Exception as e:
                logger.exception(f"Failed to parse message: {e}")

        # Parse statuses
        for status_data in value.get("statuses", []):
            try:
                event = self._parse_status(status_data)
                events.append(event)
            except Exception as e:
                logger.exception(f"Failed to parse status: {e}")

        # Parse errors
        for error_data in value.get("errors", []):
            events.append(
                WebhookEvent(
                    event_type=WebhookEventType.ERROR,
                    timestamp=datetime.now(UTC),
                    error=error_data,
                    raw_data=value,
                )
            )

        return events

    def _parse_message(self, message_data: dict, value: dict) -> WebhookEvent:
        """Parse a message object into a WebhookEvent."""
        # Get contact info (sender) - contacts not currently used but parsed for future use
        _ = value.get("contacts", [])  # noqa: F841
        from_number = message_data.get("from", "")

        # Parse timestamp
        timestamp_str = message_data.get("timestamp", "")
        try:
            timestamp = datetime.fromtimestamp(int(timestamp_str), tz=UTC)
        except (ValueError, TypeError):
            timestamp = datetime.now(UTC)

        # Determine message type
        msg_type_str = message_data.get("type", "text")
        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            msg_type = MessageType.TEXT

        # Build message object
        message = WhatsAppMessage(
            message_id=message_data.get("id", ""),
            from_number=from_number,
            timestamp=timestamp,
            message_type=msg_type,
        )

        # Parse type-specific content
        if msg_type == MessageType.TEXT:
            text_obj = message_data.get("text", {})
            message.text = text_obj.get("body", "")

        elif msg_type == MessageType.AUDIO:
            audio_obj = message_data.get("audio", {})
            message.audio_id = audio_obj.get("id")
            message.audio_mime_type = audio_obj.get("mime_type")

        elif msg_type == MessageType.LOCATION:
            loc_obj = message_data.get("location", {})
            message.latitude = loc_obj.get("latitude")
            message.longitude = loc_obj.get("longitude")
            message.location_name = loc_obj.get("name")
            message.location_address = loc_obj.get("address")

        elif msg_type == MessageType.INTERACTIVE:
            # Handle interactive reply
            interactive = message_data.get("interactive", {})
            interactive_type = interactive.get("type")

            if interactive_type == "button_reply":
                button_reply = interactive.get("button_reply", {})
                message.text = button_reply.get("title", "")

            elif interactive_type == "list_reply":
                list_reply = interactive.get("list_reply", {})
                message.text = list_reply.get("title", "")

        # Parse context (reply info)
        context = message_data.get("context", {})
        if context:
            message.context_message_id = context.get("id")
            message.is_forwarded = context.get("forwarded", False)

        return WebhookEvent(
            event_type=WebhookEventType.MESSAGE,
            timestamp=timestamp,
            message=message,
            raw_data=message_data,
        )

    def _parse_status(self, status_data: dict) -> WebhookEvent:
        """Parse a status update object into a WebhookEvent."""
        # Parse timestamp
        timestamp_str = status_data.get("timestamp", "")
        try:
            timestamp = datetime.fromtimestamp(int(timestamp_str), tz=UTC)
        except (ValueError, TypeError):
            timestamp = datetime.now(UTC)

        # Parse status
        status_str = status_data.get("status", "")
        try:
            status_enum = MessageStatus(status_str)
        except ValueError:
            status_enum = MessageStatus.SENT

        # Build status update
        status = StatusUpdate(
            message_id=status_data.get("id", ""),
            status=status_enum,
            timestamp=timestamp,
            recipient_id=status_data.get("recipient_id", ""),
        )

        # Parse error info if failed
        if status_enum == MessageStatus.FAILED:
            errors = status_data.get("errors", [])
            if errors:
                status.error_code = str(errors[0].get("code", ""))
                status.error_title = errors[0].get("title", "")

        return WebhookEvent(
            event_type=WebhookEventType.STATUS,
            timestamp=timestamp,
            status=status,
            raw_data=status_data,
        )


# Module-level singleton
_webhook: WhatsAppWebhook | None = None


def get_whatsapp_webhook() -> WhatsAppWebhook:
    """Get the shared WhatsApp webhook handler instance."""
    global _webhook
    if _webhook is None:
        _webhook = WhatsAppWebhook()
    return _webhook


def verify_webhook(mode: str | None, token: str | None, challenge: str | None) -> str:
    """Verify webhook using the shared handler."""
    return get_whatsapp_webhook().verify_webhook(mode, token, challenge)


def parse_payload(
    payload: bytes | str | dict, signature_header: str | None = None
) -> list[WebhookEvent]:
    """Parse webhook payload using the shared handler."""
    return get_whatsapp_webhook().parse_payload(payload, signature_header)
