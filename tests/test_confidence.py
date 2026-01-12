"""Tests for the confidence scoring service."""

from datetime import datetime

from assistant.services.confidence import (
    ConfidenceBreakdown,
    ConfidenceResult,
    ConfidenceScorer,
    calculate_confidence,
)
from assistant.services.entities import (
    ExtractedDate,
    ExtractedEntities,
    ExtractedPerson,
    ExtractedPlace,
)


class TestConfidenceScorer:
    """Test suite for ConfidenceScorer."""

    def setup_method(self):
        self.scorer = ConfidenceScorer()

    # === High Confidence Tests (≥80%) ===

    def test_clear_task_high_confidence(self):
        """Clear task with action verb and time should score ≥80%."""
        # In real usage, entities would be extracted first
        entities = ExtractedEntities(
            dates=[
                ExtractedDate(
                    datetime_value=datetime.now(),
                    confidence=95,
                    original_text="tomorrow",
                    timezone="UTC",
                    is_relative=True,
                )
            ],
            raw_text="Buy milk tomorrow",
        )
        result = self.scorer.score("Buy milk tomorrow", entities)
        assert result.score >= 80
        assert result.is_actionable is True
        assert result.needs_clarification is False

    def test_task_with_entities_high_confidence(self):
        """Task with verb and entities should boost confidence."""
        entities = ExtractedEntities(
            people=[ExtractedPerson(name="Sarah", confidence=90, context="with Sarah")],
            dates=[
                ExtractedDate(
                    datetime_value=datetime.now(),
                    confidence=95,
                    original_text="tomorrow",
                    timezone="America/Los_Angeles",
                    is_relative=True,
                )
            ],
            raw_text="Meet Sarah for lunch tomorrow",
        )
        # "Meet" is an action verb, plus entities and time
        result = self.scorer.score("Meet Sarah for lunch tomorrow", entities)
        assert result.score >= 80
        assert result.is_actionable is True

    def test_full_task_specification(self):
        """Task with verb, time, and entities should be very high confidence."""
        entities = ExtractedEntities(
            people=[ExtractedPerson(name="John", confidence=85, context="call John")],
            dates=[
                ExtractedDate(
                    datetime_value=datetime.now(),
                    confidence=90,
                    original_text="3pm",
                    timezone="UTC",
                    is_relative=False,
                )
            ],
            raw_text="Call John at 3pm",
        )
        result = self.scorer.score("Call John at 3pm", entities)
        assert result.score >= 85

    # === Low Confidence Tests (<80%) ===

    def test_filler_words_low_confidence(self):
        """Messages with filler words should score <80%."""
        result = self.scorer.score("uhh that thing you know")
        assert result.score < 80
        assert result.is_actionable is False
        assert result.needs_clarification is True

    def test_vague_reference_low_confidence(self):
        """Vague pronoun references should reduce confidence."""
        result = self.scorer.score("do it")
        assert result.score < 80
        assert result.is_actionable is False

    def test_question_reduces_confidence(self):
        """Questions should reduce confidence."""
        result = self.scorer.score("Should I buy milk?")
        assert result.breakdown.question_penalty == 10
        # Still might be actionable if other factors are strong
        assert result.score < 90  # At least reduced somewhat

    def test_very_short_message(self):
        """Very short messages should have lower confidence."""
        result = self.scorer.score("hi")
        assert result.score < 80

    def test_unclear_message(self):
        """Unclear message should be flagged for review."""
        result = self.scorer.score("the thing with Mike maybe")
        assert result.is_actionable is False
        assert "flagged for review" in result.explanation.lower()

    # === Breakdown Tests ===

    def test_breakdown_intent_bonus(self):
        """Action verb should add intent bonus."""
        result = self.scorer.score("Call dentist")
        assert result.breakdown.intent_bonus == 25

    def test_breakdown_no_intent_bonus_without_verb(self):
        """No action verb should mean no intent bonus."""
        result = self.scorer.score("dentist appointment")
        assert result.breakdown.intent_bonus == 0

    def test_breakdown_entity_bonus(self):
        """High-confidence entities should add bonus."""
        entities = ExtractedEntities(
            people=[
                ExtractedPerson(name="Sarah", confidence=90, context=""),
                ExtractedPerson(name="Mike", confidence=85, context=""),
            ],
            raw_text="Sarah and Mike",
        )
        result = self.scorer.score("Meeting with Sarah and Mike", entities)
        assert result.breakdown.entity_bonus >= 10  # Two high-confidence people

    def test_breakdown_time_bonus(self):
        """Date/time should add time bonus."""
        entities = ExtractedEntities(
            dates=[
                ExtractedDate(
                    datetime_value=datetime.now(),
                    confidence=90,
                    original_text="tomorrow",
                    timezone="UTC",
                    is_relative=True,
                )
            ],
            raw_text="tomorrow",
        )
        result = self.scorer.score("Buy milk tomorrow", entities)
        assert result.breakdown.time_bonus == 15

    def test_breakdown_length_bonus(self):
        """Adequate length should add bonus."""
        result = self.scorer.score("Buy milk at the store")
        assert result.breakdown.length_bonus == 5

    def test_breakdown_short_message_reduced_bonus(self):
        """Short message should have reduced length bonus."""
        result = self.scorer.score("Buy milk")
        assert result.breakdown.length_bonus == 2

    def test_breakdown_ambiguity_penalty(self):
        """Filler words should add ambiguity penalty."""
        result = self.scorer.score("umm buy like whatever")
        assert result.breakdown.ambiguity_penalty == 30

    def test_breakdown_to_dict(self):
        """Breakdown should convert to dictionary."""
        breakdown = ConfidenceBreakdown(
            base_score=50,
            intent_bonus=20,
            entity_bonus=5,
        )
        d = breakdown.to_dict()
        assert d["base_score"] == 50
        assert d["intent_bonus"] == 20
        assert d["entity_bonus"] == 5
        assert d["total"] == 75

    # === Edge Cases ===

    def test_score_clamped_to_100(self):
        """Score should never exceed 100."""
        entities = ExtractedEntities(
            people=[ExtractedPerson(name="P1", confidence=90, context="")],
            places=[ExtractedPlace(name="Place", confidence=90, context="")],
            dates=[
                ExtractedDate(
                    datetime_value=datetime.now(),
                    confidence=95,
                    original_text="now",
                    timezone="UTC",
                    is_relative=True,
                )
            ],
            raw_text="test",
        )
        result = self.scorer.score(
            "Call John at Starbucks tomorrow at 3pm for the meeting", entities
        )
        assert result.score <= 100

    def test_score_clamped_to_0(self):
        """Score should never go below 0."""
        result = self.scorer.score("uhh umm like you know that thing whatever?")
        assert result.score >= 0

    def test_action_verb_at_start(self):
        """Action verb at start of sentence should be detected."""
        result = self.scorer.score("Buy groceries")
        assert result.breakdown.intent_bonus == 25

    def test_action_verb_in_middle(self):
        """Action verb in middle should be detected."""
        result = self.scorer.score("I need to buy groceries")
        assert result.breakdown.intent_bonus == 25

    # === Convenience Function Tests ===

    def test_calculate_confidence_function(self):
        """Convenience function should work correctly."""
        result = calculate_confidence("Buy milk tomorrow")
        assert isinstance(result, ConfidenceResult)
        assert result.score >= 0
        assert result.score <= 100

    def test_custom_threshold(self):
        """Custom threshold should be respected."""
        # With default 80% threshold
        result1 = calculate_confidence("Buy milk", threshold=80)

        # With lower 50% threshold
        result2 = calculate_confidence("Buy milk", threshold=50)

        assert result1.score == result2.score  # Same score
        # But actionability may differ based on threshold
        if result1.score >= 50 and result1.score < 80:
            assert result2.is_actionable is True
            assert result1.is_actionable is False

    # === Explanation Tests ===

    def test_explanation_includes_factors(self):
        """Explanation should mention contributing factors."""
        result = self.scorer.score("Buy milk tomorrow")
        assert "action" in result.explanation.lower()

    def test_explanation_actionable(self):
        """Actionable result should mention proceeding."""
        result = calculate_confidence("Call John tomorrow at 3pm")
        if result.is_actionable:
            assert "proceeding" in result.explanation.lower()

    def test_explanation_flagged(self):
        """Non-actionable result should mention flagged."""
        result = calculate_confidence("umm that thing")
        assert "flagged" in result.explanation.lower()
