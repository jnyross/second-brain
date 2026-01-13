"""Tests for LLM provider abstraction layer (T-213)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from assistant.services.llm_client import (
    AnthropicProvider,
    GeminiProvider,
    LLMClient,
    LLMProvider,
    LLMResponse,
    LLMUsageStats,
    OpenAIProvider,
    RateLimiter,
    estimate_cost,
    get_llm_client,
    is_llm_available,
)

# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


class FakeResponse:
    """Mock HTTP response."""

    def __init__(self, data: dict[str, Any], status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._data


class FakeClient:
    """Mock HTTP client."""

    def __init__(self, response: dict[str, Any], status_code: int = 200) -> None:
        self.response = response
        self.status_code = status_code
        self.requests: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        return FakeResponse(self.response, self.status_code)

    def close(self) -> None:
        pass


def make_gemini_response(text: str, input_tokens: int = 10, output_tokens: int = 20) -> dict:
    """Create a mock Gemini API response."""
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {
            "promptTokenCount": input_tokens,
            "candidatesTokenCount": output_tokens,
        },
    }


def make_openai_response(text: str, input_tokens: int = 10, output_tokens: int = 20) -> dict:
    """Create a mock OpenAI API response."""
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


def make_anthropic_response(text: str, input_tokens: int = 10, output_tokens: int = 20) -> dict:
    """Create a mock Anthropic API response."""
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test: LLMResponse
# ─────────────────────────────────────────────────────────────────────────────


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_total_tokens_calculation(self) -> None:
        """Total tokens should be sum of input and output."""
        response = LLMResponse(
            text="Hello",
            provider=LLMProvider.GEMINI,
            model="gemini-2.5-flash-lite",
            tokens_input=100,
            tokens_output=50,
        )
        assert response.total_tokens == 150

    def test_default_values(self) -> None:
        """Default values should be sensible."""
        response = LLMResponse(
            text="Test",
            provider=LLMProvider.OPENAI,
            model="gpt-4o-mini",
        )
        assert response.tokens_input == 0
        assert response.tokens_output == 0
        assert response.cost_usd == 0.0
        assert response.raw_response == {}


class TestLLMUsageStats:
    """Tests for LLMUsageStats dataclass."""

    def test_avg_latency_zero_requests(self) -> None:
        """Average latency should be 0 with no requests."""
        stats = LLMUsageStats()
        assert stats.avg_latency_ms == 0.0

    def test_avg_latency_calculation(self) -> None:
        """Average latency should be correctly calculated."""
        stats = LLMUsageStats(total_requests=4, total_latency_ms=1000)
        assert stats.avg_latency_ms == 250.0


# ─────────────────────────────────────────────────────────────────────────────
# Test: Cost Estimation
# ─────────────────────────────────────────────────────────────────────────────


class TestEstimateCost:
    """Tests for cost estimation."""

    def test_known_model_cost(self) -> None:
        """Cost should be calculated correctly for known models."""
        # gemini-2.5-flash-lite: $0.075 input, $0.30 output per 1M tokens
        cost = estimate_cost("gemini-2.5-flash-lite", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.375, rel=0.01)

    def test_gpt4o_mini_cost(self) -> None:
        """GPT-4o-mini cost should be correct."""
        # $0.15 input, $0.60 output per 1M tokens
        cost = estimate_cost("gpt-4o-mini", 1_000_000, 500_000)
        assert cost == pytest.approx(0.45, rel=0.01)

    def test_unknown_model_default(self) -> None:
        """Unknown models should use conservative default."""
        cost = estimate_cost("unknown-model-xyz", 1000, 500)
        # Default: 1.0 input, 3.0 output per 1M
        assert cost > 0

    def test_zero_tokens(self) -> None:
        """Zero tokens should have zero cost."""
        assert estimate_cost("gpt-4o-mini", 0, 0) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Test: Rate Limiter
# ─────────────────────────────────────────────────────────────────────────────


class TestRateLimiter:
    """Tests for RateLimiter."""

    def test_can_request_when_empty(self) -> None:
        """Should allow requests when limits not reached."""
        limiter = RateLimiter(requests_per_minute=10, tokens_per_minute=1000)
        assert limiter.can_request(estimated_tokens=100)

    def test_blocks_at_request_limit(self) -> None:
        """Should block when request limit reached."""
        limiter = RateLimiter(requests_per_minute=2, tokens_per_minute=10000)
        limiter.record_request(50)
        limiter.record_request(50)
        assert not limiter.can_request()

    def test_blocks_at_token_limit(self) -> None:
        """Should block when token limit reached."""
        limiter = RateLimiter(requests_per_minute=100, tokens_per_minute=100)
        limiter.record_request(90)
        assert not limiter.can_request(estimated_tokens=20)

    def test_wait_time_when_limited(self) -> None:
        """Should return positive wait time when limited."""
        limiter = RateLimiter(requests_per_minute=1, tokens_per_minute=10000)
        limiter.record_request(10)
        wait = limiter.wait_time_seconds()
        assert wait > 0
        assert wait <= 60.0

    def test_wait_time_when_available(self) -> None:
        """Should return 0 wait time when available."""
        limiter = RateLimiter(requests_per_minute=100, tokens_per_minute=10000)
        assert limiter.wait_time_seconds() == 0.0

    def test_cleanup_old_entries(self) -> None:
        """Old entries should be cleaned up."""
        limiter = RateLimiter(requests_per_minute=10, tokens_per_minute=1000)
        # Simulate old entries by manipulating internal state
        old_time = datetime.now() - timedelta(minutes=2)
        limiter._request_timestamps = [old_time]
        limiter._token_usage = [(old_time, 500)]
        # New request should clean up old entries
        assert limiter.can_request(100)


# ─────────────────────────────────────────────────────────────────────────────
# Test: Gemini Provider
# ─────────────────────────────────────────────────────────────────────────────


class TestGeminiProvider:
    """Tests for GeminiProvider."""

    def test_complete_basic(self) -> None:
        """Basic completion should work."""
        client = FakeClient(make_gemini_response("Hello, world!"))
        provider = GeminiProvider(api_key="test-key", client=client)

        response = provider.complete("Say hello")

        assert response.text == "Hello, world!"
        assert response.provider == LLMProvider.GEMINI
        assert response.model == "gemini-2.5-flash-lite"

    def test_complete_with_system_prompt(self) -> None:
        """System prompt should be included in request."""
        client = FakeClient(make_gemini_response("OK"))
        provider = GeminiProvider(api_key="test-key", client=client)

        provider.complete("Hello", system_prompt="Be helpful")

        request = client.requests[0]
        contents = request["json"]["contents"]
        # System prompt becomes first user/model pair
        assert len(contents) >= 2

    def test_complete_json_mode(self) -> None:
        """JSON mode should set response_mime_type."""
        client = FakeClient(make_gemini_response('{"answer": 42}'))
        provider = GeminiProvider(api_key="test-key", client=client)

        provider.complete("Give JSON", json_mode=True)

        request = client.requests[0]
        assert request["json"]["generationConfig"]["response_mime_type"] == "application/json"

    def test_tracks_usage(self) -> None:
        """Should track token usage from response."""
        client = FakeClient(make_gemini_response("Hello", input_tokens=50, output_tokens=30))
        provider = GeminiProvider(api_key="test-key", client=client)

        response = provider.complete("Test")

        assert response.tokens_input == 50
        assert response.tokens_output == 30
        assert response.cost_usd > 0

    def test_uses_correct_endpoint(self) -> None:
        """Should call correct Gemini endpoint."""
        client = FakeClient(make_gemini_response("OK"))
        provider = GeminiProvider(api_key="test-key", model="gemini-2.5-pro", client=client)

        provider.complete("Test")

        request = client.requests[0]
        assert "gemini-2.5-pro" in request["url"]
        assert request["params"]["key"] == "test-key"


# ─────────────────────────────────────────────────────────────────────────────
# Test: OpenAI Provider
# ─────────────────────────────────────────────────────────────────────────────


class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    def test_complete_basic(self) -> None:
        """Basic completion should work."""
        client = FakeClient(make_openai_response("Hello from GPT!"))
        provider = OpenAIProvider(api_key="sk-test", client=client)

        response = provider.complete("Say hello")

        assert response.text == "Hello from GPT!"
        assert response.provider == LLMProvider.OPENAI
        assert response.model == "gpt-4o-mini"

    def test_complete_with_system_prompt(self) -> None:
        """System prompt should be in messages."""
        client = FakeClient(make_openai_response("OK"))
        provider = OpenAIProvider(api_key="sk-test", client=client)

        provider.complete("Hello", system_prompt="You are helpful")

        request = client.requests[0]
        messages = request["json"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful"

    def test_json_mode(self) -> None:
        """JSON mode should set response_format."""
        client = FakeClient(make_openai_response('{"data": 1}'))
        provider = OpenAIProvider(api_key="sk-test", client=client)

        provider.complete("Give JSON", json_mode=True)

        request = client.requests[0]
        assert request["json"]["response_format"]["type"] == "json_object"

    def test_uses_bearer_auth(self) -> None:
        """Should use Bearer token authentication."""
        client = FakeClient(make_openai_response("OK"))
        provider = OpenAIProvider(api_key="sk-test123", client=client)

        provider.complete("Test")

        request = client.requests[0]
        assert request["headers"]["Authorization"] == "Bearer sk-test123"


# ─────────────────────────────────────────────────────────────────────────────
# Test: Anthropic Provider
# ─────────────────────────────────────────────────────────────────────────────


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    def test_complete_basic(self) -> None:
        """Basic completion should work."""
        client = FakeClient(make_anthropic_response("Hello from Claude!"))
        provider = AnthropicProvider(api_key="sk-ant-test", client=client)

        response = provider.complete("Say hello")

        assert response.text == "Hello from Claude!"
        assert response.provider == LLMProvider.ANTHROPIC
        assert response.model == "claude-3-5-haiku-20241022"

    def test_system_prompt_in_body(self) -> None:
        """System prompt should be in request body."""
        client = FakeClient(make_anthropic_response("OK"))
        provider = AnthropicProvider(api_key="sk-ant-test", client=client)

        provider.complete("Hello", system_prompt="Be concise")

        request = client.requests[0]
        assert request["json"]["system"] == "Be concise"

    def test_json_mode_appends_instruction(self) -> None:
        """JSON mode should append instruction to prompt."""
        client = FakeClient(make_anthropic_response('{"value": 1}'))
        provider = AnthropicProvider(api_key="sk-ant-test", client=client)

        provider.complete("Give data", json_mode=True)

        request = client.requests[0]
        content = request["json"]["messages"][0]["content"]
        assert "JSON" in content

    def test_uses_anthropic_headers(self) -> None:
        """Should use x-api-key and anthropic-version headers."""
        client = FakeClient(make_anthropic_response("OK"))
        provider = AnthropicProvider(api_key="sk-ant-test", client=client)

        provider.complete("Test")

        request = client.requests[0]
        assert request["headers"]["x-api-key"] == "sk-ant-test"
        assert "anthropic-version" in request["headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Test: LLM Client
# ─────────────────────────────────────────────────────────────────────────────


class TestLLMClient:
    """Tests for the main LLMClient."""

    def test_no_providers_not_available(self) -> None:
        """Client without providers should report not available."""
        client = LLMClient()
        assert not client.is_available
        assert client.available_providers == []

    def test_gemini_only(self) -> None:
        """Client with only Gemini should work."""
        client = LLMClient(gemini_api_key="test-key")
        assert client.is_available
        assert LLMProvider.GEMINI in client.available_providers
        assert client.primary_provider == LLMProvider.GEMINI

    def test_multiple_providers(self) -> None:
        """Client with multiple providers should list all."""
        client = LLMClient(
            gemini_api_key="gem-key",
            openai_api_key="sk-key",
            anthropic_api_key="ant-key",
        )
        assert len(client.available_providers) == 3
        # Gemini should be primary (cheapest)
        assert client.primary_provider == LLMProvider.GEMINI

    def test_complete_raises_without_providers(self) -> None:
        """Complete should raise if no providers configured."""
        client = LLMClient()
        with pytest.raises(RuntimeError, match="No LLM providers configured"):
            client.complete("Hello")


class TestLLMClientComplete:
    """Tests for LLMClient.complete() method."""

    def test_uses_primary_provider(self) -> None:
        """Should use primary provider by default."""
        fake = FakeClient(make_gemini_response("Response"))
        client = LLMClient(gemini_api_key="test")
        client._providers[LLMProvider.GEMINI]._client = fake
        response = client.complete("Hello")

        assert response.provider == LLMProvider.GEMINI

    def test_fallback_on_failure(self) -> None:
        """Should fallback to next provider on failure."""
        fail_client = MagicMock()
        fail_client.post.side_effect = Exception("API Error")

        success_response = make_openai_response("Success from OpenAI")
        success_client = FakeClient(success_response)

        client = LLMClient(gemini_api_key="gem", openai_api_key="oai")
        # Replace provider clients
        client._providers[LLMProvider.GEMINI]._client = fail_client
        client._providers[LLMProvider.OPENAI]._client = success_client

        response = client.complete("Test")

        assert response.provider == LLMProvider.OPENAI
        assert response.text == "Success from OpenAI"

    def test_force_specific_provider(self) -> None:
        """Should use specified provider when requested."""
        gemini_client = FakeClient(make_gemini_response("Gemini"))
        openai_client = FakeClient(make_openai_response("OpenAI"))

        client = LLMClient(gemini_api_key="gem", openai_api_key="oai")
        client._providers[LLMProvider.GEMINI]._client = gemini_client
        client._providers[LLMProvider.OPENAI]._client = openai_client

        response = client.complete("Test", provider=LLMProvider.OPENAI)

        assert response.provider == LLMProvider.OPENAI
        assert response.text == "OpenAI"

    def test_all_providers_fail_raises(self) -> None:
        """Should raise RuntimeError when all providers fail."""
        fail_client = MagicMock()
        fail_client.post.side_effect = Exception("API Error")

        client = LLMClient(gemini_api_key="gem", openai_api_key="oai")
        client._providers[LLMProvider.GEMINI]._client = fail_client
        client._providers[LLMProvider.OPENAI]._client = fail_client

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            client.complete("Test")


class TestLLMClientBudget:
    """Tests for daily budget tracking."""

    def test_tracks_daily_cost(self) -> None:
        """Should accumulate daily cost."""
        fake = FakeClient(make_gemini_response("OK", input_tokens=100, output_tokens=50))
        client = LLMClient(gemini_api_key="test", daily_budget_usd=100.0)
        client._providers[LLMProvider.GEMINI]._client = fake

        client.complete("Test 1")
        client.complete("Test 2")

        assert client._daily_cost_usd > 0

    def test_blocks_at_budget_limit(self) -> None:
        """Should raise when daily budget exhausted."""
        client = LLMClient(gemini_api_key="test", daily_budget_usd=0.0001)
        fake = FakeClient(make_gemini_response("OK", input_tokens=10000, output_tokens=10000))
        client._providers[LLMProvider.GEMINI]._client = fake

        # First request pushes over budget
        client.complete("Test")

        with pytest.raises(RuntimeError, match="Daily budget exhausted"):
            client.complete("Test again")

    def test_budget_resets_daily(self) -> None:
        """Budget should reset on new day."""
        client = LLMClient(gemini_api_key="test", daily_budget_usd=10.0)
        client._daily_cost_usd = 9.99
        client._daily_reset_date = datetime.now().date() - timedelta(days=1)

        # Check triggers reset
        assert client._check_daily_budget()
        assert client._daily_cost_usd == 0.0


class TestLLMClientStats:
    """Tests for usage statistics."""

    def test_get_stats_empty(self) -> None:
        """Stats should be empty initially."""
        client = LLMClient(gemini_api_key="test")
        stats = client.get_stats(LLMProvider.GEMINI)

        assert stats["requests"] == 0
        assert stats["cost_usd"] == 0

    def test_get_stats_after_requests(self) -> None:
        """Stats should track requests."""
        fake = FakeClient(make_gemini_response("OK", 100, 50))
        client = LLMClient(gemini_api_key="test")
        client._providers[LLMProvider.GEMINI]._client = fake

        client.complete("Test 1")
        client.complete("Test 2")

        stats = client.get_stats(LLMProvider.GEMINI)
        assert stats["requests"] == 2
        assert stats["tokens_input"] == 200
        assert stats["tokens_output"] == 100

    def test_get_all_stats(self) -> None:
        """Should return stats for all providers."""
        client = LLMClient(gemini_api_key="gem", openai_api_key="oai")
        all_stats = client.get_stats()

        assert "daily_cost_usd" in all_stats
        assert "providers" in all_stats
        assert "gemini" in all_stats["providers"]
        assert "openai" in all_stats["providers"]


class TestLLMClientRateLimiting:
    """Tests for rate limiting integration."""

    def test_skips_rate_limited_provider(self) -> None:
        """Should skip provider when rate limited."""
        gemini_client = FakeClient(make_gemini_response("Gemini"))
        openai_client = FakeClient(make_openai_response("OpenAI"))

        client = LLMClient(gemini_api_key="gem", openai_api_key="oai")
        client._providers[LLMProvider.GEMINI]._client = gemini_client
        client._providers[LLMProvider.OPENAI]._client = openai_client

        # Max out Gemini rate limiter
        limiter = client._rate_limiters[LLMProvider.GEMINI]
        for _ in range(100):
            limiter.record_request(1000)

        response = client.complete("Test")

        # Should fallback to OpenAI
        assert response.provider == LLMProvider.OPENAI


# ─────────────────────────────────────────────────────────────────────────────
# Test: Module-Level Functions
# ─────────────────────────────────────────────────────────────────────────────


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_llm_client_singleton(self) -> None:
        """Should return singleton instance."""
        import assistant.services.llm_client as module

        # Reset singleton
        module._client = None

        with patch.object(module, "LLMClient") as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance

            client1 = get_llm_client()
            client2 = get_llm_client()

            # Should only create once
            assert mock_class.call_count == 1
            assert client1 is client2

        # Reset for other tests
        module._client = None

    def test_is_llm_available(self) -> None:
        """is_llm_available should check client."""
        import assistant.services.llm_client as module

        module._client = None

        with patch.object(module, "get_llm_client") as mock:
            mock.return_value.is_available = True
            assert is_llm_available()

            mock.return_value.is_available = False
            assert not is_llm_available()

        module._client = None


# ─────────────────────────────────────────────────────────────────────────────
# Test: Provider Enum
# ─────────────────────────────────────────────────────────────────────────────


class TestLLMProviderEnum:
    """Tests for LLMProvider enum."""

    def test_values(self) -> None:
        """Enum should have expected values."""
        assert LLMProvider.GEMINI.value == "gemini"
        assert LLMProvider.OPENAI.value == "openai"
        assert LLMProvider.ANTHROPIC.value == "anthropic"

    def test_string_comparison(self) -> None:
        """Enum should work as string."""
        assert LLMProvider.GEMINI == "gemini"


# ─────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestT213Integration:
    """Integration tests for T-213 requirements."""

    def test_provider_abstraction_all_return_llm_response(self) -> None:
        """All providers should return standardized LLMResponse."""
        providers = [
            (GeminiProvider, FakeClient(make_gemini_response("Test")), "gem-key"),
            (OpenAIProvider, FakeClient(make_openai_response("Test")), "oai-key"),
            (AnthropicProvider, FakeClient(make_anthropic_response("Test")), "ant-key"),
        ]

        for provider_class, client, api_key in providers:
            provider = provider_class(api_key=api_key, client=client)
            response = provider.complete("Hello")

            assert isinstance(response, LLMResponse)
            assert response.text == "Test"
            assert isinstance(response.provider, LLMProvider)
            assert response.cost_usd >= 0
            assert response.latency_ms >= 0

    def test_automatic_fallback_chain(self) -> None:
        """Fallback should work through all providers."""
        # All fail except the last
        gem_client = MagicMock()
        gem_client.post.side_effect = Exception("Gemini down")

        oai_client = MagicMock()
        oai_client.post.side_effect = Exception("OpenAI down")

        ant_client = FakeClient(make_anthropic_response("Anthropic works!"))

        client = LLMClient(
            gemini_api_key="gem",
            openai_api_key="oai",
            anthropic_api_key="ant",
        )
        client._providers[LLMProvider.GEMINI]._client = gem_client
        client._providers[LLMProvider.OPENAI]._client = oai_client
        client._providers[LLMProvider.ANTHROPIC]._client = ant_client

        response = client.complete("Test")

        assert response.provider == LLMProvider.ANTHROPIC
        assert response.text == "Anthropic works!"

    def test_cost_tracking_across_providers(self) -> None:
        """Cost should be tracked per provider."""
        # Use larger token counts so cost > 0.0001 (rounds to non-zero at 4 decimals)
        # gemini-2.5-flash-lite: $0.075 input, $0.30 output per 1M tokens
        # 10000 input + 5000 output = (10000*0.075 + 5000*0.30) / 1M = 0.00225
        gem_client = FakeClient(make_gemini_response("Gem", 10000, 5000))
        oai_client = FakeClient(make_openai_response("OAI", 20000, 10000))

        client = LLMClient(gemini_api_key="gem", openai_api_key="oai")
        client._providers[LLMProvider.GEMINI]._client = gem_client
        client._providers[LLMProvider.OPENAI]._client = oai_client

        client.complete("Test 1")  # Uses Gemini
        client.complete("Test 2", provider=LLMProvider.OPENAI)  # Uses OpenAI

        gem_stats = client.get_stats(LLMProvider.GEMINI)
        oai_stats = client.get_stats(LLMProvider.OPENAI)

        assert gem_stats["requests"] == 1
        assert oai_stats["requests"] == 1
        assert gem_stats["cost_usd"] > 0
        assert oai_stats["cost_usd"] > 0

    def test_rate_limiting_prevents_quota_exhaustion(self) -> None:
        """Rate limiter should prevent too many requests."""
        client = LLMClient(
            gemini_api_key="gem",
            openai_api_key="oai",
            rate_limit_requests_per_minute=5,
        )

        # Fill up Gemini rate limit
        limiter = client._rate_limiters[LLMProvider.GEMINI]
        for _ in range(10):
            limiter.record_request(100)

        # Should not be able to use Gemini
        assert not limiter.can_request()

        # OpenAI should still be available
        oai_limiter = client._rate_limiters[LLMProvider.OPENAI]
        assert oai_limiter.can_request()
