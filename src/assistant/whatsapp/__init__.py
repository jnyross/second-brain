"""WhatsApp integration for Second Brain.

This module provides WhatsApp Business Cloud API integration as an alternative
to Telegram for capturing thoughts, tasks, and ideas.

WhatsApp Business Cloud API Documentation:
https://developers.facebook.com/docs/whatsapp/cloud-api
"""

from assistant.whatsapp.client import WhatsAppClient
from assistant.whatsapp.webhook import WebhookEvent, WhatsAppWebhook

__all__ = [
    "WhatsAppClient",
    "WhatsAppWebhook",
    "WebhookEvent",
]
