"""Pattern detection and learning service for Second Brain.

Detects repeated corrections and builds learned patterns that can be
applied to future inputs. Per PRD Section 5.5 and AT-109:

Pattern learning:
- Track which corrections are made repeatedly
- Store pattern: `trigger="work meeting Sarah", meaning="Sarah Jones (colleague)"`
- Apply pattern automatically after 3 confirmations

Pattern correction example:
```
User: You keep setting shopping tasks as high priority, they should be low

AI: Got it. I've updated my pattern: shopping-related tasks will now default
    to low priority. I'll update the 3 existing shopping tasks too.

Pattern stored:
- trigger: "shopping" / "buy" / "groceries"
- correction: priority = low
- confidence: 80% (will increase with confirmation)
```
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from collections import Counter, defaultdict

from assistant.notion import NotionClient
from assistant.notion.schemas import Pattern

logger = logging.getLogger(__name__)


# Minimum occurrences before a pattern is detected
MIN_PATTERN_OCCURRENCES = 3

# Confidence threshold for pattern to be auto-applied
PATTERN_CONFIDENCE_THRESHOLD = 70

# Initial confidence when pattern is first created
INITIAL_PATTERN_CONFIDENCE = 50

# Confidence boost per confirmation
CONFIDENCE_BOOST_PER_CONFIRMATION = 10

# Confidence penalty per wrong application
CONFIDENCE_PENALTY_PER_WRONG = 20


@dataclass
class CorrectionRecord:
    """A record of a single correction for pattern detection."""

    original_value: str
    corrected_value: str
    context: str = ""  # Additional context (e.g., "task title", "person name")
    timestamp: datetime = field(default_factory=datetime.utcnow)
    entity_type: str = ""  # "task", "person", "place", "project"


@dataclass
class DetectedPattern:
    """A pattern detected from repeated corrections."""

    trigger: str  # The pattern that triggers this correction
    meaning: str  # What it should be corrected to
    occurrences: int  # How many times this correction was made
    confidence: int  # Calculated confidence (50-100)
    examples: list[CorrectionRecord]  # Example corrections
    pattern_type: str = "name"  # "name", "priority", "date", "person"

    @property
    def is_ready_for_storage(self) -> bool:
        """Check if pattern has enough occurrences to be stored."""
        return self.occurrences >= MIN_PATTERN_OCCURRENCES

    @property
    def is_auto_applicable(self) -> bool:
        """Check if pattern confidence is high enough for auto-apply."""
        return self.confidence >= PATTERN_CONFIDENCE_THRESHOLD


@dataclass
class PatternMatch:
    """A match between an input and a stored pattern."""

    pattern: Pattern
    matched_text: str
    suggested_correction: str
    confidence: int


class PatternDetector:
    """Detects patterns from repeated corrections.

    Analyzes correction history to find repeated similar corrections,
    and creates patterns that can be applied to future inputs.
    """

    def __init__(self, notion_client: Optional[NotionClient] = None):
        """Initialize the pattern detector.

        Args:
            notion_client: Optional NotionClient instance.
        """
        self._notion = notion_client

        # In-memory correction history for pattern detection
        # This will be populated from Notion's log on init
        self._correction_history: list[CorrectionRecord] = []

        # Detected patterns waiting to be stored
        self._pending_patterns: list[DetectedPattern] = []

    @property
    def notion(self) -> NotionClient:
        """Get or create NotionClient instance."""
        if self._notion is None:
            self._notion = NotionClient()
        return self._notion

    def add_correction(self, record: CorrectionRecord) -> list[DetectedPattern]:
        """Add a correction and check for new patterns.

        Args:
            record: The correction record to add

        Returns:
            List of newly detected patterns (may be empty)
        """
        self._correction_history.append(record)

        # Normalize values for comparison
        normalized_original = self._normalize(record.original_value)
        normalized_corrected = self._normalize(record.corrected_value)

        # Check if this correction forms a new pattern
        return self._detect_patterns_for(normalized_original, normalized_corrected)

    def _normalize(self, text: str) -> str:
        """Normalize text for pattern comparison.

        Lowercases, strips whitespace, removes punctuation.
        """
        text = text.lower().strip()
        # Remove common punctuation that doesn't affect meaning
        text = re.sub(r"[.,!?;:'\"-]", "", text)
        return text

    def _detect_patterns_for(
        self,
        normalized_original: str,
        normalized_corrected: str
    ) -> list[DetectedPattern]:
        """Detect patterns involving this specific correction.

        Args:
            normalized_original: Normalized original value
            normalized_corrected: Normalized corrected value

        Returns:
            List of newly detected patterns
        """
        new_patterns = []

        # Count similar corrections in history
        similar_corrections = []
        for record in self._correction_history:
            rec_orig = self._normalize(record.original_value)
            rec_corr = self._normalize(record.corrected_value)

            if self._is_similar_correction(
                normalized_original, normalized_corrected,
                rec_orig, rec_corr
            ):
                similar_corrections.append(record)

        # Check if we've hit the threshold
        if len(similar_corrections) >= MIN_PATTERN_OCCURRENCES:
            pattern = self._create_pattern_from_corrections(similar_corrections)

            # Only add if not already pending
            if not self._is_pattern_pending(pattern):
                self._pending_patterns.append(pattern)
                new_patterns.append(pattern)
                logger.info(
                    f"Detected new pattern: '{pattern.trigger}' → '{pattern.meaning}' "
                    f"(confidence: {pattern.confidence}%, occurrences: {pattern.occurrences})"
                )

        return new_patterns

    def _is_similar_correction(
        self,
        orig1: str, corr1: str,
        orig2: str, corr2: str,
    ) -> bool:
        """Check if two corrections are similar enough to form a pattern.

        We consider corrections similar if:
        1. They have the same original value (exact match)
        2. They have the same corrected value (exact match)
        3. OR they follow a predictable transformation pattern
        """
        # Exact match on both ends
        if orig1 == orig2 and corr1 == corr2:
            return True

        # Same original, similar corrected (e.g., typo variants)
        if orig1 == orig2 and self._string_similarity(corr1, corr2) > 0.8:
            return True

        # Similar original, same corrected (e.g., multiple misspellings of same name)
        if self._string_similarity(orig1, orig2) > 0.8 and corr1 == corr2:
            return True

        return False

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity between two strings (0.0 to 1.0).

        Uses simple character-based similarity.
        """
        if not s1 or not s2:
            return 0.0

        if s1 == s2:
            return 1.0

        # Count matching characters
        len1, len2 = len(s1), len(s2)
        max_len = max(len1, len2)

        # Simple Levenshtein-like distance approximation
        matching = sum(c1 == c2 for c1, c2 in zip(s1, s2))
        extra_chars = abs(len1 - len2)

        return (matching - extra_chars * 0.5) / max_len

    def _create_pattern_from_corrections(
        self,
        corrections: list[CorrectionRecord]
    ) -> DetectedPattern:
        """Create a pattern from a list of similar corrections.

        Args:
            corrections: List of similar corrections

        Returns:
            DetectedPattern representing these corrections
        """
        # Find most common original and corrected values
        original_counts = Counter(c.original_value for c in corrections)
        corrected_counts = Counter(c.corrected_value for c in corrections)

        most_common_original = original_counts.most_common(1)[0][0]
        most_common_corrected = corrected_counts.most_common(1)[0][0]

        # Determine pattern type from context
        pattern_type = self._infer_pattern_type(corrections)

        # Calculate confidence based on consistency
        consistency = len(set(c.corrected_value for c in corrections)) == 1
        base_confidence = INITIAL_PATTERN_CONFIDENCE

        if consistency:
            # All corrections went to the same value - higher confidence
            extra_confidence = (len(corrections) - MIN_PATTERN_OCCURRENCES) * CONFIDENCE_BOOST_PER_CONFIRMATION
            confidence = min(100, base_confidence + extra_confidence + 10)
        else:
            confidence = base_confidence

        return DetectedPattern(
            trigger=most_common_original,
            meaning=most_common_corrected,
            occurrences=len(corrections),
            confidence=confidence,
            examples=corrections[:5],  # Keep up to 5 examples
            pattern_type=pattern_type,
        )

    def _infer_pattern_type(self, corrections: list[CorrectionRecord]) -> str:
        """Infer the type of pattern from correction context.

        Args:
            corrections: List of corrections

        Returns:
            Pattern type string
        """
        # Check entity types from corrections
        entity_types = Counter(c.entity_type for c in corrections if c.entity_type)

        if entity_types:
            most_common = entity_types.most_common(1)[0][0]
            if most_common == "person":
                return "person"
            elif most_common in ("task", "project"):
                return "name"

        # Check context for clues
        contexts = [c.context.lower() for c in corrections if c.context]
        if any("priority" in ctx for ctx in contexts):
            return "priority"
        if any("date" in ctx or "time" in ctx for ctx in contexts):
            return "date"
        if any("person" in ctx or "name" in ctx for ctx in contexts):
            return "person"

        return "name"  # Default

    def _is_pattern_pending(self, pattern: DetectedPattern) -> bool:
        """Check if a similar pattern is already pending storage."""
        for pending in self._pending_patterns:
            if (self._normalize(pending.trigger) == self._normalize(pattern.trigger) and
                self._normalize(pending.meaning) == self._normalize(pattern.meaning)):
                return True
        return False

    def get_pending_patterns(self) -> list[DetectedPattern]:
        """Get patterns that are ready to be stored but haven't been yet."""
        return [p for p in self._pending_patterns if p.is_ready_for_storage]

    async def store_pattern(self, pattern: DetectedPattern) -> str:
        """Store a detected pattern in Notion's Patterns database.

        Args:
            pattern: The pattern to store

        Returns:
            The Notion page ID of the stored pattern
        """
        notion_pattern = Pattern(
            trigger=pattern.trigger,
            meaning=pattern.meaning,
            confidence=pattern.confidence,
            times_confirmed=pattern.occurrences,
        )

        page_id = await self.notion.create_pattern(notion_pattern)

        # Remove from pending
        self._pending_patterns = [
            p for p in self._pending_patterns
            if not (self._normalize(p.trigger) == self._normalize(pattern.trigger) and
                   self._normalize(p.meaning) == self._normalize(pattern.meaning))
        ]

        logger.info(
            f"Stored pattern in Notion: '{pattern.trigger}' → '{pattern.meaning}' "
            f"(id: {page_id})"
        )

        return page_id

    async def store_pending_patterns(self) -> list[str]:
        """Store all pending patterns that meet the threshold.

        Returns:
            List of Notion page IDs for stored patterns
        """
        stored_ids = []

        for pattern in self.get_pending_patterns():
            try:
                page_id = await self.store_pattern(pattern)
                stored_ids.append(page_id)
            except Exception as e:
                logger.exception(f"Failed to store pattern: {e}")

        return stored_ids

    async def load_corrections_from_log(
        self,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> int:
        """Load correction history from Notion's log.

        Args:
            since: Only load corrections after this timestamp
            limit: Maximum number of entries to load

        Returns:
            Number of corrections loaded
        """
        if since is None:
            # Default to last 7 days
            since = datetime.utcnow() - timedelta(days=7)

        entries = await self.notion.query_log_corrections(since=since, limit=limit)

        loaded = 0
        for entry in entries:
            if entry.correction:
                # Parse "original → corrected" format
                parts = entry.correction.split(" → ")
                if len(parts) == 2:
                    record = CorrectionRecord(
                        original_value=parts[0].strip(),
                        corrected_value=parts[1].strip(),
                        timestamp=entry.corrected_at or entry.timestamp,
                    )
                    self._correction_history.append(record)
                    loaded += 1

        logger.info(f"Loaded {loaded} corrections from log")
        return loaded

    async def analyze_correction_patterns(self) -> list[DetectedPattern]:
        """Analyze all corrections in history to find patterns.

        Useful for bulk analysis after loading from log.

        Returns:
            List of all detected patterns
        """
        # Group by normalized original value
        by_original: dict[str, list[CorrectionRecord]] = defaultdict(list)

        for record in self._correction_history:
            normalized = self._normalize(record.original_value)
            by_original[normalized].append(record)

        # Check each group for pattern potential
        detected = []
        for normalized_orig, records in by_original.items():
            if len(records) >= MIN_PATTERN_OCCURRENCES:
                # Group by corrected value too
                by_corrected = defaultdict(list)
                for r in records:
                    norm_corr = self._normalize(r.corrected_value)
                    by_corrected[norm_corr].append(r)

                # Find the most common correction
                for norm_corr, corr_records in by_corrected.items():
                    if len(corr_records) >= MIN_PATTERN_OCCURRENCES:
                        pattern = self._create_pattern_from_corrections(corr_records)
                        if not self._is_pattern_pending(pattern):
                            self._pending_patterns.append(pattern)
                            detected.append(pattern)

        return detected

    def clear_history(self) -> None:
        """Clear correction history and pending patterns."""
        self._correction_history = []
        self._pending_patterns = []


# Module-level convenience functions

_detector: Optional[PatternDetector] = None


def get_pattern_detector() -> PatternDetector:
    """Get or create the global PatternDetector instance."""
    global _detector
    if _detector is None:
        _detector = PatternDetector()
    return _detector


def add_correction(
    original_value: str,
    corrected_value: str,
    context: str = "",
    entity_type: str = "",
) -> list[DetectedPattern]:
    """Add a correction and check for patterns.

    Convenience function that uses the global detector.
    """
    record = CorrectionRecord(
        original_value=original_value,
        corrected_value=corrected_value,
        context=context,
        entity_type=entity_type,
    )
    return get_pattern_detector().add_correction(record)


async def store_pending_patterns() -> list[str]:
    """Store all pending patterns that meet the threshold.

    Convenience function that uses the global detector.
    """
    return await get_pattern_detector().store_pending_patterns()


async def load_and_analyze_patterns(since_days: int = 7) -> list[DetectedPattern]:
    """Load corrections from log and analyze for patterns.

    Convenience function that uses the global detector.

    Args:
        since_days: How many days of history to analyze

    Returns:
        List of detected patterns
    """
    detector = get_pattern_detector()
    since = datetime.utcnow() - timedelta(days=since_days)
    await detector.load_corrections_from_log(since=since)
    return await detector.analyze_correction_patterns()
