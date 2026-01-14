"""Provider-agnostic LLM client with fallback, cost tracking, and rate limiting."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    text: str
    provider: LLMProvider
    model: str
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """Total tokens used in this request."""
        return self.tokens_input + self.tokens_output


@dataclass
class LLMUsageStats:
    """Usage statistics for a provider."""

    total_requests: int = 0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0
    errors: int = 0
    last_request_at: datetime | None = None
    requests_in_window: list[datetime] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        """Average latency per request."""
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests


# Cost per 1M tokens (input/output) - prices as of Jan 2026
# NOTE: Optimized for SPEED and PERFORMANCE, not cost
PROVIDER_COSTS: dict[str, tuple[float, float]] = {
    # Direct Gemini API - Flagship & Fast models
    "gemini-2.0-flash": (0.10, 0.40),  # FAST: 200+ tokens/sec
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),  # 1M context
    "gemini-2.5-flash-lite": (0.075, 0.30),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 5.00),
    # Direct OpenAI API - Latest flagship models
    "gpt-4o": (2.50, 10.00),  # Strong multimodal
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    # Direct Anthropic API - Claude 4.5 series (latest)
    "claude-sonnet-4-5-20250514": (3.00, 15.00),  # Claude 4.5 Sonnet - latest
    "claude-haiku-4-5-20250514": (0.80, 4.00),  # Claude 4.5 Haiku - lowest latency
    "claude-opus-4-5-20250514": (15.00, 75.00),  # Claude 4.5 Opus - most capable
    # Claude 4 / 3.5 series (legacy)
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    # OpenRouter models (provider/model format)
    "openai/gpt-4o": (2.50, 10.00),  # High performance
    "openai/gpt-4o-mini": (0.15, 0.60),
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "anthropic/claude-3.5-haiku": (0.80, 4.00),
    "google/gemini-flash-1.5": (0.075, 0.30),
    "google/gemini-flash-1.5-8b": (0.0375, 0.15),
    "google/gemini-pro-1.5": (1.25, 5.00),
    "meta-llama/llama-3.3-70b-instruct": (0.35, 0.40),
    "meta-llama/llama-3.1-8b-instruct": (0.055, 0.055),
    "deepseek/deepseek-chat": (0.14, 0.28),
    "deepseek/deepseek-r1": (0.55, 2.19),
    "mistralai/mistral-small-24b-instruct-2501": (0.10, 0.30),
    "qwen/qwen-2.5-72b-instruct": (0.35, 0.40),
}


def estimate_cost(model: str, tokens_input: int, tokens_output: int) -> float:
    """Estimate cost in USD for a request."""
    if model not in PROVIDER_COSTS:
        # Default to a conservative estimate for unknown models
        return (tokens_input * 1.0 + tokens_output * 3.0) / 1_000_000
    input_cost, output_cost = PROVIDER_COSTS[model]
    return (tokens_input * input_cost + tokens_output * output_cost) / 1_000_000


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    provider: LLMProvider
    default_model: str

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model or self.default_model
        self.timeout = timeout
        if client is None:
            import httpx

            self._client = httpx.Client(timeout=timeout)
            self._owns_client = True
        else:
            self._client = client
            self._owns_client = False

    def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._owns_client and self._client is not None:
            self._client.close()

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Send a completion request and return standardized response."""
        ...

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate (4 chars per token)."""
        return max(1, len(text) // 4)


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API provider."""

    provider = LLMProvider.GEMINI
    default_model = "gemini-2.0-flash"  # 200+ tokens/sec throughput

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Send completion to Gemini API."""
        start_time = time.time()
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append(
                {"role": "model", "parts": [{"text": "Understood. Following instructions."}]}
            )
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            generation_config["response_mime_type"] = "application/json"

        response = self._client.post(
            endpoint,
            params={"key": self.api_key},
            json={"contents": contents, "generationConfig": generation_config},
        )
        response.raise_for_status()
        data = response.json()

        latency_ms = int((time.time() - start_time) * 1000)

        # Extract text
        text = ""
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    text = part["text"]
                    break

        # Extract usage
        usage = data.get("usageMetadata", {})
        tokens_input = usage.get("promptTokenCount", self._estimate_tokens(prompt))
        tokens_output = usage.get("candidatesTokenCount", self._estimate_tokens(text))

        return LLMResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=latency_ms,
            cost_usd=estimate_cost(self.model, tokens_input, tokens_output),
            raw_response=data,
        )


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API provider."""

    provider = LLMProvider.OPENAI
    default_model = "gpt-4o"  # Best multimodal, strong reasoning

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Send completion to OpenAI API."""
        start_time = time.time()
        endpoint = "https://api.openai.com/v1/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            request_body["response_format"] = {"type": "json_object"}

        response = self._client.post(
            endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()

        latency_ms = int((time.time() - start_time) * 1000)

        # Extract text
        text = ""
        choices = data.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")

        # Extract usage
        usage = data.get("usage", {})
        tokens_input = usage.get("prompt_tokens", self._estimate_tokens(prompt))
        tokens_output = usage.get("completion_tokens", self._estimate_tokens(text))

        return LLMResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=latency_ms,
            cost_usd=estimate_cost(self.model, tokens_input, tokens_output),
            raw_response=data,
        )


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude API provider."""

    provider = LLMProvider.ANTHROPIC
    default_model = "claude-sonnet-4-5-20250514"  # Claude 4.5 Sonnet - latest, fast + capable

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Send completion to Anthropic API."""
        start_time = time.time()
        endpoint = "https://api.anthropic.com/v1/messages"

        messages = [{"role": "user", "content": prompt}]
        if json_mode:
            messages[0]["content"] = f"{prompt}\n\nRespond with valid JSON only, no other text."

        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            request_body["system"] = system_prompt

        response = self._client.post(
            endpoint,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()

        latency_ms = int((time.time() - start_time) * 1000)

        # Extract text
        text = ""
        content = data.get("content", [])
        if content:
            for block in content:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    break

        # Extract usage
        usage = data.get("usage", {})
        tokens_input = usage.get("input_tokens", self._estimate_tokens(prompt))
        tokens_output = usage.get("output_tokens", self._estimate_tokens(text))

        return LLMResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=latency_ms,
            cost_usd=estimate_cost(self.model, tokens_input, tokens_output),
            raw_response=data,
        )


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter API provider - OpenAI-compatible interface to 100+ models."""

    provider = LLMProvider.OPENROUTER
    default_model = "openai/gpt-4o"  # High performance via OpenRouter

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Send completion to OpenRouter API."""
        start_time = time.time()
        endpoint = "https://openrouter.ai/api/v1/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            request_body["response_format"] = {"type": "json_object"}

        response = self._client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "X-Title": "Second Brain Assistant",
            },
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()

        latency_ms = int((time.time() - start_time) * 1000)

        # Extract text (OpenAI-compatible format)
        text = ""
        choices = data.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")

        # Extract usage
        usage = data.get("usage", {})
        tokens_input = usage.get("prompt_tokens", self._estimate_tokens(prompt))
        tokens_output = usage.get("completion_tokens", self._estimate_tokens(text))

        return LLMResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=latency_ms,
            cost_usd=estimate_cost(self.model, tokens_input, tokens_output),
            raw_response=data,
        )


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        tokens_per_minute: int = 100_000,
    ) -> None:
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self._request_timestamps: list[datetime] = []
        self._token_usage: list[tuple[datetime, int]] = []

    def _cleanup_old_entries(self, now: datetime) -> None:
        """Remove entries older than 1 minute."""
        cutoff = now - timedelta(minutes=1)
        self._request_timestamps = [ts for ts in self._request_timestamps if ts > cutoff]
        self._token_usage = [(ts, t) for ts, t in self._token_usage if ts > cutoff]

    def can_request(self, estimated_tokens: int = 100) -> bool:
        """Check if we can make a request within rate limits."""
        now = datetime.now()
        self._cleanup_old_entries(now)

        if len(self._request_timestamps) >= self.requests_per_minute:
            return False

        current_tokens = sum(t for _, t in self._token_usage)
        if current_tokens + estimated_tokens > self.tokens_per_minute:
            return False

        return True

    def record_request(self, tokens_used: int) -> None:
        """Record a completed request."""
        now = datetime.now()
        self._request_timestamps.append(now)
        self._token_usage.append((now, tokens_used))

    def wait_time_seconds(self) -> float:
        """Return seconds to wait before next request is allowed."""
        now = datetime.now()
        self._cleanup_old_entries(now)

        if len(self._request_timestamps) < self.requests_per_minute:
            current_tokens = sum(t for _, t in self._token_usage)
            if current_tokens < self.tokens_per_minute:
                return 0.0

        if not self._request_timestamps:
            return 0.0

        oldest = min(self._request_timestamps)
        wait = (oldest + timedelta(minutes=1) - now).total_seconds()
        return max(0.0, wait)


class LLMClient:
    """Provider-agnostic LLM client with fallback and cost tracking."""

    def __init__(
        self,
        *,
        gemini_api_key: str = "",
        openai_api_key: str = "",
        anthropic_api_key: str = "",
        openrouter_api_key: str = "",
        primary_provider: LLMProvider | None = None,
        fallback_order: list[LLMProvider] | None = None,
        rate_limit_requests_per_minute: int = 60,
        rate_limit_tokens_per_minute: int = 100_000,
        daily_budget_usd: float = 100.0,  # High budget for performance-first usage
        timeout: float = 30.0,
    ) -> None:
        self._providers: dict[LLMProvider, BaseLLMProvider] = {}
        self._stats: dict[LLMProvider, LLMUsageStats] = defaultdict(LLMUsageStats)
        self._rate_limiters: dict[LLMProvider, RateLimiter] = {}
        self.daily_budget_usd = daily_budget_usd
        self._daily_cost_usd = 0.0
        self._daily_reset_date = datetime.now().date()

        # Initialize providers
        if gemini_api_key:
            self._providers[LLMProvider.GEMINI] = GeminiProvider(
                api_key=gemini_api_key, timeout=timeout
            )
            self._rate_limiters[LLMProvider.GEMINI] = RateLimiter(
                rate_limit_requests_per_minute, rate_limit_tokens_per_minute
            )

        if openai_api_key:
            self._providers[LLMProvider.OPENAI] = OpenAIProvider(
                api_key=openai_api_key, timeout=timeout
            )
            self._rate_limiters[LLMProvider.OPENAI] = RateLimiter(
                rate_limit_requests_per_minute, rate_limit_tokens_per_minute
            )

        if anthropic_api_key:
            self._providers[LLMProvider.ANTHROPIC] = AnthropicProvider(
                api_key=anthropic_api_key, timeout=timeout
            )
            self._rate_limiters[LLMProvider.ANTHROPIC] = RateLimiter(
                rate_limit_requests_per_minute, rate_limit_tokens_per_minute
            )

        if openrouter_api_key:
            self._providers[LLMProvider.OPENROUTER] = OpenRouterProvider(
                api_key=openrouter_api_key, timeout=timeout
            )
            self._rate_limiters[LLMProvider.OPENROUTER] = RateLimiter(
                rate_limit_requests_per_minute, rate_limit_tokens_per_minute
            )

        # Determine provider order
        self._primary: LLMProvider | None = None
        if primary_provider and primary_provider in self._providers:
            self._primary = primary_provider
        elif self._providers:
            # Default priority: Gemini (fastest) > OpenAI > Anthropic > OpenRouter
            priority_order = [
                LLMProvider.GEMINI,
                LLMProvider.OPENAI,
                LLMProvider.ANTHROPIC,
                LLMProvider.OPENROUTER,
            ]
            for p in priority_order:
                if p in self._providers:
                    self._primary = p
                    break

        if fallback_order:
            self._fallback_order = [p for p in fallback_order if p in self._providers]
        else:
            priority_order = [
                LLMProvider.GEMINI,
                LLMProvider.OPENAI,
                LLMProvider.ANTHROPIC,
                LLMProvider.OPENROUTER,
            ]
            self._fallback_order = [
                p for p in priority_order if p in self._providers and p != self._primary
            ]

    @property
    def available_providers(self) -> list[LLMProvider]:
        """List of configured providers."""
        return list(self._providers.keys())

    @property
    def primary_provider(self) -> LLMProvider | None:
        """The primary provider to use."""
        return self._primary

    @property
    def is_available(self) -> bool:
        """True if at least one provider is configured."""
        return len(self._providers) > 0

    def _check_daily_budget(self) -> bool:
        """Check if we're within daily budget. Resets at midnight."""
        today = datetime.now().date()
        if today > self._daily_reset_date:
            self._daily_cost_usd = 0.0
            self._daily_reset_date = today
        return self._daily_cost_usd < self.daily_budget_usd

    def _get_provider_order(self) -> list[LLMProvider]:
        """Get ordered list of providers to try."""
        if self._primary is None:
            return list(self._fallback_order)
        return [self._primary] + [p for p in self._fallback_order if p != self._primary]

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        json_mode: bool = False,
        provider: LLMProvider | None = None,
    ) -> LLMResponse:
        """Send completion request with automatic fallback.

        Args:
            prompt: The user prompt
            system_prompt: Optional system instructions
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum response tokens
            json_mode: Request JSON-formatted response
            provider: Force specific provider (skips fallback)

        Returns:
            LLMResponse with text and metadata

        Raises:
            RuntimeError: If no providers available or all fail
        """
        if not self.is_available:
            raise RuntimeError("No LLM providers configured")

        if not self._check_daily_budget():
            raise RuntimeError(
                f"Daily budget exhausted (${self._daily_cost_usd:.2f}/${self.daily_budget_usd:.2f})"
            )

        providers_to_try = (
            [provider] if provider and provider in self._providers else self._get_provider_order()
        )

        errors: list[tuple[LLMProvider, Exception]] = []

        for p in providers_to_try:
            rate_limiter = self._rate_limiters.get(p)
            if rate_limiter and not rate_limiter.can_request():
                logger.warning(
                    "Rate limit reached for %s, wait %.1fs",
                    p.value,
                    rate_limiter.wait_time_seconds(),
                )
                continue

            try:
                provider_impl = self._providers[p]
                response = provider_impl.complete(
                    prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )

                # Update stats
                stats = self._stats[p]
                stats.total_requests += 1
                stats.total_tokens_input += response.tokens_input
                stats.total_tokens_output += response.tokens_output
                stats.total_cost_usd += response.cost_usd
                stats.total_latency_ms += response.latency_ms
                stats.last_request_at = datetime.now()

                # Update rate limiter
                if rate_limiter:
                    rate_limiter.record_request(response.total_tokens)

                # Track daily cost
                self._daily_cost_usd += response.cost_usd

                return response

            except Exception as e:
                logger.warning("Provider %s failed: %s", p.value, e)
                errors.append((p, e))
                self._stats[p].errors += 1

        # All providers failed
        error_summary = "; ".join(f"{p.value}: {e}" for p, e in errors)
        raise RuntimeError(f"All LLM providers failed: {error_summary}")

    def get_stats(self, provider: LLMProvider | None = None) -> dict[str, Any]:
        """Get usage statistics.

        Args:
            provider: Specific provider, or None for all

        Returns:
            Dict with usage stats
        """
        if provider:
            s = self._stats[provider]
            return {
                "provider": provider.value,
                "requests": s.total_requests,
                "tokens_input": s.total_tokens_input,
                "tokens_output": s.total_tokens_output,
                "cost_usd": round(s.total_cost_usd, 4),
                "avg_latency_ms": round(s.avg_latency_ms, 1),
                "errors": s.errors,
            }

        return {
            "daily_cost_usd": round(self._daily_cost_usd, 4),
            "daily_budget_usd": self.daily_budget_usd,
            "providers": {p.value: self.get_stats(p) for p in self._providers.keys()},
        }

    def close(self) -> None:
        """Close all provider clients."""
        for provider in self._providers.values():
            provider.close()


# Module-level singleton
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get or create the singleton LLM client."""
    global _client
    if _client is None:
        from assistant.config import settings

        _client = LLMClient(
            gemini_api_key=settings.gemini_api_key,
            openai_api_key=settings.openai_api_key,
            anthropic_api_key=getattr(settings, "anthropic_api_key", ""),
            openrouter_api_key=getattr(settings, "openrouter_api_key", ""),
        )
    return _client


def is_llm_available() -> bool:
    """Check if LLM services are available."""
    return get_llm_client().is_available


def llm_complete(
    prompt: str,
    *,
    system_prompt: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    json_mode: bool = False,
) -> LLMResponse:
    """Convenience function for completions."""
    return get_llm_client().complete(
        prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )
