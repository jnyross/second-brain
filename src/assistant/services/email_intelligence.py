"""Email intelligence service using LLM for analysis.

Uses Gemini 3 Flash via OpenRouter to analyze emails for:
- Importance scoring (0-100)
- Urgency classification
- Action item extraction
- Response suggestions
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from assistant.config import settings
from assistant.google.gmail import EmailMessage
from assistant.services.llm_client import OpenRouterProvider

logger = logging.getLogger(__name__)

# Default model for email analysis - Gemini 3 Flash via OpenRouter
DEFAULT_EMAIL_MODEL = "google/gemini-2.0-flash-exp"


@dataclass
class EmailAnalysis:
    """Result of LLM email analysis."""

    importance_score: int  # 0-100
    urgency: str  # urgent, high, normal, low
    category: str  # work, personal, newsletter, notification, spam, etc.
    needs_response: bool
    action_items: list[str] = field(default_factory=list)
    people_mentioned: list[str] = field(default_factory=list)
    suggested_response: str | None = None
    summary: str | None = None
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


ANALYSIS_SYSTEM_PROMPT = """You are an email analysis assistant. Analyze emails to determine \
their importance and extract actionable information.

Respond ONLY with valid JSON matching this schema:
{
  "importance_score": <0-100>,
  "urgency": "<urgent|high|normal|low>",
  "category": "<work|personal|newsletter|notification|transactional|spam|social>",
  "needs_response": <true|false>,
  "action_items": ["<action 1>", "<action 2>"],
  "people_mentioned": ["<name 1>", "<name 2>"],
  "suggested_response": "<brief suggested response approach or null>",
  "summary": "<one sentence summary>"
}

Scoring guidelines:
- 90-100: Urgent, time-sensitive, from important contacts, requires immediate action
- 70-89: Important but not urgent, from known contacts, has deadlines
- 50-69: Moderately important, useful information, optional action
- 30-49: Low priority, informational, newsletters worth reading
- 0-29: Spam, marketing, unimportant notifications

Category definitions:
- work: Professional correspondence, project updates, meetings
- personal: Friends, family, personal matters
- newsletter: Subscribed content, digests, publications
- notification: System alerts, service notifications
- transactional: Receipts, confirmations, shipping updates
- spam: Unsolicited marketing, scams
- social: Social media notifications"""


class EmailIntelligenceService:
    """Service for analyzing emails using LLM."""

    def __init__(
        self,
        model: str = DEFAULT_EMAIL_MODEL,
        importance_threshold: int = 50,
    ):
        """Initialize the email intelligence service.

        Args:
            model: OpenRouter model ID to use for analysis
            importance_threshold: Minimum score to flag as important
        """
        self.model = model
        self.importance_threshold = importance_threshold
        self._provider: OpenRouterProvider | None = None

    def _get_provider(self) -> OpenRouterProvider:
        """Get or create the OpenRouter provider."""
        if self._provider is None:
            if not settings.openrouter_api_key:
                raise RuntimeError(
                    "OpenRouter API key not configured. Set OPENROUTER_API_KEY in .env"
                )
            self._provider = OpenRouterProvider(
                api_key=settings.openrouter_api_key,
                model=self.model,
                timeout=60.0,  # Longer timeout for email analysis
            )
        return self._provider

    def analyze_email(self, email: EmailMessage) -> EmailAnalysis:
        """Analyze an email using LLM.

        Args:
            email: EmailMessage from Gmail client

        Returns:
            EmailAnalysis with importance score, urgency, action items, etc.
        """
        provider = self._get_provider()

        # Build the analysis prompt
        prompt = self._build_analysis_prompt(email)

        try:
            response = provider.complete(
                prompt,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                temperature=0.1,  # Low temperature for consistent analysis
                max_tokens=1024,
                json_mode=True,
            )

            # Parse the JSON response
            analysis_data = json.loads(response.text)

            return EmailAnalysis(
                importance_score=int(analysis_data.get("importance_score", 50)),
                urgency=analysis_data.get("urgency", "normal"),
                category=analysis_data.get("category", "work"),
                needs_response=bool(analysis_data.get("needs_response", False)),
                action_items=analysis_data.get("action_items", []),
                people_mentioned=analysis_data.get("people_mentioned", []),
                suggested_response=analysis_data.get("suggested_response"),
                summary=analysis_data.get("summary"),
            )

        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response as JSON: %s", e)
            # Return a default analysis on parse failure
            return EmailAnalysis(
                importance_score=50,
                urgency="normal",
                category="work",
                needs_response=False,
                summary="Analysis failed - could not parse response",
            )
        except Exception as e:
            logger.exception("Email analysis failed: %s", e)
            raise

    def _build_analysis_prompt(self, email: EmailMessage) -> str:
        """Build the prompt for email analysis."""
        # Use snippet as body (EmailMessage only has snippet, not full body)
        body = email.snippet or ""
        if len(body) > 2000:
            body = body[:2000] + "\n... [truncated]"

        parts = [
            f"From: {email.sender_name} <{email.sender_email}>",
            f"Subject: {email.subject}",
            f"Date: {email.received_at.isoformat()}",
            "",
            "Body:",
            body,
        ]

        if email.has_attachments:
            parts.append("\n[Email has attachment(s)]")

        return "\n".join(parts)

    def is_important(self, analysis: EmailAnalysis) -> bool:
        """Check if an email analysis meets the importance threshold."""
        return analysis.importance_score >= self.importance_threshold

    def close(self) -> None:
        """Close the provider client."""
        if self._provider:
            self._provider.close()
            self._provider = None


# Module-level singleton
_service: EmailIntelligenceService | None = None


def get_email_intelligence_service() -> EmailIntelligenceService:
    """Get or create the singleton email intelligence service."""
    global _service
    if _service is None:
        # Use environment variable for model if set
        model = getattr(settings, "email_llm_model", None) or DEFAULT_EMAIL_MODEL
        threshold = getattr(settings, "email_importance_threshold", None) or 50
        _service = EmailIntelligenceService(
            model=model,
            importance_threshold=threshold,
        )
    return _service


def analyze_email(email: EmailMessage) -> EmailAnalysis:
    """Convenience function to analyze an email."""
    return get_email_intelligence_service().analyze_email(email)
