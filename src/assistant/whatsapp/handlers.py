"""WhatsApp message handlers for Second Brain.

Handles incoming WhatsApp messages by processing them through the same
MessageProcessor pipeline used for Telegram. This ensures consistent
behavior across both platforms.
"""

import logging
from datetime import UTC, datetime
from io import BytesIO

from assistant.services.corrections import (
    get_correction_handler,
    is_correction_message,
    track_created_task,
)
from assistant.services.processor import MessageProcessor
from assistant.services.whisper import (
    TranscriptionError,
    TranscriptionResult,
    WhisperTranscriber,
)
from assistant.whatsapp.client import (
    MediaDownloadResult,
    MessageType,
    SendResult,
    WhatsAppClient,
    WhatsAppMessage,
    get_whatsapp_client,
)
from assistant.whatsapp.webhook import WebhookEvent, WebhookEventType

logger = logging.getLogger(__name__)

# Message processor instance (shared with Telegram)
processor = MessageProcessor()

# Whisper transcriber instance (created lazily)
_transcriber: WhisperTranscriber | None = None


def get_transcriber() -> WhisperTranscriber:
    """Get or create WhisperTranscriber instance."""
    global _transcriber
    if _transcriber is None:
        _transcriber = WhisperTranscriber()
    return _transcriber


class WhatsAppHandler:
    """Handles incoming WhatsApp webhook events.

    Processes messages through the same pipeline as Telegram messages,
    ensuring consistent behavior across both platforms.

    Example:
        >>> handler = WhatsAppHandler()
        >>> events = parse_payload(request_body)
        >>> for event in events:
        ...     await handler.handle_event(event)
    """

    def __init__(
        self,
        client: WhatsAppClient | None = None,
        processor: MessageProcessor | None = None,
    ):
        self.client = client or get_whatsapp_client()
        self.processor = processor or MessageProcessor()

    async def handle_event(self, event: WebhookEvent) -> None:
        """Handle a webhook event.

        Routes events to appropriate handlers based on event type.

        Args:
            event: The parsed webhook event
        """
        if event.event_type == WebhookEventType.MESSAGE:
            await self.handle_message(event)
        elif event.event_type == WebhookEventType.STATUS:
            await self.handle_status(event)
        elif event.event_type == WebhookEventType.ERROR:
            await self.handle_error(event)

    async def handle_message(self, event: WebhookEvent) -> None:
        """Handle an incoming message event.

        Routes to text or audio handler based on message type.

        Args:
            event: Message webhook event
        """
        message = event.message
        if not message:
            return

        # Mark message as read
        await self.client.mark_as_read(message.message_id)

        try:
            if message.message_type == MessageType.TEXT:
                await self._handle_text_message(message)
            elif message.message_type == MessageType.AUDIO:
                await self._handle_audio_message(message)
            elif message.message_type == MessageType.INTERACTIVE:
                # Interactive replies come as text
                await self._handle_text_message(message)
            elif message.message_type == MessageType.LOCATION:
                await self._handle_location_message(message)
            else:
                await self._send_unsupported_type_response(message)

        except Exception as e:
            logger.exception(f"Error handling WhatsApp message: {e}")
            await self._send_error_response(message, str(e))

    async def handle_status(self, event: WebhookEvent) -> None:
        """Handle a message status update event.

        Logs delivery status for tracking purposes.

        Args:
            event: Status webhook event
        """
        status = event.status
        if not status:
            return

        logger.info(
            f"Message {status.message_id} status: {status.status.value} "
            f"(recipient: {status.recipient_id})"
        )

        # Could store in database for delivery tracking
        # For now, just log it

    async def handle_error(self, event: WebhookEvent) -> None:
        """Handle an error event.

        Logs errors for debugging.

        Args:
            event: Error webhook event
        """
        logger.error(f"WhatsApp webhook error: {event.error}")

    async def _handle_text_message(self, message: WhatsAppMessage) -> None:
        """Handle a text message.

        Processes through MessageProcessor and sends response.

        Args:
            message: The WhatsApp message
        """
        text = message.text or ""
        from_number = message.from_number

        logger.info(f"Processing text message from {from_number}: {text[:50]}...")

        # Check for corrections first
        if is_correction_message(text):
            handler = get_correction_handler()
            result = await handler.handle_correction(
                chat_id=from_number,
                message=text,
            )
            if result.handled:
                response = result.response or "Got it, I've made that correction."
                await self.client.send_text(from_number, response)
                return

        # Process through MessageProcessor
        result = await self.processor.process(
            text=text,
            chat_id=from_number,
            message_id=message.message_id,
            source="whatsapp",
        )

        # Track task creation for correction context
        if result.task_id:
            track_created_task(
                chat_id=from_number,
                message_id=message.message_id,
                task_id=result.task_id,
                title=result.task_title or text,
            )

        # Send response
        await self.client.send_text(from_number, result.response)

    async def _handle_audio_message(self, message: WhatsAppMessage) -> None:
        """Handle an audio/voice message.

        Downloads audio, transcribes via Whisper, processes as text.

        Args:
            message: The WhatsApp message with audio
        """
        from_number = message.from_number
        audio_id = message.audio_id

        if not audio_id:
            await self.client.send_text(
                from_number,
                "I couldn't process that audio message. Please try again.",
            )
            return

        logger.info(f"Processing audio message from {from_number}")

        # Download audio
        download_result = await self.client.download_media(audio_id)
        if not download_result.success or not download_result.content:
            await self.client.send_text(
                from_number,
                "I couldn't download that audio. Please try again.",
            )
            return

        # Transcribe
        transcriber = get_transcriber()
        try:
            # Determine file extension from mime type
            extension = "ogg"  # Default for WhatsApp voice messages
            if download_result.mime_type:
                if "mp3" in download_result.mime_type:
                    extension = "mp3"
                elif "mp4" in download_result.mime_type:
                    extension = "mp4"
                elif "m4a" in download_result.mime_type:
                    extension = "m4a"
                elif "wav" in download_result.mime_type:
                    extension = "wav"

            audio_file = BytesIO(download_result.content)
            audio_file.name = f"voice.{extension}"

            transcription = await transcriber.transcribe(audio_file)

        except TranscriptionError as e:
            logger.error(f"Transcription failed: {e}")
            await self.client.send_text(
                from_number,
                "I couldn't transcribe that audio. Please try again or send a text message.",
            )
            return

        # Process transcription
        await self._process_transcription(
            message=message,
            transcription=transcription,
        )

    async def _process_transcription(
        self,
        message: WhatsAppMessage,
        transcription: TranscriptionResult,
    ) -> None:
        """Process a voice transcription result.

        Args:
            message: Original WhatsApp message
            transcription: Whisper transcription result
        """
        from_number = message.from_number
        text = transcription.text

        logger.info(
            f"Transcribed audio (confidence: {transcription.confidence}%): {text[:50]}..."
        )

        # Handle low-confidence transcriptions
        if transcription.is_low_confidence:
            # Process with low confidence flag
            result = await self.processor.process(
                text=text,
                chat_id=from_number,
                message_id=message.message_id,
                source="whatsapp_voice",
                voice_file_id=message.audio_id,
                transcript_confidence=transcription.confidence,
                language=transcription.language,
            )

            # Include transcription in response
            response = (
                f"I heard: \"{text}\"\n"
                f"(Confidence: {transcription.confidence}%)\n\n"
                f"{result.response}"
            )
        else:
            # Process normally
            result = await self.processor.process(
                text=text,
                chat_id=from_number,
                message_id=message.message_id,
                source="whatsapp_voice",
            )
            response = result.response

        # Track task creation
        if result.task_id:
            track_created_task(
                chat_id=from_number,
                message_id=message.message_id,
                task_id=result.task_id,
                title=result.task_title or text,
            )

        await self.client.send_text(from_number, response)

    async def _handle_location_message(self, message: WhatsAppMessage) -> None:
        """Handle a location message.

        Stores location as a place reference.

        Args:
            message: The WhatsApp message with location
        """
        from_number = message.from_number

        location_text = ""
        if message.location_name:
            location_text = message.location_name
        if message.location_address:
            location_text += f" ({message.location_address})"

        if not location_text:
            location_text = f"Location at {message.latitude}, {message.longitude}"

        # Process as "save this location" intent
        text = f"Remember this place: {location_text}"

        result = await self.processor.process(
            text=text,
            chat_id=from_number,
            message_id=message.message_id,
            source="whatsapp",
        )

        await self.client.send_text(from_number, result.response)

    async def _send_unsupported_type_response(self, message: WhatsAppMessage) -> None:
        """Send response for unsupported message types."""
        await self.client.send_text(
            message.from_number,
            f"I can only process text, voice, and location messages right now. "
            f"You sent a {message.message_type.value} message.",
        )

    async def _send_error_response(self, message: WhatsAppMessage, error: str) -> None:
        """Send error response."""
        await self.client.send_text(
            message.from_number,
            "Sorry, something went wrong processing your message. Please try again.",
        )


# Module-level handler instance
_handler: WhatsAppHandler | None = None


def get_whatsapp_handler() -> WhatsAppHandler:
    """Get the shared WhatsApp handler instance."""
    global _handler
    if _handler is None:
        _handler = WhatsAppHandler()
    return _handler


async def handle_webhook_events(events: list[WebhookEvent]) -> None:
    """Process a list of webhook events using the shared handler."""
    handler = get_whatsapp_handler()
    for event in events:
        await handler.handle_event(event)
