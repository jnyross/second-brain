"""Pattern applicator service for Second Brain.

T-093: Apply patterns to new inputs

Checks stored patterns before classification and applies learned behaviors
to correct likely errors early in the processing pipeline.

PRD Section 5.5 - Pattern Application:
- Apply pattern automatically after 3 confirmations (stored patterns have >= 3)
- Patterns with confidence >= 70% are auto-applicable
- Example: AI keeps hearing "Jess" but user means "Tess" - pattern corrects it

Pattern matching strategy:
1. Query all applicable patterns from Notion (confidence >= 70%)
2. Match triggers against extracted entities and text
3. Apply corrections to people names, places, task titles
4. Return modified values for use in message processing
"""

import logging
import re
from dataclasses import dataclass, field

from assistant.notion import NotionClient
from assistant.services.patterns import PATTERN_CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)


@dataclass
class AppliedPattern:
    """Record of a pattern that was applied to input."""

    pattern_id: str  # Notion page ID
    trigger: str  # What triggered the match
    meaning: str  # What it was corrected to
    original_value: str  # Original value in input
    corrected_value: str  # Corrected value after pattern
    pattern_type: str  # "name", "person", "priority", etc.
    confidence: int  # Pattern confidence


@dataclass
class PatternApplicationResult:
    """Result of applying patterns to input."""

    # Original values
    original_text: str
    original_people: list[str] = field(default_factory=list)
    original_places: list[str] = field(default_factory=list)
    original_title: str = ""

    # Corrected values
    corrected_people: list[str] = field(default_factory=list)
    corrected_places: list[str] = field(default_factory=list)
    corrected_title: str = ""

    # Applied patterns
    patterns_applied: list[AppliedPattern] = field(default_factory=list)

    @property
    def has_corrections(self) -> bool:
        """Check if any corrections were made."""
        return len(self.patterns_applied) > 0

    @property
    def people(self) -> list[str]:
        """Get the corrected people list (or original if no corrections)."""
        return self.corrected_people if self.corrected_people else self.original_people

    @property
    def places(self) -> list[str]:
        """Get the corrected places list (or original if no corrections)."""
        return self.corrected_places if self.corrected_places else self.original_places

    @property
    def title(self) -> str:
        """Get the corrected title (or original if no corrections)."""
        return self.corrected_title if self.corrected_title else self.original_title

    def summary(self) -> str:
        """Generate a human-readable summary of corrections."""
        if not self.has_corrections:
            return "No patterns applied."

        parts = []
        for pattern in self.patterns_applied:
            parts.append(f"'{pattern.original_value}' → '{pattern.corrected_value}'")

        return f"Applied {len(self.patterns_applied)} pattern(s): {', '.join(parts)}"


class PatternApplicator:
    """Applies stored patterns to new inputs.

    This service queries Notion for applicable patterns and applies
    corrections to extracted entities before further processing.
    """

    def __init__(self, notion_client: NotionClient | None = None):
        """Initialize the pattern applicator.

        Args:
            notion_client: Optional NotionClient instance.
        """
        self._notion = notion_client
        self._pattern_cache: list[dict] = []
        self._cache_loaded = False

    @property
    def notion(self) -> NotionClient:
        """Get or create NotionClient instance."""
        if self._notion is None:
            self._notion = NotionClient()
        return self._notion

    async def load_patterns(self, min_confidence: int = PATTERN_CONFIDENCE_THRESHOLD) -> int:
        """Load applicable patterns from Notion.

        Args:
            min_confidence: Minimum confidence for patterns to load

        Returns:
            Number of patterns loaded
        """
        try:
            results = await self.notion.query_patterns(
                min_confidence=min_confidence,
                limit=100,
            )

            self._pattern_cache = []
            for result in results:
                pattern_data = self._extract_pattern_data(result)
                if pattern_data:
                    self._pattern_cache.append(pattern_data)

            self._cache_loaded = True
            logger.info(f"Loaded {len(self._pattern_cache)} applicable patterns")
            return len(self._pattern_cache)

        except Exception as e:
            logger.warning(f"Failed to load patterns from Notion: {e}")
            self._pattern_cache = []
            self._cache_loaded = True  # Mark as loaded to avoid repeated failures
            return 0

    def _extract_pattern_data(self, notion_result: dict) -> dict | None:
        """Extract pattern data from Notion result.

        Args:
            notion_result: Raw Notion query result

        Returns:
            Extracted pattern data or None
        """
        try:
            props = notion_result.get("properties", {})

            # Extract trigger (title property)
            trigger_prop = props.get("trigger", {})
            trigger_title = trigger_prop.get("title", [])
            trigger = ""
            if trigger_title:
                trigger = trigger_title[0].get("text", {}).get("content", "")

            # Extract meaning (rich_text property)
            meaning_prop = props.get("meaning", {})
            meaning_text = meaning_prop.get("rich_text", [])
            meaning = ""
            if meaning_text:
                meaning = meaning_text[0].get("text", {}).get("content", "")

            # Extract confidence (number property)
            confidence_prop = props.get("confidence", {})
            confidence = confidence_prop.get("number", 0) or 0

            # Extract pattern type (select property, optional)
            type_prop = props.get("pattern_type", {})
            type_select = type_prop.get("select", {})
            pattern_type = type_select.get("name", "name") if type_select else "name"

            if not trigger or not meaning:
                return None

            return {
                "id": notion_result.get("id", ""),
                "trigger": trigger,
                "meaning": meaning,
                "confidence": int(confidence),
                "pattern_type": pattern_type,
            }

        except Exception as e:
            logger.warning(f"Failed to extract pattern data: {e}")
            return None

    def _normalize(self, text: str) -> str:
        """Normalize text for pattern matching.

        Args:
            text: Text to normalize

        Returns:
            Normalized text
        """
        text = text.lower().strip()
        # Remove common punctuation
        text = re.sub(r"[.,!?;:'\"-]", "", text)
        return text

    def _matches_trigger(self, value: str, trigger: str) -> bool:
        """Check if a value matches a pattern trigger.

        Args:
            value: Value to check (e.g., extracted person name)
            trigger: Pattern trigger to match against

        Returns:
            True if value matches trigger
        """
        norm_value = self._normalize(value)
        norm_trigger = self._normalize(trigger)

        # Exact match
        if norm_value == norm_trigger:
            return True

        # Value contains trigger (for multi-word patterns)
        if norm_trigger in norm_value:
            return True

        # Trigger contains value (for short names)
        if norm_value in norm_trigger and len(norm_value) >= 3:
            return True

        return False

    async def apply_patterns(
        self,
        text: str,
        people: list[str] | None = None,
        places: list[str] | None = None,
        title: str | None = None,
    ) -> PatternApplicationResult:
        """Apply stored patterns to input values.

        Args:
            text: Original input text
            people: Extracted people names
            places: Extracted place names
            title: Generated task title

        Returns:
            PatternApplicationResult with original and corrected values
        """
        people = people or []
        places = places or []
        title = title or text

        result = PatternApplicationResult(
            original_text=text,
            original_people=people.copy(),
            original_places=places.copy(),
            original_title=title,
            corrected_people=people.copy(),
            corrected_places=places.copy(),
            corrected_title=title,
        )

        # Load patterns if not cached
        if not self._cache_loaded:
            await self.load_patterns()

        if not self._pattern_cache:
            return result

        # Apply patterns to people names
        for i, person in enumerate(result.corrected_people):
            for pattern in self._pattern_cache:
                if self._matches_trigger(person, pattern["trigger"]):
                    original = result.corrected_people[i]
                    result.corrected_people[i] = pattern["meaning"]
                    result.patterns_applied.append(
                        AppliedPattern(
                            pattern_id=pattern["id"],
                            trigger=pattern["trigger"],
                            meaning=pattern["meaning"],
                            original_value=original,
                            corrected_value=pattern["meaning"],
                            pattern_type=pattern.get("pattern_type", "person"),
                            confidence=pattern["confidence"],
                        )
                    )
                    # Also update title if it contains the name
                    if original.lower() in result.corrected_title.lower():
                        result.corrected_title = re.sub(
                            re.escape(original),
                            pattern["meaning"],
                            result.corrected_title,
                            flags=re.IGNORECASE,
                        )
                    break  # Only apply one pattern per person

        # Apply patterns to place names
        for i, place in enumerate(result.corrected_places):
            for pattern in self._pattern_cache:
                if self._matches_trigger(place, pattern["trigger"]):
                    original = result.corrected_places[i]
                    result.corrected_places[i] = pattern["meaning"]
                    result.patterns_applied.append(
                        AppliedPattern(
                            pattern_id=pattern["id"],
                            trigger=pattern["trigger"],
                            meaning=pattern["meaning"],
                            original_value=original,
                            corrected_value=pattern["meaning"],
                            pattern_type=pattern.get("pattern_type", "place"),
                            confidence=pattern["confidence"],
                        )
                    )
                    # Also update title if it contains the place
                    if original.lower() in result.corrected_title.lower():
                        result.corrected_title = re.sub(
                            re.escape(original),
                            pattern["meaning"],
                            result.corrected_title,
                            flags=re.IGNORECASE,
                        )
                    break  # Only apply one pattern per place

        # Apply patterns to title directly (for patterns not caught by entity matching)
        # This handles cases like "shopping" → priority change context
        for pattern in self._pattern_cache:
            norm_trigger = self._normalize(pattern["trigger"])
            norm_title = self._normalize(result.corrected_title)

            if norm_trigger in norm_title:
                # Check if this pattern was already applied
                already_applied = any(
                    p.pattern_id == pattern["id"] for p in result.patterns_applied
                )
                if not already_applied:
                    # For title-based patterns, we record but may not modify title
                    # (e.g., priority patterns affect priority, not title text)
                    result.patterns_applied.append(
                        AppliedPattern(
                            pattern_id=pattern["id"],
                            trigger=pattern["trigger"],
                            meaning=pattern["meaning"],
                            original_value=pattern["trigger"],
                            corrected_value=pattern["meaning"],
                            pattern_type=pattern.get("pattern_type", "name"),
                            confidence=pattern["confidence"],
                        )
                    )

        if result.has_corrections:
            logger.info(f"Applied patterns: {result.summary()}")

        return result

    async def update_pattern_usage(self, pattern_id: str) -> None:
        """Update a pattern's last_used timestamp after application.

        Args:
            pattern_id: Notion page ID of the pattern
        """
        try:
            # The update_pattern_confidence method also updates last_used
            await self.notion.update_pattern_confidence(
                page_id=pattern_id,
                times_confirmed=None,  # Don't change confirmation count
                confidence=None,  # Don't change confidence
            )
        except Exception as e:
            logger.warning(f"Failed to update pattern usage for {pattern_id}: {e}")

    def clear_cache(self) -> None:
        """Clear the pattern cache to force reload on next apply."""
        self._pattern_cache = []
        self._cache_loaded = False


# Module-level convenience functions

_applicator: PatternApplicator | None = None


def get_pattern_applicator() -> PatternApplicator:
    """Get or create the global PatternApplicator instance."""
    global _applicator
    if _applicator is None:
        _applicator = PatternApplicator()
    return _applicator


async def apply_patterns(
    text: str,
    people: list[str] | None = None,
    places: list[str] | None = None,
    title: str | None = None,
) -> PatternApplicationResult:
    """Apply stored patterns to input values.

    Convenience function that uses the global applicator.

    Args:
        text: Original input text
        people: Extracted people names
        places: Extracted place names
        title: Generated task title

    Returns:
        PatternApplicationResult with original and corrected values
    """
    return await get_pattern_applicator().apply_patterns(
        text=text,
        people=people,
        places=places,
        title=title,
    )


async def load_patterns() -> int:
    """Load applicable patterns from Notion.

    Convenience function that uses the global applicator.

    Returns:
        Number of patterns loaded
    """
    return await get_pattern_applicator().load_patterns()
