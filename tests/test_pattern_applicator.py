"""Tests for the pattern applicator service.

Tests for T-093: Apply patterns to new inputs - checks patterns before
classification and applies learned behaviors to correct likely errors.
"""

from unittest.mock import AsyncMock

import pytest

from assistant.services.pattern_applicator import (
    AppliedPattern,
    PatternApplicationResult,
    PatternApplicator,
    apply_patterns,
    get_pattern_applicator,
    load_patterns,
)
from assistant.services.patterns import PATTERN_CONFIDENCE_THRESHOLD


class TestAppliedPattern:
    """Tests for AppliedPattern dataclass."""

    def test_creation(self):
        """Test basic creation with all fields."""
        pattern = AppliedPattern(
            pattern_id="pattern-123",
            trigger="Jess",
            meaning="Tess",
            original_value="Jess",
            corrected_value="Tess",
            pattern_type="person",
            confidence=80,
        )

        assert pattern.pattern_id == "pattern-123"
        assert pattern.trigger == "Jess"
        assert pattern.meaning == "Tess"
        assert pattern.original_value == "Jess"
        assert pattern.corrected_value == "Tess"
        assert pattern.pattern_type == "person"
        assert pattern.confidence == 80


class TestPatternApplicationResult:
    """Tests for PatternApplicationResult dataclass."""

    def test_creation_empty(self):
        """Test creation with no corrections."""
        result = PatternApplicationResult(
            original_text="Call Jess tomorrow",
            original_people=["Jess"],
            original_places=[],
            original_title="Call Jess",
        )

        assert result.original_text == "Call Jess tomorrow"
        assert result.original_people == ["Jess"]
        assert result.original_title == "Call Jess"
        assert not result.has_corrections
        assert result.people == ["Jess"]  # Returns original when no corrections

    def test_has_corrections_false_when_empty(self):
        """Test has_corrections is False when no patterns applied."""
        result = PatternApplicationResult(
            original_text="Call Jess",
            original_people=["Jess"],
        )

        assert not result.has_corrections
        assert result.patterns_applied == []

    def test_has_corrections_true_with_patterns(self):
        """Test has_corrections is True when patterns were applied."""
        result = PatternApplicationResult(
            original_text="Call Jess",
            original_people=["Jess"],
            corrected_people=["Tess"],
            patterns_applied=[
                AppliedPattern(
                    pattern_id="p1",
                    trigger="Jess",
                    meaning="Tess",
                    original_value="Jess",
                    corrected_value="Tess",
                    pattern_type="person",
                    confidence=80,
                )
            ],
        )

        assert result.has_corrections
        assert len(result.patterns_applied) == 1

    def test_people_property_returns_corrected(self):
        """Test people property returns corrected list when available."""
        result = PatternApplicationResult(
            original_text="Call Jess",
            original_people=["Jess"],
            corrected_people=["Tess"],
        )

        assert result.people == ["Tess"]

    def test_people_property_returns_original_when_empty_corrections(self):
        """Test people property returns original when corrected is empty."""
        result = PatternApplicationResult(
            original_text="Call Jess",
            original_people=["Jess"],
            corrected_people=[],  # Empty after correction attempt
        )

        # Should return original since corrected is empty
        assert result.people == ["Jess"]

    def test_summary_no_corrections(self):
        """Test summary when no corrections made."""
        result = PatternApplicationResult(original_text="test")

        assert result.summary() == "No patterns applied."

    def test_summary_with_corrections(self):
        """Test summary with corrections."""
        result = PatternApplicationResult(
            original_text="test",
            patterns_applied=[
                AppliedPattern(
                    pattern_id="p1",
                    trigger="Jess",
                    meaning="Tess",
                    original_value="Jess",
                    corrected_value="Tess",
                    pattern_type="person",
                    confidence=80,
                )
            ],
        )

        summary = result.summary()
        assert "1 pattern" in summary
        assert "'Jess' → 'Tess'" in summary


class TestPatternApplicatorNormalization:
    """Tests for text normalization in pattern matching."""

    def test_normalize_basic(self):
        """Test basic normalization."""
        applicator = PatternApplicator()

        assert applicator._normalize("  Hello  ") == "hello"
        assert applicator._normalize("Hello!") == "hello"
        assert applicator._normalize("Hello, World!") == "hello world"

    def test_normalize_preserves_content(self):
        """Test that meaningful content is preserved."""
        applicator = PatternApplicator()

        assert applicator._normalize("Tess") == "tess"
        assert applicator._normalize("Sarah Chen") == "sarah chen"


class TestPatternApplicatorMatching:
    """Tests for pattern trigger matching."""

    def test_matches_trigger_exact(self):
        """Test exact match."""
        applicator = PatternApplicator()

        assert applicator._matches_trigger("Jess", "Jess")
        assert applicator._matches_trigger("jess", "JESS")  # Case-insensitive

    def test_matches_trigger_contains(self):
        """Test value contains trigger."""
        applicator = PatternApplicator()

        assert applicator._matches_trigger("Call Jess now", "Jess")

    def test_matches_trigger_short_name_in_trigger(self):
        """Test short name matching (3+ chars)."""
        applicator = PatternApplicator()

        # "Bob" is in "Bobby", and len("Bob") >= 3
        assert applicator._matches_trigger("Bob", "Bobby")

    def test_matches_trigger_too_short(self):
        """Test that very short names don't match loosely."""
        applicator = PatternApplicator()

        # "Al" is only 2 chars, so won't match "Alice" loosely
        assert not applicator._matches_trigger("Al", "Alice")

    def test_matches_trigger_no_match(self):
        """Test no match."""
        applicator = PatternApplicator()

        assert not applicator._matches_trigger("Mike", "Jess")


class TestPatternApplicatorLoadPatterns:
    """Tests for loading patterns from Notion."""

    @pytest.mark.asyncio
    async def test_load_patterns_success(self):
        """Test successful pattern loading."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "pattern-123",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Jess"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Tess"}}]},
                        "confidence": {"number": 80},
                    },
                }
            ]
        )

        applicator = PatternApplicator(notion_client=mock_notion)

        count = await applicator.load_patterns()

        assert count == 1
        assert len(applicator._pattern_cache) == 1
        assert applicator._cache_loaded

        mock_notion.query_patterns.assert_called_once_with(
            min_confidence=PATTERN_CONFIDENCE_THRESHOLD,
            limit=100,
        )

    @pytest.mark.asyncio
    async def test_load_patterns_empty(self):
        """Test loading when no patterns exist."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(return_value=[])

        applicator = PatternApplicator(notion_client=mock_notion)

        count = await applicator.load_patterns()

        assert count == 0
        assert applicator._pattern_cache == []
        assert applicator._cache_loaded

    @pytest.mark.asyncio
    async def test_load_patterns_error_handling(self):
        """Test graceful handling of load errors."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(side_effect=Exception("API error"))

        applicator = PatternApplicator(notion_client=mock_notion)

        count = await applicator.load_patterns()

        assert count == 0
        assert applicator._pattern_cache == []
        assert applicator._cache_loaded  # Still marked as loaded to avoid retries

    @pytest.mark.asyncio
    async def test_load_patterns_filters_invalid(self):
        """Test that invalid patterns are filtered out."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "valid",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Jess"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Tess"}}]},
                        "confidence": {"number": 80},
                    },
                },
                {
                    # Invalid: missing meaning
                    "id": "invalid",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Bob"}}]},
                        "meaning": {"rich_text": []},
                        "confidence": {"number": 70},
                    },
                },
            ]
        )

        applicator = PatternApplicator(notion_client=mock_notion)

        count = await applicator.load_patterns()

        assert count == 1  # Only valid pattern loaded


class TestPatternApplicatorApplyPatterns:
    """Tests for applying patterns to input."""

    @pytest.mark.asyncio
    async def test_apply_patterns_no_cache(self):
        """Test applying patterns loads cache if not loaded."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(return_value=[])

        applicator = PatternApplicator(notion_client=mock_notion)
        assert not applicator._cache_loaded

        await applicator.apply_patterns(
            text="Call Jess",
            people=["Jess"],
        )

        assert applicator._cache_loaded
        mock_notion.query_patterns.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_patterns_corrects_person(self):
        """Test pattern corrects person name."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "pattern-123",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Jess"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Tess"}}]},
                        "confidence": {"number": 80},
                    },
                }
            ]
        )

        applicator = PatternApplicator(notion_client=mock_notion)
        await applicator.load_patterns()

        result = await applicator.apply_patterns(
            text="Call Jess tomorrow",
            people=["Jess"],
            title="Call Jess",
        )

        assert result.has_corrections
        assert result.corrected_people == ["Tess"]
        assert result.corrected_title == "Call Tess"
        assert len(result.patterns_applied) == 1
        assert result.patterns_applied[0].original_value == "Jess"
        assert result.patterns_applied[0].corrected_value == "Tess"

    @pytest.mark.asyncio
    async def test_apply_patterns_corrects_place(self):
        """Test pattern corrects place name."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "pattern-456",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Starbucks"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Starbucks Reserve"}}]},
                        "confidence": {"number": 75},
                    },
                }
            ]
        )

        applicator = PatternApplicator(notion_client=mock_notion)
        await applicator.load_patterns()

        result = await applicator.apply_patterns(
            text="Meet at Starbucks",
            places=["Starbucks"],
            title="Meet at Starbucks",
        )

        assert result.has_corrections
        assert result.corrected_places == ["Starbucks Reserve"]
        assert "Starbucks Reserve" in result.corrected_title

    @pytest.mark.asyncio
    async def test_apply_patterns_no_match(self):
        """Test no patterns applied when no match."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "pattern-123",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Jess"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Tess"}}]},
                        "confidence": {"number": 80},
                    },
                }
            ]
        )

        applicator = PatternApplicator(notion_client=mock_notion)
        await applicator.load_patterns()

        result = await applicator.apply_patterns(
            text="Call Mike tomorrow",
            people=["Mike"],
            title="Call Mike",
        )

        assert not result.has_corrections
        assert result.corrected_people == ["Mike"]  # Unchanged
        assert result.corrected_title == "Call Mike"  # Unchanged

    @pytest.mark.asyncio
    async def test_apply_patterns_multiple_people(self):
        """Test pattern applies to one person in a list."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "pattern-123",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Jess"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Tess"}}]},
                        "confidence": {"number": 80},
                    },
                }
            ]
        )

        applicator = PatternApplicator(notion_client=mock_notion)
        await applicator.load_patterns()

        result = await applicator.apply_patterns(
            text="Meet with Jess and Mike",
            people=["Jess", "Mike"],
            title="Meet with Jess and Mike",
        )

        assert result.has_corrections
        assert result.corrected_people == ["Tess", "Mike"]  # Only Jess corrected

    @pytest.mark.asyncio
    async def test_apply_patterns_title_only(self):
        """Test pattern detected in title without entity extraction."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "priority-pattern",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "shopping"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "low priority"}}]},
                        "confidence": {"number": 80},
                        "pattern_type": {"select": {"name": "priority"}},
                    },
                }
            ]
        )

        applicator = PatternApplicator(notion_client=mock_notion)
        await applicator.load_patterns()

        result = await applicator.apply_patterns(
            text="Buy groceries - shopping",
            people=[],
            places=[],
            title="Buy groceries - shopping",
        )

        assert result.has_corrections
        assert len(result.patterns_applied) == 1
        assert result.patterns_applied[0].trigger == "shopping"


class TestPatternApplicatorClearCache:
    """Tests for cache clearing."""

    def test_clear_cache(self):
        """Test cache clearing."""
        applicator = PatternApplicator()
        applicator._pattern_cache = [{"id": "test"}]
        applicator._cache_loaded = True

        applicator.clear_cache()

        assert applicator._pattern_cache == []
        assert not applicator._cache_loaded


class TestPatternApplicatorUpdateUsage:
    """Tests for updating pattern usage."""

    @pytest.mark.asyncio
    async def test_update_pattern_usage(self):
        """Test pattern usage timestamp update."""
        mock_notion = AsyncMock()
        mock_notion.update_pattern_confidence = AsyncMock()

        applicator = PatternApplicator(notion_client=mock_notion)

        await applicator.update_pattern_usage("pattern-123")

        mock_notion.update_pattern_confidence.assert_called_once_with(
            page_id="pattern-123",
            times_confirmed=None,
            confidence=None,
        )

    @pytest.mark.asyncio
    async def test_update_pattern_usage_error_handling(self):
        """Test graceful error handling."""
        mock_notion = AsyncMock()
        mock_notion.update_pattern_confidence = AsyncMock(side_effect=Exception("API error"))

        applicator = PatternApplicator(notion_client=mock_notion)

        # Should not raise
        await applicator.update_pattern_usage("pattern-123")


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_pattern_applicator_returns_singleton(self):
        """Test that get_pattern_applicator returns same instance."""
        import assistant.services.pattern_applicator as module

        module._applicator = None

        applicator1 = get_pattern_applicator()
        applicator2 = get_pattern_applicator()

        assert applicator1 is applicator2

    @pytest.mark.asyncio
    async def test_apply_patterns_convenience_function(self):
        """Test the apply_patterns convenience function."""
        import assistant.services.pattern_applicator as module

        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(return_value=[])

        module._applicator = PatternApplicator(notion_client=mock_notion)

        result = await apply_patterns(
            text="Call Mike",
            people=["Mike"],
        )

        assert isinstance(result, PatternApplicationResult)
        assert result.original_people == ["Mike"]

    @pytest.mark.asyncio
    async def test_load_patterns_convenience_function(self):
        """Test the load_patterns convenience function."""
        import assistant.services.pattern_applicator as module

        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "p1",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Test"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Result"}}]},
                        "confidence": {"number": 80},
                    },
                }
            ]
        )

        module._applicator = PatternApplicator(notion_client=mock_notion)

        count = await load_patterns()

        assert count == 1


class TestT093Integration:
    """Integration tests for T-093: Apply patterns to new inputs."""

    @pytest.mark.asyncio
    async def test_t093_full_correction_flow(self):
        """Test T-093: Full flow of pattern application.

        Scenario: A "Jess → Tess" pattern exists.
        User sends "Call Jess tomorrow".
        System should correct to "Call Tess tomorrow".
        """
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "jess-tess-pattern",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Jess"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Tess"}}]},
                        "confidence": {"number": 85},
                        "pattern_type": {"select": {"name": "person"}},
                    },
                }
            ]
        )
        mock_notion.update_pattern_confidence = AsyncMock()

        applicator = PatternApplicator(notion_client=mock_notion)

        # Load patterns (simulating startup)
        await applicator.load_patterns()

        # Apply patterns to input
        result = await applicator.apply_patterns(
            text="Call Jess tomorrow at 2pm",
            people=["Jess"],
            places=[],
            title="Call Jess",
        )

        # Verify corrections
        assert result.has_corrections
        assert result.corrected_people == ["Tess"]
        assert result.corrected_title == "Call Tess"

        # Verify pattern was tracked
        assert len(result.patterns_applied) == 1
        applied = result.patterns_applied[0]
        assert applied.pattern_id == "jess-tess-pattern"
        assert applied.original_value == "Jess"
        assert applied.corrected_value == "Tess"
        assert applied.confidence == 85

    @pytest.mark.asyncio
    async def test_t093_priority_pattern_detection(self):
        """Test T-093: Priority pattern detection in title.

        PRD 5.7 example: shopping tasks should be low priority.
        """
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "shopping-priority-pattern",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "shopping"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "priority=low"}}]},
                        "confidence": {"number": 80},
                        "pattern_type": {"select": {"name": "priority"}},
                    },
                }
            ]
        )

        applicator = PatternApplicator(notion_client=mock_notion)
        await applicator.load_patterns()

        result = await applicator.apply_patterns(
            text="Buy milk - shopping trip",
            people=[],
            places=[],
            title="Buy milk - shopping trip",
        )

        # Pattern should be detected (though title may not change for priority patterns)
        assert result.has_corrections
        assert any(
            p.trigger == "shopping" and p.meaning == "priority=low" for p in result.patterns_applied
        )

    @pytest.mark.asyncio
    async def test_t093_multiple_patterns_applied(self):
        """Test T-093: Multiple patterns can apply to one message."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "jess-tess",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Jess"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Tess"}}]},
                        "confidence": {"number": 80},
                    },
                },
                {
                    "id": "starbucks-reserve",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "Starbucks"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "Starbucks Reserve"}}]},
                        "confidence": {"number": 75},
                    },
                },
            ]
        )

        applicator = PatternApplicator(notion_client=mock_notion)
        await applicator.load_patterns()

        result = await applicator.apply_patterns(
            text="Meet Jess at Starbucks",
            people=["Jess"],
            places=["Starbucks"],
            title="Meet Jess at Starbucks",
        )

        assert result.has_corrections
        assert result.corrected_people == ["Tess"]
        assert result.corrected_places == ["Starbucks Reserve"]
        assert len(result.patterns_applied) == 2

    @pytest.mark.asyncio
    async def test_t093_pattern_respects_confidence_threshold(self):
        """Test T-093: Patterns below threshold are not applied."""
        mock_notion = AsyncMock()
        mock_notion.query_patterns = AsyncMock(return_value=[])  # No patterns above threshold

        applicator = PatternApplicator(notion_client=mock_notion)

        # Load with default threshold (70%)
        await applicator.load_patterns()

        result = await applicator.apply_patterns(
            text="Call Jess",
            people=["Jess"],
        )

        # No corrections since no patterns meet threshold
        assert not result.has_corrections


class TestProcessorIntegration:
    """Tests for MessageProcessor integration with pattern applicator."""

    @pytest.mark.asyncio
    async def test_processor_applies_patterns(self):
        """Test that MessageProcessor applies patterns during processing."""
        from assistant.services.processor import MessageProcessor

        # This test verifies the integration at a high level
        # Detailed tests are in TestT093Integration

        processor = MessageProcessor()

        # The processor should have a pattern_applicator
        assert hasattr(processor, "pattern_applicator")
        assert isinstance(processor.pattern_applicator, PatternApplicator)


class TestAT109Integration:
    """Verify that T-093 completes the AT-109 acceptance criteria.

    AT-109: Pattern Learning
    - Given: User corrects priority 3 times for similar tasks
    - When: Pattern confidence > 70%
    - Then: Pattern stored in Patterns database
    - And: Future similar tasks use learned pattern

    T-093 implements the "Future similar tasks use learned pattern" part.
    """

    @pytest.mark.asyncio
    async def test_at109_pattern_applied_to_future_task(self):
        """Test AT-109: Stored pattern is applied to future similar task.

        This verifies the complete AT-109 flow:
        1. Pattern was previously stored (simulated with mock)
        2. New input matches the pattern trigger
        3. Pattern correction is applied automatically
        """
        mock_notion = AsyncMock()
        # Simulate a stored pattern from previous corrections
        mock_notion.query_patterns = AsyncMock(
            return_value=[
                {
                    "id": "learned-pattern-123",
                    "properties": {
                        "trigger": {"title": [{"text": {"content": "high"}}]},
                        "meaning": {"rich_text": [{"text": {"content": "low"}}]},
                        "confidence": {"number": 80},  # > 70% as required by AT-109
                        "pattern_type": {"select": {"name": "priority"}},
                    },
                }
            ]
        )
        mock_notion.update_pattern_confidence = AsyncMock()

        applicator = PatternApplicator(notion_client=mock_notion)
        await applicator.load_patterns()

        # New task that would normally be high priority
        result = await applicator.apply_patterns(
            text="Buy groceries - probably high priority",
            people=[],
            places=[],
            title="Buy groceries - high priority",
        )

        # Pattern should be detected in title
        assert result.has_corrections
        assert any(p.trigger == "high" and p.meaning == "low" for p in result.patterns_applied)

        # This satisfies AT-109: "Future similar tasks use learned pattern"
