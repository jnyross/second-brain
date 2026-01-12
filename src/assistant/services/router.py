"""Classification router for Second Brain.

Routes parsed input to the correct Notion database based on entity type,
confidence score, and intent classification.
"""

from dataclasses import dataclass
from enum import Enum

from assistant.services.confidence import ConfidenceResult
from assistant.services.entities import ExtractedEntities


class TargetDatabase(Enum):
    """Notion databases that can receive routed input."""

    INBOX = "inbox"  # Raw captures, needs review
    TASKS = "tasks"  # Actionable items
    PEOPLE = "people"  # Contact information
    PLACES = "places"  # Location information
    PROJECTS = "projects"  # Grouped work items


class RouteAction(Enum):
    """Actions to take after routing."""

    CREATE = "create"  # Create new record
    UPDATE = "update"  # Update existing record
    LINK = "link"  # Link to existing record
    FLAG_REVIEW = "flag_review"  # Flag for human review


@dataclass
class RoutingDecision:
    """Result of the classification router."""

    target: TargetDatabase
    action: RouteAction
    confidence: int
    needs_clarification: bool
    reason: str
    secondary_targets: list[TargetDatabase]  # Related databases to update


class ClassificationRouter:
    """Routes parsed input to the correct Notion database.

    The router implements the "Sorter" component from the Second Brain framework:
    - Auto-categorize into correct database based on entity type
    - Use confidence to determine action (create vs flag for review)
    - Support intent types: task, idea, note, person, place
    """

    # Minimum confidence for automatic action
    DEFAULT_THRESHOLD = 80

    # Intent types and their primary routing targets
    INTENT_ROUTES = {
        "task": TargetDatabase.TASKS,
        "idea": TargetDatabase.INBOX,  # Ideas go to inbox for processing
        "note": TargetDatabase.INBOX,  # Notes go to inbox
        "person": TargetDatabase.PEOPLE,
        "place": TargetDatabase.PLACES,
        "project": TargetDatabase.PROJECTS,
    }

    def __init__(self, confidence_threshold: int = DEFAULT_THRESHOLD):
        self.confidence_threshold = confidence_threshold

    def route(
        self,
        intent_type: str,
        confidence_result: ConfidenceResult,
        entities: ExtractedEntities | None = None,
    ) -> RoutingDecision:
        """Determine where to route the parsed input.

        Args:
            intent_type: Detected intent (task, idea, note, person, place, project)
            confidence_result: Result from ConfidenceScorer
            entities: Extracted entities (for secondary routing)

        Returns:
            RoutingDecision with target database, action, and related targets
        """
        confidence = confidence_result.score
        is_actionable = confidence >= self.confidence_threshold

        # Determine primary target based on intent type
        primary_target = self._get_primary_target(intent_type)

        # Determine secondary targets based on extracted entities
        secondary_targets = self._get_secondary_targets(entities, primary_target)

        # Determine action based on confidence
        if not is_actionable:
            return RoutingDecision(
                target=TargetDatabase.INBOX,
                action=RouteAction.FLAG_REVIEW,
                confidence=confidence,
                needs_clarification=True,
                reason=f"Low confidence ({confidence}%) - flagged for review",
                secondary_targets=[],
            )

        # High confidence - route to appropriate database
        action = RouteAction.CREATE
        reason = f"High confidence ({confidence}%) - creating {primary_target.value}"

        return RoutingDecision(
            target=primary_target,
            action=action,
            confidence=confidence,
            needs_clarification=False,
            reason=reason,
            secondary_targets=secondary_targets,
        )

    def _get_primary_target(self, intent_type: str) -> TargetDatabase:
        """Determine primary target database from intent type."""
        intent_lower = intent_type.lower()
        return self.INTENT_ROUTES.get(intent_lower, TargetDatabase.TASKS)

    def _get_secondary_targets(
        self,
        entities: ExtractedEntities | None,
        primary_target: TargetDatabase,
    ) -> list[TargetDatabase]:
        """Determine secondary databases to update based on entities.

        For example, a task mentioning a person should also link to People database.
        """
        if not entities:
            return []

        secondary = []

        # If we have people entities and primary isn't People, add People as secondary
        if entities.people and primary_target != TargetDatabase.PEOPLE:
            secondary.append(TargetDatabase.PEOPLE)

        # If we have place entities and primary isn't Places, add Places as secondary
        if entities.places and primary_target != TargetDatabase.PLACES:
            secondary.append(TargetDatabase.PLACES)

        return secondary

    def should_create_task(self, decision: RoutingDecision) -> bool:
        """Check if routing decision indicates task creation."""
        return decision.target == TargetDatabase.TASKS and decision.action == RouteAction.CREATE

    def should_flag_for_review(self, decision: RoutingDecision) -> bool:
        """Check if routing decision indicates flagging for human review."""
        return decision.needs_clarification

    def get_linked_entities(self, entities: ExtractedEntities | None) -> dict[str, list[str]]:
        """Extract entity names for linking to related databases.

        Returns dict with 'people' and 'places' lists of names to link.
        """
        result: dict[str, list[str]] = {"people": [], "places": []}

        if not entities:
            return result

        result["people"] = [p.name for p in entities.people]
        result["places"] = [p.name for p in entities.places]

        return result


def classify_and_route(
    intent_type: str,
    confidence_result: ConfidenceResult,
    entities: ExtractedEntities | None = None,
    threshold: int = ClassificationRouter.DEFAULT_THRESHOLD,
) -> RoutingDecision:
    """Convenience function to classify and route input.

    Args:
        intent_type: Detected intent (task, idea, note, etc.)
        confidence_result: Result from confidence scoring
        entities: Extracted entities
        threshold: Confidence threshold for automatic action

    Returns:
        RoutingDecision with target and action
    """
    router = ClassificationRouter(confidence_threshold=threshold)
    return router.route(intent_type, confidence_result, entities)
