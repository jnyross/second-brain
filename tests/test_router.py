"""Tests for the classification router."""

import pytest
from datetime import datetime

from assistant.services.router import (
    ClassificationRouter,
    TargetDatabase,
    RouteAction,
    RoutingDecision,
    classify_and_route,
)
from assistant.services.confidence import (
    ConfidenceResult,
    ConfidenceBreakdown,
)
from assistant.services.entities import (
    ExtractedEntities,
    ExtractedPerson,
    ExtractedPlace,
    ExtractedDate,
)


def make_confidence_result(score: int) -> ConfidenceResult:
    """Helper to create a ConfidenceResult with given score."""
    is_actionable = score >= 80
    return ConfidenceResult(
        score=score,
        is_actionable=is_actionable,
        breakdown=ConfidenceBreakdown(),
        explanation=f"Test confidence: {score}%",
    )


class TestClassificationRouter:
    """Test suite for ClassificationRouter."""

    def setup_method(self):
        self.router = ClassificationRouter()

    # === High Confidence Task Routing ===

    def test_route_task_high_confidence(self):
        """High confidence task should route to Tasks database."""
        confidence = make_confidence_result(85)
        decision = self.router.route("task", confidence)

        assert decision.target == TargetDatabase.TASKS
        assert decision.action == RouteAction.CREATE
        assert decision.needs_clarification is False
        assert decision.confidence == 85

    def test_route_task_with_people_entities(self):
        """Task with people should have People as secondary target."""
        confidence = make_confidence_result(90)
        entities = ExtractedEntities(
            people=[ExtractedPerson(name="Sarah", confidence=85, context="")],
            raw_text="Call Sarah",
        )
        decision = self.router.route("task", confidence, entities)

        assert decision.target == TargetDatabase.TASKS
        assert TargetDatabase.PEOPLE in decision.secondary_targets

    def test_route_task_with_places_entities(self):
        """Task with places should have Places as secondary target."""
        confidence = make_confidence_result(90)
        entities = ExtractedEntities(
            places=[ExtractedPlace(name="Starbucks", confidence=80, context="")],
            raw_text="Meet at Starbucks",
        )
        decision = self.router.route("task", confidence, entities)

        assert decision.target == TargetDatabase.TASKS
        assert TargetDatabase.PLACES in decision.secondary_targets

    # === Low Confidence Routing ===

    def test_route_low_confidence_to_inbox(self):
        """Low confidence input should always go to Inbox."""
        confidence = make_confidence_result(50)
        decision = self.router.route("task", confidence)

        assert decision.target == TargetDatabase.INBOX
        assert decision.action == RouteAction.FLAG_REVIEW
        assert decision.needs_clarification is True
        assert "flagged for review" in decision.reason.lower()

    def test_route_borderline_confidence(self):
        """Confidence at 79% should still flag for review."""
        confidence = make_confidence_result(79)
        decision = self.router.route("task", confidence)

        assert decision.target == TargetDatabase.INBOX
        assert decision.needs_clarification is True

    def test_route_threshold_exactly_80(self):
        """Confidence at exactly 80% should be actionable."""
        confidence = make_confidence_result(80)
        decision = self.router.route("task", confidence)

        assert decision.target == TargetDatabase.TASKS
        assert decision.needs_clarification is False

    # === Different Intent Types ===

    def test_route_idea_to_inbox(self):
        """Ideas should route to Inbox (for later processing)."""
        confidence = make_confidence_result(85)
        decision = self.router.route("idea", confidence)

        assert decision.target == TargetDatabase.INBOX
        assert decision.action == RouteAction.CREATE

    def test_route_note_to_inbox(self):
        """Notes should route to Inbox."""
        confidence = make_confidence_result(85)
        decision = self.router.route("note", confidence)

        assert decision.target == TargetDatabase.INBOX

    def test_route_person_to_people(self):
        """Person-focused input should route to People database."""
        confidence = make_confidence_result(90)
        decision = self.router.route("person", confidence)

        assert decision.target == TargetDatabase.PEOPLE
        assert decision.action == RouteAction.CREATE

    def test_route_place_to_places(self):
        """Place-focused input should route to Places database."""
        confidence = make_confidence_result(90)
        decision = self.router.route("place", confidence)

        assert decision.target == TargetDatabase.PLACES

    def test_route_project_to_projects(self):
        """Project-focused input should route to Projects database."""
        confidence = make_confidence_result(85)
        decision = self.router.route("project", confidence)

        assert decision.target == TargetDatabase.PROJECTS

    def test_route_unknown_intent_defaults_to_task(self):
        """Unknown intent type should default to Tasks."""
        confidence = make_confidence_result(85)
        decision = self.router.route("unknown_type", confidence)

        assert decision.target == TargetDatabase.TASKS

    # === Helper Methods ===

    def test_should_create_task_true(self):
        """should_create_task returns True for task creation decisions."""
        confidence = make_confidence_result(85)
        decision = self.router.route("task", confidence)

        assert self.router.should_create_task(decision) is True

    def test_should_create_task_false_for_inbox(self):
        """should_create_task returns False for inbox routing."""
        confidence = make_confidence_result(50)
        decision = self.router.route("task", confidence)

        assert self.router.should_create_task(decision) is False

    def test_should_flag_for_review(self):
        """should_flag_for_review returns True for low confidence."""
        confidence = make_confidence_result(60)
        decision = self.router.route("task", confidence)

        assert self.router.should_flag_for_review(decision) is True

    def test_get_linked_entities_with_people_and_places(self):
        """get_linked_entities extracts entity names."""
        entities = ExtractedEntities(
            people=[
                ExtractedPerson(name="Sarah", confidence=90, context=""),
                ExtractedPerson(name="Mike", confidence=85, context=""),
            ],
            places=[
                ExtractedPlace(name="Starbucks", confidence=80, context=""),
            ],
            raw_text="test",
        )
        linked = self.router.get_linked_entities(entities)

        assert "Sarah" in linked["people"]
        assert "Mike" in linked["people"]
        assert "Starbucks" in linked["places"]

    def test_get_linked_entities_empty(self):
        """get_linked_entities handles None entities."""
        linked = self.router.get_linked_entities(None)

        assert linked["people"] == []
        assert linked["places"] == []

    # === Custom Threshold ===

    def test_custom_threshold_higher(self):
        """Custom higher threshold should be respected."""
        router = ClassificationRouter(confidence_threshold=90)
        confidence = make_confidence_result(85)
        decision = router.route("task", confidence)

        # 85 < 90, so should flag for review
        assert decision.needs_clarification is True

    def test_custom_threshold_lower(self):
        """Custom lower threshold should be respected."""
        router = ClassificationRouter(confidence_threshold=60)
        confidence = make_confidence_result(65)
        decision = router.route("task", confidence)

        # 65 >= 60, so should be actionable
        assert decision.needs_clarification is False
        assert decision.target == TargetDatabase.TASKS

    # === Secondary Targets Logic ===

    def test_no_secondary_when_target_matches_entity(self):
        """Don't add People as secondary if routing to People already."""
        confidence = make_confidence_result(85)
        entities = ExtractedEntities(
            people=[ExtractedPerson(name="Sarah", confidence=90, context="")],
            raw_text="test",
        )
        decision = self.router.route("person", confidence, entities)

        assert decision.target == TargetDatabase.PEOPLE
        assert TargetDatabase.PEOPLE not in decision.secondary_targets

    def test_multiple_secondary_targets(self):
        """Can have both People and Places as secondary targets."""
        confidence = make_confidence_result(90)
        entities = ExtractedEntities(
            people=[ExtractedPerson(name="Sarah", confidence=90, context="")],
            places=[ExtractedPlace(name="Cafe", confidence=85, context="")],
            raw_text="Meet Sarah at Cafe",
        )
        decision = self.router.route("task", confidence, entities)

        assert TargetDatabase.PEOPLE in decision.secondary_targets
        assert TargetDatabase.PLACES in decision.secondary_targets

    # === Convenience Function ===

    def test_classify_and_route_function(self):
        """Convenience function should work correctly."""
        confidence = make_confidence_result(85)
        decision = classify_and_route("task", confidence)

        assert isinstance(decision, RoutingDecision)
        assert decision.target == TargetDatabase.TASKS

    def test_classify_and_route_with_custom_threshold(self):
        """Convenience function respects custom threshold."""
        confidence = make_confidence_result(75)
        decision = classify_and_route("task", confidence, threshold=70)

        assert decision.needs_clarification is False
        assert decision.target == TargetDatabase.TASKS


class TestRoutingDecision:
    """Tests for RoutingDecision dataclass."""

    def test_routing_decision_creation(self):
        """RoutingDecision can be created with all fields."""
        decision = RoutingDecision(
            target=TargetDatabase.TASKS,
            action=RouteAction.CREATE,
            confidence=85,
            needs_clarification=False,
            reason="High confidence",
            secondary_targets=[TargetDatabase.PEOPLE],
        )

        assert decision.target == TargetDatabase.TASKS
        assert decision.action == RouteAction.CREATE
        assert decision.confidence == 85
        assert len(decision.secondary_targets) == 1
