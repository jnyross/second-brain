"""Tests for WhatsApp Business Cloud API integration.

Tests cover:
- Client configuration and availability
- Message sending (text, templates, interactive)
- Media downloading
- Webhook verification
- Webhook payload parsing
- Message handling integration
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.whatsapp.client import (
    MAX_MESSAGE_LENGTH,
    MessageType,
    SendResult,
    WhatsAppClient,
    WhatsAppMessage,
    get_whatsapp_client,
    is_whatsapp_available,
)
from assistant.whatsapp.webhook import (
    MessageStatus,
    WebhookEvent,
    WebhookEventType,
    WebhookParseError,
    WebhookVerificationError,
    WhatsAppWebhook,
    get_whatsapp_webhook,
    parse_payload,
    verify_webhook,
)

# =============================================================================
# WhatsApp Client Tests
# =============================================================================


class TestWhatsAppMessage:
    """Tests for WhatsAppMessage dataclass."""

    def test_text_message(self):
        """Test text message properties."""
        msg = WhatsAppMessage(
            message_id="wamid.123",
            from_number="1234567890",
            timestamp=datetime.now(UTC),
            message_type=MessageType.TEXT,
            text="Hello world",
        )
        assert msg.text == "Hello world"
        assert not msg.has_audio
        assert not msg.has_location

    def test_audio_message(self):
        """Test audio message properties."""
        msg = WhatsAppMessage(
            message_id="wamid.123",
            from_number="1234567890",
            timestamp=datetime.now(UTC),
            message_type=MessageType.AUDIO,
            audio_id="audio123",
            audio_mime_type="audio/ogg",
        )
        assert msg.has_audio
        assert msg.audio_id == "audio123"
        assert not msg.has_location

    def test_location_message(self):
        """Test location message properties."""
        msg = WhatsAppMessage(
            message_id="wamid.123",
            from_number="1234567890",
            timestamp=datetime.now(UTC),
            message_type=MessageType.LOCATION,
            latitude=37.7749,
            longitude=-122.4194,
            location_name="San Francisco",
        )
        assert msg.has_location
        assert msg.latitude == 37.7749
        assert not msg.has_audio


class TestSendResult:
    """Tests for SendResult dataclass."""

    def test_successful_result(self):
        """Test successful send result."""
        result = SendResult(
            success=True,
            message_id="wamid.123",
        )
        assert result.success
        assert result.message_id == "wamid.123"
        assert result.error_code is None

    def test_failed_result(self):
        """Test failed send result."""
        result = SendResult(
            success=False,
            error_code="131047",
            error_message="Re-engagement message required",
        )
        assert not result.success
        assert result.error_code == "131047"


class TestWhatsAppClientInit:
    """Tests for WhatsApp client initialization."""

    def test_init_with_credentials(self):
        """Test initialization with explicit credentials."""
        client = WhatsAppClient(
            phone_number_id="123456789",
            access_token="EAABc...",
        )
        assert client.phone_number_id == "123456789"
        assert client.access_token == "EAABc..."
        assert client.is_configured

    def test_init_without_credentials(self):
        """Test initialization without credentials."""
        with patch("assistant.config.settings") as mock_settings:
            mock_settings.whatsapp_phone_number_id = ""
            mock_settings.whatsapp_access_token = ""
            client = WhatsAppClient(
                phone_number_id="",
                access_token="",
            )
            assert not client.is_configured


class TestWhatsAppClientSendText:
    """Tests for sending text messages."""

    @pytest.fixture
    def client(self):
        """Create a configured client."""
        return WhatsAppClient(
            phone_number_id="123456789",
            access_token="test_token",
        )

    @pytest.mark.asyncio
    async def test_send_text_success(self, client):
        """Test successful text message send."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messaging_product": "whatsapp",
            "messages": [{"id": "wamid.123"}],
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_http

            result = await client.send_text("1234567890", "Hello!")

            assert result.success
            assert result.message_id == "wamid.123"

    @pytest.mark.asyncio
    async def test_send_text_truncates_long_messages(self, client):
        """Test that long messages are truncated."""
        long_text = "x" * (MAX_MESSAGE_LENGTH + 100)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.123"}]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_http

            await client.send_text("1234567890", long_text)

            # Check the payload was truncated
            call_args = mock_http.post.call_args
            payload = call_args[1]["json"]
            assert len(payload["text"]["body"]) == MAX_MESSAGE_LENGTH


class TestWhatsAppClientSendTemplate:
    """Tests for sending template messages."""

    @pytest.fixture
    def client(self):
        """Create a configured client."""
        return WhatsAppClient(
            phone_number_id="123456789",
            access_token="test_token",
        )

    @pytest.mark.asyncio
    async def test_send_template_success(self, client):
        """Test successful template message send."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.123"}]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_http

            result = await client.send_template(
                "1234567890",
                "hello_world",
                language_code="en",
            )

            assert result.success

            # Check template payload
            call_args = mock_http.post.call_args
            payload = call_args[1]["json"]
            assert payload["type"] == "template"
            assert payload["template"]["name"] == "hello_world"


class TestWhatsAppClientSendInteractive:
    """Tests for sending interactive messages."""

    @pytest.fixture
    def client(self):
        """Create a configured client."""
        return WhatsAppClient(
            phone_number_id="123456789",
            access_token="test_token",
        )

    @pytest.mark.asyncio
    async def test_send_interactive_buttons(self, client):
        """Test sending button message."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.123"}]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_http

            result = await client.send_interactive_buttons(
                "1234567890",
                "Choose an option:",
                [
                    {"id": "yes", "title": "Yes"},
                    {"id": "no", "title": "No"},
                ],
            )

            assert result.success

            # Check interactive payload
            call_args = mock_http.post.call_args
            payload = call_args[1]["json"]
            assert payload["type"] == "interactive"
            assert payload["interactive"]["type"] == "button"

    @pytest.mark.asyncio
    async def test_send_interactive_list(self, client):
        """Test sending list message."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.123"}]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_http

            result = await client.send_interactive_list(
                "1234567890",
                "Select a task:",
                "View Tasks",
                [
                    {
                        "title": "High Priority",
                        "rows": [
                            {"id": "task1", "title": "Buy groceries"},
                        ],
                    }
                ],
            )

            assert result.success


class TestWhatsAppClientDownloadMedia:
    """Tests for downloading media."""

    @pytest.fixture
    def client(self):
        """Create a configured client."""
        return WhatsAppClient(
            phone_number_id="123456789",
            access_token="test_token",
        )

    @pytest.mark.asyncio
    async def test_download_media_success(self, client):
        """Test successful media download."""
        # Mock URL response
        url_response = MagicMock()
        url_response.status_code = 200
        url_response.json.return_value = {"url": "https://example.com/media.ogg"}
        url_response.raise_for_status = MagicMock()

        # Mock content response
        content_response = MagicMock()
        content_response.status_code = 200
        content_response.content = b"fake audio data"
        content_response.headers = {"content-type": "audio/ogg"}
        content_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=[url_response, content_response])
            mock_get_client.return_value = mock_http

            result = await client.download_media("media123")

            assert result.success
            assert result.content == b"fake audio data"
            assert result.mime_type == "audio/ogg"


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_whatsapp_client_singleton(self):
        """Test that get_whatsapp_client returns a singleton."""
        with patch("assistant.whatsapp.client._client", None):
            client1 = get_whatsapp_client()
            client2 = get_whatsapp_client()
            # Both should be the same instance
            assert client1 is client2

    def test_is_whatsapp_available(self):
        """Test availability check."""
        with patch("assistant.whatsapp.client.get_whatsapp_client") as mock:
            mock_client = MagicMock()
            mock_client.is_configured = True
            mock.return_value = mock_client
            assert is_whatsapp_available()

            mock_client.is_configured = False
            assert not is_whatsapp_available()


# =============================================================================
# WhatsApp Webhook Tests
# =============================================================================


class TestWebhookVerification:
    """Tests for webhook verification."""

    def test_verify_webhook_success(self):
        """Test successful webhook verification."""
        webhook = WhatsAppWebhook(verify_token="my_token")
        challenge = webhook.verify_webhook(
            mode="subscribe",
            token="my_token",
            challenge="challenge_string",
        )
        assert challenge == "challenge_string"

    def test_verify_webhook_wrong_mode(self):
        """Test verification fails with wrong mode."""
        webhook = WhatsAppWebhook(verify_token="my_token")
        with pytest.raises(WebhookVerificationError, match="Invalid mode"):
            webhook.verify_webhook(
                mode="unsubscribe",
                token="my_token",
                challenge="challenge_string",
            )

    def test_verify_webhook_wrong_token(self):
        """Test verification fails with wrong token."""
        webhook = WhatsAppWebhook(verify_token="my_token")
        with pytest.raises(WebhookVerificationError, match="Token mismatch"):
            webhook.verify_webhook(
                mode="subscribe",
                token="wrong_token",
                challenge="challenge_string",
            )

    def test_verify_webhook_no_challenge(self):
        """Test verification fails without challenge."""
        webhook = WhatsAppWebhook(verify_token="my_token")
        with pytest.raises(WebhookVerificationError, match="No challenge"):
            webhook.verify_webhook(
                mode="subscribe",
                token="my_token",
                challenge=None,
            )


class TestWebhookSignatureVerification:
    """Tests for webhook signature verification."""

    def test_verify_signature_valid(self):
        """Test valid signature verification."""
        app_secret = "test_secret"
        payload = b'{"test": "data"}'

        # Compute expected signature
        signature = hmac.new(
            app_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        webhook = WhatsAppWebhook(app_secret=app_secret)
        assert webhook.verify_signature(payload, f"sha256={signature}")

    def test_verify_signature_invalid(self):
        """Test invalid signature rejection."""
        webhook = WhatsAppWebhook(app_secret="test_secret")
        payload = b'{"test": "data"}'
        assert not webhook.verify_signature(payload, "sha256=invalid")

    def test_verify_signature_no_header(self):
        """Test missing signature header."""
        webhook = WhatsAppWebhook(app_secret="test_secret")
        assert not webhook.verify_signature(b"test", None)

    def test_verify_signature_no_secret_skips(self):
        """Test that missing app_secret skips verification."""
        webhook = WhatsAppWebhook(app_secret="")
        assert webhook.verify_signature(b"test", "sha256=anything")


class TestWebhookPayloadParsing:
    """Tests for parsing webhook payloads."""

    def test_parse_text_message(self):
        """Test parsing a text message webhook."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "BUSINESS_ID",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"display_phone_number": "123"},
                                "contacts": [{"profile": {"name": "John"}}],
                                "messages": [
                                    {
                                        "from": "1234567890",
                                        "id": "wamid.123",
                                        "timestamp": "1700000000",
                                        "type": "text",
                                        "text": {"body": "Hello world"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        webhook = WhatsAppWebhook(verify_token="test")
        events = webhook.parse_payload(payload)

        assert len(events) == 1
        event = events[0]
        assert event.event_type == WebhookEventType.MESSAGE
        assert event.message is not None
        assert event.message.text == "Hello world"
        assert event.message.from_number == "1234567890"

    def test_parse_audio_message(self):
        """Test parsing an audio message webhook."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "BUSINESS_ID",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "from": "1234567890",
                                        "id": "wamid.123",
                                        "timestamp": "1700000000",
                                        "type": "audio",
                                        "audio": {
                                            "id": "audio123",
                                            "mime_type": "audio/ogg; codecs=opus",
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        webhook = WhatsAppWebhook(verify_token="test")
        events = webhook.parse_payload(payload)

        assert len(events) == 1
        assert events[0].message.message_type == MessageType.AUDIO
        assert events[0].message.audio_id == "audio123"

    def test_parse_location_message(self):
        """Test parsing a location message webhook."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "BUSINESS_ID",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "from": "1234567890",
                                        "id": "wamid.123",
                                        "timestamp": "1700000000",
                                        "type": "location",
                                        "location": {
                                            "latitude": 37.7749,
                                            "longitude": -122.4194,
                                            "name": "San Francisco",
                                            "address": "CA, USA",
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        webhook = WhatsAppWebhook(verify_token="test")
        events = webhook.parse_payload(payload)

        assert len(events) == 1
        msg = events[0].message
        assert msg.message_type == MessageType.LOCATION
        assert msg.latitude == 37.7749
        assert msg.location_name == "San Francisco"

    def test_parse_status_update(self):
        """Test parsing a status update webhook."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "BUSINESS_ID",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.123",
                                        "status": "delivered",
                                        "timestamp": "1700000000",
                                        "recipient_id": "1234567890",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        webhook = WhatsAppWebhook(verify_token="test")
        events = webhook.parse_payload(payload)

        assert len(events) == 1
        assert events[0].event_type == WebhookEventType.STATUS
        assert events[0].status.status == MessageStatus.DELIVERED

    def test_parse_interactive_reply(self):
        """Test parsing an interactive button reply."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "BUSINESS_ID",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "from": "1234567890",
                                        "id": "wamid.123",
                                        "timestamp": "1700000000",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {
                                                "id": "yes_button",
                                                "title": "Yes",
                                            },
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        webhook = WhatsAppWebhook(verify_token="test")
        events = webhook.parse_payload(payload)

        assert len(events) == 1
        assert events[0].message.message_type == MessageType.INTERACTIVE
        assert events[0].message.text == "Yes"

    def test_parse_json_string_payload(self):
        """Test parsing a JSON string payload."""
        payload_dict = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "from": "123",
                                        "id": "wamid.1",
                                        "timestamp": "1700000000",
                                        "type": "text",
                                        "text": {"body": "test"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        webhook = WhatsAppWebhook(verify_token="test")
        events = webhook.parse_payload(json.dumps(payload_dict))

        assert len(events) == 1
        assert events[0].message.text == "test"

    def test_parse_bytes_payload(self):
        """Test parsing a bytes payload."""
        payload_dict = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "from": "123",
                                        "id": "wamid.1",
                                        "timestamp": "1700000000",
                                        "type": "text",
                                        "text": {"body": "test"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        webhook = WhatsAppWebhook(verify_token="test")
        events = webhook.parse_payload(json.dumps(payload_dict).encode("utf-8"))

        assert len(events) == 1

    def test_parse_invalid_json(self):
        """Test parsing invalid JSON raises error."""
        webhook = WhatsAppWebhook(verify_token="test")
        with pytest.raises(WebhookParseError, match="Invalid JSON"):
            webhook.parse_payload(b"not json")

    def test_parse_wrong_object_type(self):
        """Test parsing wrong object type returns empty list."""
        payload = {"object": "instagram", "entry": []}

        webhook = WhatsAppWebhook(verify_token="test")
        events = webhook.parse_payload(payload)

        assert len(events) == 0


class TestWebhookModuleFunctions:
    """Tests for webhook module-level functions."""

    def test_get_whatsapp_webhook_singleton(self):
        """Test that get_whatsapp_webhook returns a singleton."""
        with patch("assistant.whatsapp.webhook._webhook", None):
            wh1 = get_whatsapp_webhook()
            wh2 = get_whatsapp_webhook()
            assert wh1 is wh2

    def test_verify_webhook_convenience(self):
        """Test verify_webhook convenience function."""
        with patch("assistant.whatsapp.webhook.get_whatsapp_webhook") as mock:
            mock_wh = MagicMock()
            mock_wh.verify_webhook.return_value = "challenge"
            mock.return_value = mock_wh

            result = verify_webhook("subscribe", "token", "challenge")
            assert result == "challenge"

    def test_parse_payload_convenience(self):
        """Test parse_payload convenience function."""
        with patch("assistant.whatsapp.webhook.get_whatsapp_webhook") as mock:
            mock_wh = MagicMock()
            mock_wh.parse_payload.return_value = []
            mock.return_value = mock_wh

            result = parse_payload({"test": "data"})
            assert result == []


# =============================================================================
# Integration Tests
# =============================================================================


class TestWhatsAppHandlerIntegration:
    """Integration tests for WhatsApp message handling."""

    @pytest.mark.asyncio
    async def test_text_message_flow(self):
        """Test complete text message handling flow."""
        from assistant.whatsapp.handlers import WhatsAppHandler

        # Create mock client
        mock_client = MagicMock()
        mock_client.mark_as_read = AsyncMock(return_value=True)
        mock_client.send_text = AsyncMock(
            return_value=SendResult(success=True, message_id="wamid.response")
        )

        # Create mock processor
        mock_processor = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "Task created!"
        mock_result.task_id = "T-001"
        mock_result.task_title = "Buy groceries"
        mock_processor.process = AsyncMock(return_value=mock_result)

        handler = WhatsAppHandler(client=mock_client, processor=mock_processor)

        # Create message event
        message = WhatsAppMessage(
            message_id="wamid.123",
            from_number="1234567890",
            timestamp=datetime.now(UTC),
            message_type=MessageType.TEXT,
            text="Buy groceries tomorrow",
        )
        event = WebhookEvent(
            event_type=WebhookEventType.MESSAGE,
            timestamp=datetime.now(UTC),
            message=message,
        )

        # Handle the event
        await handler.handle_event(event)

        # Verify
        mock_client.mark_as_read.assert_called_once_with("wamid.123")
        mock_processor.process.assert_called_once()
        mock_client.send_text.assert_called_once_with("1234567890", "Task created!")


class TestT140WhatsAppIntegration:
    """Acceptance tests for T-140: WhatsApp integration."""

    def test_whatsapp_module_exports(self):
        """Test that whatsapp module exports required classes."""
        from assistant.whatsapp import WebhookEvent, WhatsAppClient, WhatsAppWebhook

        assert WhatsAppClient is not None
        assert WhatsAppWebhook is not None
        assert WebhookEvent is not None

    def test_config_has_whatsapp_settings(self):
        """Test that config includes WhatsApp settings."""
        from assistant.config import Settings

        settings = Settings()
        assert hasattr(settings, "whatsapp_phone_number_id")
        assert hasattr(settings, "whatsapp_access_token")
        assert hasattr(settings, "whatsapp_verify_token")
        assert hasattr(settings, "whatsapp_app_secret")
        assert hasattr(settings, "has_whatsapp")

    def test_message_processor_shared(self):
        """Test that WhatsApp uses the same MessageProcessor as Telegram."""
        from assistant.services.processor import MessageProcessor
        from assistant.whatsapp.handlers import WhatsAppHandler

        handler = WhatsAppHandler()
        # Should use MessageProcessor instance
        assert isinstance(handler.processor, MessageProcessor)

    @pytest.mark.asyncio
    async def test_text_message_creates_task(self):
        """Test that text messages can create tasks like Telegram."""
        from assistant.whatsapp.handlers import WhatsAppHandler

        mock_client = MagicMock()
        mock_client.mark_as_read = AsyncMock(return_value=True)
        mock_client.send_text = AsyncMock(
            return_value=SendResult(success=True, message_id="wamid.1")
        )

        mock_processor = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "Got it! Created task: Call mom"
        mock_result.task_id = "T-123"
        mock_result.task_title = "Call mom"
        mock_processor.process = AsyncMock(return_value=mock_result)

        handler = WhatsAppHandler(client=mock_client, processor=mock_processor)

        message = WhatsAppMessage(
            message_id="wamid.in",
            from_number="15551234567",
            timestamp=datetime.now(UTC),
            message_type=MessageType.TEXT,
            text="Call mom tomorrow at 3pm",
        )

        await handler._handle_text_message(message)

        # Verify processor was called with correct args
        mock_processor.process.assert_called_once()
        call_args = mock_processor.process.call_args
        assert call_args[1]["text"] == "Call mom tomorrow at 3pm"
        assert call_args[1]["chat_id"] == "15551234567"
        assert call_args[1]["message_id"] == "wamid.in"

        # Verify response was sent
        mock_client.send_text.assert_called_once()

    def test_webhook_verification_handshake(self):
        """Test webhook verification for Meta setup."""
        webhook = WhatsAppWebhook(verify_token="test_token_123")

        # Simulate Meta's verification request
        challenge = webhook.verify_webhook(
            mode="subscribe",
            token="test_token_123",
            challenge="random_challenge_12345",
        )

        # Should return the challenge to complete handshake
        assert challenge == "random_challenge_12345"

    def test_message_types_supported(self):
        """Test that WhatsApp supports text, audio, and location."""
        from assistant.whatsapp.client import MessageType

        # These types should be supported
        assert MessageType.TEXT.value == "text"
        assert MessageType.AUDIO.value == "audio"
        assert MessageType.LOCATION.value == "location"
        assert MessageType.INTERACTIVE.value == "interactive"
