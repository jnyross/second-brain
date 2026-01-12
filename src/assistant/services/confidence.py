"""Confidence scoring service for Second Brain.

Calculates confidence scores (0-100) for AI interpretations of user input.
Scores determine routing: ≥80% = act automatically, <80% = flag for review.
"""

from dataclasses import dataclass

from assistant.services.entities import ExtractedEntities


@dataclass
class ConfidenceBreakdown:
    """Detailed breakdown of confidence score components."""

    base_score: int = 50
    intent_bonus: int = 0  # +25 for clear action verb
    entity_bonus: int = 0  # +5 per high-confidence entity (max +15)
    time_bonus: int = 0  # +15 for date/time extracted
    length_bonus: int = 0  # +5 for adequate length
    ambiguity_penalty: int = 0  # -30 for filler words
    question_penalty: int = 0  # -10 for question mark
    vagueness_penalty: int = 0  # -15 for vague pronouns without context

    @property
    def total(self) -> int:
        """Calculate total confidence score (0-100)."""
        raw = (
            self.base_score
            + self.intent_bonus
            + self.entity_bonus
            + self.time_bonus
            + self.length_bonus
            - self.ambiguity_penalty
            - self.question_penalty
            - self.vagueness_penalty
        )
        return max(0, min(100, raw))

    def to_dict(self) -> dict:
        """Return breakdown as dictionary."""
        return {
            "base_score": self.base_score,
            "intent_bonus": self.intent_bonus,
            "entity_bonus": self.entity_bonus,
            "time_bonus": self.time_bonus,
            "length_bonus": self.length_bonus,
            "ambiguity_penalty": self.ambiguity_penalty,
            "question_penalty": self.question_penalty,
            "vagueness_penalty": self.vagueness_penalty,
            "total": self.total,
        }


@dataclass
class ConfidenceResult:
    """Result of confidence scoring."""

    score: int  # 0-100
    is_actionable: bool  # True if score >= threshold
    breakdown: ConfidenceBreakdown
    explanation: str  # Human-readable explanation

    @property
    def needs_clarification(self) -> bool:
        """Whether this input needs human clarification."""
        return not self.is_actionable


class ConfidenceScorer:
    """Scores confidence for AI interpretations of user input.

    The confidence score determines routing:
    - ≥80%: Act automatically, create task/item, log action
    - <80%: Flag for review, add to Inbox with needs_clarification=true
    """

    # Threshold for automatic action (PRD specifies 80%)
    DEFAULT_THRESHOLD = 80

    # Clear action verbs that indicate intent
    ACTION_VERBS = frozenset(
        [
            "buy",
            "call",
            "email",
            "send",
            "book",
            "schedule",
            "meet",
            "remind",
            "pick up",
            "drop off",
            "finish",
            "complete",
            "do",
            "make",
            "get",
            "check",
            "review",
            "prepare",
            "write",
            "text",
            "contact",
            "cancel",
            "reschedule",
            "confirm",
            "pay",
            "order",
            "submit",
            "deliver",
            "return",
            "fix",
            "update",
            "create",
        ]
    )

    # Filler words indicating uncertainty
    FILLER_WORDS = [
        "uhh",
        "umm",
        "uh",
        "um",
        "like",
        "you know",
        "that thing",
        "whatever",
        "stuff",
        "thingy",
        "whatchamacallit",
    ]

    # Vague pronouns that need context
    VAGUE_PRONOUNS = ["it", "that", "this", "them", "those", "something", "someone"]

    def __init__(self, threshold: int = DEFAULT_THRESHOLD):
        self.threshold = threshold

    def score(
        self,
        text: str,
        entities: ExtractedEntities | None = None,
        intent_type: str | None = None,
    ) -> ConfidenceResult:
        """Calculate confidence score for the given input.

        Args:
            text: The user's input text
            entities: Extracted entities (if already extracted)
            intent_type: Detected intent type (task, idea, note)

        Returns:
            ConfidenceResult with score, actionability, and breakdown
        """
        text_lower = text.lower()
        breakdown = ConfidenceBreakdown()

        # Intent bonus: clear action verb
        if self._has_action_verb(text_lower):
            breakdown.intent_bonus = 25

        # Entity bonus: high-confidence entities found
        if entities:
            breakdown.entity_bonus = self._calculate_entity_bonus(entities)

        # Time bonus: date/time was extracted
        if entities and entities.dates:
            breakdown.time_bonus = 15

        # Length bonus: adequate message length
        words = text.split()
        if len(words) >= 3:
            breakdown.length_bonus = 5
        elif len(words) == 2:
            breakdown.length_bonus = 2

        # Ambiguity penalty: filler words
        if self._has_filler_words(text_lower):
            breakdown.ambiguity_penalty = 30

        # Question penalty
        if "?" in text:
            breakdown.question_penalty = 10

        # Vagueness penalty: vague pronouns without supporting context
        if self._has_vague_pronouns(text_lower, entities):
            breakdown.vagueness_penalty = 15

        # Calculate final score
        score = breakdown.total
        is_actionable = score >= self.threshold

        # Generate explanation
        explanation = self._generate_explanation(breakdown, score, is_actionable)

        return ConfidenceResult(
            score=score,
            is_actionable=is_actionable,
            breakdown=breakdown,
            explanation=explanation,
        )

    def _has_action_verb(self, text: str) -> bool:
        """Check if text contains a clear action verb."""
        for verb in self.ACTION_VERBS:
            # Check for word boundary (not part of another word)
            if f" {verb} " in f" {text} ":
                return True
            if text.startswith(f"{verb} "):
                return True
        return False

    def _has_filler_words(self, text: str) -> bool:
        """Check if text contains filler words indicating uncertainty."""
        for filler in self.FILLER_WORDS:
            if filler in text:
                return True
        return False

    def _has_vague_pronouns(self, text: str, entities: ExtractedEntities | None) -> bool:
        """Check for vague pronouns without supporting entity context."""
        words = text.split()

        # If we have entities, vague pronouns are less of a problem
        if entities and (entities.people or entities.places):
            return False

        # Check for vague pronouns at the start or as the main subject
        for pronoun in self.VAGUE_PRONOUNS:
            # Check if pronoun is a standalone word in the text
            if pronoun in words:
                # "do it" or "get that" are vague without context
                idx = words.index(pronoun)
                if idx <= 2:  # Near the start of the message
                    return True

        return False

    def _calculate_entity_bonus(self, entities: ExtractedEntities) -> int:
        """Calculate bonus based on extracted entities."""
        bonus = 0

        # High-confidence people
        for person in entities.people:
            if person.confidence >= 80:
                bonus += 5

        # High-confidence places
        for place in entities.places:
            if place.confidence >= 80:
                bonus += 5

        # Cap at +15
        return min(15, bonus)

    def _generate_explanation(
        self, breakdown: ConfidenceBreakdown, score: int, is_actionable: bool
    ) -> str:
        """Generate human-readable explanation of the confidence score."""
        parts = []

        if breakdown.intent_bonus > 0:
            parts.append("clear action detected")
        if breakdown.entity_bonus > 0:
            parts.append("entities recognized")
        if breakdown.time_bonus > 0:
            parts.append("time specified")
        if breakdown.ambiguity_penalty > 0:
            parts.append("unclear language")
        if breakdown.question_penalty > 0:
            parts.append("question detected")
        if breakdown.vagueness_penalty > 0:
            parts.append("vague reference")

        factors = ", ".join(parts) if parts else "baseline assessment"

        if is_actionable:
            return f"Confidence {score}% ({factors}) - proceeding automatically"
        else:
            return f"Confidence {score}% ({factors}) - flagged for review"


def calculate_confidence(
    text: str,
    entities: ExtractedEntities | None = None,
    intent_type: str | None = None,
    threshold: int = ConfidenceScorer.DEFAULT_THRESHOLD,
) -> ConfidenceResult:
    """Convenience function to calculate confidence score.

    Args:
        text: The user's input text
        entities: Extracted entities (if already extracted)
        intent_type: Detected intent type
        threshold: Minimum score for automatic action (default 80)

    Returns:
        ConfidenceResult with score, actionability, and breakdown
    """
    scorer = ConfidenceScorer(threshold=threshold)
    return scorer.score(text, entities, intent_type)
