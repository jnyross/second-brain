"""LLM-enhanced intent parsing with regex fallback."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from assistant.services.intent import ParsedIntent

if TYPE_CHECKING:
    import httpx

    from assistant.services.parser import Parser

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.0-flash"  # 200+ tokens/sec throughput
DEFAULT_TIMEOUT_SECONDS = 15.0


class LLMIntentParser:
    """Parse intents with an LLM, falling back to the regex parser on failure."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_parser: Parser | None = None,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        resolved_api_key = api_key
        resolved_model = model

        if resolved_api_key is None:
            from assistant.config import settings

            resolved_api_key = settings.gemini_api_key
            if resolved_model is None:
                resolved_model = settings.gemini_model or DEFAULT_MODEL
        elif resolved_model is None:
            resolved_model = DEFAULT_MODEL

        self.api_key = resolved_api_key
        self.model = resolved_model
        if base_parser is None:
            from assistant.services.parser import Parser

            self.base_parser = Parser()
        else:
            self.base_parser = base_parser
        if client is None:
            import httpx

            self.client = httpx.Client(timeout=timeout)
        else:
            self.client = client
        self.timeout = timeout

    def parse(self, text: str) -> ParsedIntent:
        base_result = self.base_parser.parse(text)
        if not self.api_key:
            return base_result

        try:
            payload = self._request_llm(text)
            llm_data = self._extract_llm_payload(payload)
            return self._merge_with_base(text, base_result, llm_data)
        except Exception as exc:
            logger.warning("LLM parser failed; falling back to regex parser: %s", exc)
            return base_result

    def _request_llm(self, text: str) -> dict[str, Any]:
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )
        prompt = (
            "You are an intent parser for a personal assistant. "
            "Return only JSON with keys: intent_type, title, confidence, due_date, "
            "due_timezone, people, places. "
            "intent_type must be task, idea, note, person, or project. "
            "confidence must be 0-100. "
            "due_date must be ISO-8601 or null. "
            "people and places are lists of strings. "
            f"Input: {text}"
        )
        response = self.client.post(
            endpoint,
            params={"key": self.api_key},
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                },
            },
        )
        response.raise_for_status()
        return response.json()

    def _extract_llm_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidates = payload.get("candidates", [])
        if not candidates:
            raise ValueError("No LLM candidates returned")

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        text = None
        for part in parts:
            if "text" in part:
                text = part["text"]
                break

        if not text:
            raise ValueError("No text payload returned from LLM")

        return json.loads(text)

    def _merge_with_base(
        self, text: str, base: ParsedIntent, llm_data: dict[str, Any]
    ) -> ParsedIntent:
        due_date = self._parse_due_date(llm_data.get("due_date")) or base.due_date
        due_timezone = llm_data.get("due_timezone") or base.due_timezone
        if due_timezone is None and due_date and due_date.tzinfo:
            due_timezone = str(due_date.tzinfo)

        confidence = self._coerce_confidence(llm_data.get("confidence"), base.confidence)
        intent_type = llm_data.get("intent_type") or base.intent_type
        title = llm_data.get("title") or base.title
        people = self._coerce_list(llm_data.get("people"), base.people)
        places = self._coerce_list(llm_data.get("places"), base.places)

        return ParsedIntent(
            intent_type=intent_type,
            title=title,
            confidence=confidence,
            due_date=due_date,
            due_timezone=due_timezone,
            people=people,
            places=places,
            raw_text=text,
        )

    def _parse_due_date(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError("Invalid due_date format")

    def _coerce_confidence(self, value: Any, fallback: int) -> int:
        if value is None:
            return fallback
        try:
            confidence = int(round(float(value)))
        except (TypeError, ValueError):
            return fallback
        return max(0, min(100, confidence))

    def _coerce_list(self, value: Any, fallback: list[str]) -> list[str]:
        if value is None:
            return fallback
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        raise ValueError("Expected list value")


_parser: LLMIntentParser | None = None


def get_intent_parser() -> LLMIntentParser:
    global _parser
    if _parser is None:
        _parser = LLMIntentParser()
    return _parser
