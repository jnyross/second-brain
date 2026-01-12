"""Entity extraction service for Second Brain.

Extracts structured entities (people, dates, places) from natural language input.
Designed for extensibility with future Google Maps integration and NLP enhancements.

Implements PRD Section 5.4 timezone handling:
- All times parsed in user's configured timezone
- Explicit timezone markers (e.g., "9am EST") are respected
- Due dates formatted as ISO 8601 with timezone offset
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from assistant.services.timezone import (
    TIMEZONE_ABBREVIATIONS,
    TimezoneService,
)


@dataclass
class ExtractedPerson:
    """A person entity extracted from text."""
    name: str
    confidence: int  # 0-100
    context: str = ""  # The surrounding context where found


@dataclass
class ExtractedPlace:
    """A place entity extracted from text."""
    name: str
    confidence: int  # 0-100
    context: str = ""
    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None


@dataclass
class ExtractedDate:
    """A date/time entity extracted from text.

    Per PRD Section 5.4:
    - datetime_value is always timezone-aware
    - timezone field contains the IANA timezone name
    - Use to_iso8601() for proper ISO 8601 formatting with offset
    """
    datetime_value: datetime
    confidence: int  # 0-100
    original_text: str  # The matched text fragment
    timezone: str = "UTC"  # IANA timezone name (e.g., "America/Los_Angeles")
    is_relative: bool = False  # "tomorrow" vs "2024-01-15"
    has_explicit_timezone: bool = False  # True if user specified timezone (e.g., "9am EST")

    def to_iso8601(self) -> str:
        """Format as ISO 8601 string with timezone offset.

        Example: 2024-01-15T14:00:00-08:00
        """
        return self.datetime_value.isoformat()

    def to_iso8601_utc(self) -> str:
        """Format as ISO 8601 string in UTC with Z suffix.

        Example: 2024-01-15T22:00:00Z
        """
        utc_dt = self.datetime_value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ExtractedEntities:
    """Container for all extracted entities from text."""
    people: list[ExtractedPerson] = field(default_factory=list)
    places: list[ExtractedPlace] = field(default_factory=list)
    dates: list[ExtractedDate] = field(default_factory=list)
    raw_text: str = ""


class EntityExtractor:
    """Extracts entities (people, dates, places) from natural language text.

    Uses pattern matching and heuristics. Designed to be extended with
    Google Maps geocoding and NLP enhancements.

    Per PRD Section 5.4:
    - All times are parsed in user's configured timezone by default
    - Explicit timezone markers (e.g., "9am EST") override the default
    - Results include IANA timezone name for due_timezone field
    """

    # Words that look like names but aren't people
    NOT_PEOPLE = frozenset([
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "morning", "afternoon", "evening", "night",
        "today", "tomorrow", "yesterday",
    ])

    # Words that typically precede a proper noun but don't indicate a person
    NON_PERSON_PREFIXES = frozenset([
        "i", "the", "a", "an", "at", "on", "in", "to", "from", "by",
    ])

    # Patterns for place detection
    PLACE_PATTERNS = [
        r"at\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",  # "at Starbucks" or "at The Coffee Shop"
        r"(?:near|by|around)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
        r"(?:going to|heading to|meet at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
    ]

    # Patterns for time extraction
    TIME_PATTERNS = [
        (r"\b(\d{1,2})\s*(?::|\.)\s*(\d{2})\s*(am|pm)?\b", "full_time"),
        (r"\b(\d{1,2})\s*(am|pm)\b", "simple_time"),
        (r"\btomorrow\b", "tomorrow"),
        (r"\btoday\b", "today"),
        (r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "weekday"),
        (r"\bnext week\b", "next_week"),
        (r"\bin (\d+) (day|hour|minute|week)s?\b", "relative"),
    ]

    # Pattern for explicit timezone markers (e.g., "9am EST", "2pm PST")
    EXPLICIT_TZ_PATTERN = re.compile(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(" +
        "|".join(re.escape(tz) for tz in TIMEZONE_ABBREVIATIONS.keys()) +
        r")\b",
        re.IGNORECASE,
    )

    def __init__(self, timezone: str | None = None):
        """Initialize entity extractor.

        Args:
            timezone: IANA timezone name (e.g., "America/Los_Angeles").
                     Defaults to settings.user_timezone.
        """
        self._tz_service = TimezoneService(timezone)
        self._tz_name = self._tz_service.default_timezone
        self._tz = ZoneInfo(self._tz_name)

    def extract(self, text: str) -> ExtractedEntities:
        """Extract all entities from the given text.

        Args:
            text: Natural language input text

        Returns:
            ExtractedEntities containing all found entities
        """
        return ExtractedEntities(
            people=self.extract_people(text),
            places=self.extract_places(text),
            dates=self.extract_dates(text),
            raw_text=text,
        )

    def extract_people(self, text: str) -> list[ExtractedPerson]:
        """Extract person names from text.

        Uses multiple strategies:
        1. "with [Name]" pattern (high confidence)
        2. "call/email/meet [Name]" patterns (high confidence)
        3. Capitalized words in non-sentence-start positions (medium confidence)

        Args:
            text: Natural language input text

        Returns:
            List of ExtractedPerson entities
        """
        people = []
        seen_names = set()

        # Strategy 1: "with Name" pattern - high confidence
        with_matches = re.finditer(r"\bwith\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text)
        for match in with_matches:
            name = match.group(1)
            if name.lower() not in self.NOT_PEOPLE and name not in seen_names:
                people.append(ExtractedPerson(
                    name=name,
                    confidence=90,
                    context=match.group(0),
                ))
                seen_names.add(name)

        # Strategy 2: "call/email/meet Name" patterns - high confidence
        # Match action verb (case-insensitive) followed by capitalized name
        action_patterns = [
            r"\b(?:[Cc]all|[Ee]mail|[Tt]ext|[Mm]eet|[Ss]ee|[Cc]ontact)\s+([A-Z][a-z]+)",
            r"\b[Tt]ell\s+([A-Z][a-z]+)",
            r"\b[Aa]sk\s+([A-Z][a-z]+)",
        ]
        for pattern in action_patterns:
            for match in re.finditer(pattern, text):
                name = match.group(1)
                if name.lower() not in self.NOT_PEOPLE and name not in seen_names:
                    people.append(ExtractedPerson(
                        name=name,
                        confidence=85,
                        context=match.group(0),
                    ))
                    seen_names.add(name)

        # Strategy 3: Capitalized words (not at sentence start) - medium confidence
        words = text.split()
        for i, word in enumerate(words):
            # Skip first word of sentence
            if i == 0:
                continue
            # Check previous word ends with sentence-ending punctuation
            if i > 0 and words[i-1][-1] in ".!?":
                continue

            # Check for capitalized word
            if word and word[0].isupper() and len(word) > 1:
                # Clean punctuation
                clean_word = word.rstrip(".,!?;:")

                # Skip if it's not a name-like word
                if clean_word.lower() in self.NOT_PEOPLE:
                    continue
                if i > 0 and words[i-1].lower() in self.NON_PERSON_PREFIXES:
                    continue
                if clean_word in seen_names:
                    continue

                people.append(ExtractedPerson(
                    name=clean_word,
                    confidence=60,
                    context=f"...{words[max(0,i-2):i+2]}...",
                ))
                seen_names.add(clean_word)

        return people

    def extract_places(self, text: str) -> list[ExtractedPlace]:
        """Extract place names from text.

        Uses pattern matching for common place indicators.
        Future: Will integrate with Google Maps for geocoding.

        Args:
            text: Natural language input text

        Returns:
            List of ExtractedPlace entities
        """
        places = []
        seen_places = set()

        for pattern in self.PLACE_PATTERNS:
            for match in re.finditer(pattern, text):
                place_name = match.group(1)
                if place_name.lower() not in self.NOT_PEOPLE and place_name not in seen_places:
                    places.append(ExtractedPlace(
                        name=place_name,
                        confidence=80,
                        context=match.group(0),
                    ))
                    seen_places.add(place_name)

        return places

    def extract_dates(self, text: str) -> list[ExtractedDate]:
        """Extract date/time references from text.

        Handles per PRD Section 5.4:
        - Relative dates: "tomorrow", "today", weekdays
        - Relative times: "in 2 hours", "in 30 minutes"
        - Explicit times: "3pm", "14:30"
        - Explicit timezones: "9am EST" uses America/New_York

        Args:
            text: Natural language input text

        Returns:
            List of ExtractedDate entities with timezone-aware datetimes
        """
        dates = []
        text_lower = text.lower()
        now = datetime.now(self._tz)

        # Check for explicit timezone marker first (e.g., "9am EST")
        explicit_tz_match = self.EXPLICIT_TZ_PATTERN.search(text)
        explicit_tz_name: str | None = None
        has_explicit_tz = False
        if explicit_tz_match:
            tz_abbrev = explicit_tz_match.group(4).upper()
            if tz_abbrev in TIMEZONE_ABBREVIATIONS:
                explicit_tz_name = TIMEZONE_ABBREVIATIONS[tz_abbrev]
                has_explicit_tz = True

        # Determine which timezone to use for parsing
        parse_tz_name = explicit_tz_name or self._tz_name
        parse_tz = ZoneInfo(parse_tz_name)

        # Check for "tomorrow"
        if "tomorrow" in text_lower:
            dt = now + timedelta(days=1)
            time_result = self._extract_time_with_explicit_tz(text, text_lower)
            if time_result:
                hour, minute, tz_name = time_result
                if tz_name:
                    parse_tz_name = tz_name
                    parse_tz = ZoneInfo(tz_name)
                    has_explicit_tz = True
                dt = dt.replace(hour=hour, minute=minute, tzinfo=parse_tz)
            else:
                dt = dt.replace(hour=9, minute=0, tzinfo=parse_tz)  # Default to 9am
            dates.append(ExtractedDate(
                datetime_value=dt,
                confidence=95,
                original_text="tomorrow",
                timezone=parse_tz_name,
                is_relative=True,
                has_explicit_timezone=has_explicit_tz,
            ))

        # Check for "today"
        if "today" in text_lower:
            dt = now
            time_result = self._extract_time_with_explicit_tz(text, text_lower)
            if time_result:
                hour, minute, tz_name = time_result
                if tz_name:
                    parse_tz_name = tz_name
                    parse_tz = ZoneInfo(tz_name)
                    has_explicit_tz = True
                dt = dt.replace(hour=hour, minute=minute, tzinfo=parse_tz)
            dates.append(ExtractedDate(
                datetime_value=dt,
                confidence=95,
                original_text="today",
                timezone=parse_tz_name,
                is_relative=True,
                has_explicit_timezone=has_explicit_tz,
            ))

        # Check for weekdays
        weekdays = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }
        for day_name, day_num in weekdays.items():
            if day_name in text_lower:
                days_ahead = day_num - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                dt = now + timedelta(days=days_ahead)
                time_result = self._extract_time_with_explicit_tz(text, text_lower)
                if time_result:
                    hour, minute, tz_name = time_result
                    if tz_name:
                        parse_tz_name = tz_name
                        parse_tz = ZoneInfo(tz_name)
                        has_explicit_tz = True
                    dt = dt.replace(hour=hour, minute=minute, tzinfo=parse_tz)
                else:
                    dt = dt.replace(hour=9, minute=0, tzinfo=parse_tz)
                dates.append(ExtractedDate(
                    datetime_value=dt,
                    confidence=90,
                    original_text=day_name,
                    timezone=parse_tz_name,
                    is_relative=True,
                    has_explicit_timezone=has_explicit_tz,
                ))

        # Check for relative time ("in X hours/days/minutes")
        relative_match = re.search(r"in (\d+) (day|hour|minute|week)s?", text_lower)
        if relative_match:
            amount = int(relative_match.group(1))
            unit = relative_match.group(2)
            if unit == "minute":
                dt = now + timedelta(minutes=amount)
            elif unit == "hour":
                dt = now + timedelta(hours=amount)
            elif unit == "day":
                dt = now + timedelta(days=amount)
            elif unit == "week":
                dt = now + timedelta(weeks=amount)
            else:
                dt = now
            dates.append(ExtractedDate(
                datetime_value=dt,
                confidence=90,
                original_text=relative_match.group(0),
                timezone=self._tz_name,  # Relative times always use user timezone
                is_relative=True,
                has_explicit_timezone=False,
            ))

        # Check for standalone time (if no date context found yet)
        if not dates:
            time_result = self._extract_time_with_explicit_tz(text, text_lower)
            if time_result:
                hour, minute, tz_name = time_result
                if tz_name:
                    parse_tz_name = tz_name
                    parse_tz = ZoneInfo(tz_name)
                    has_explicit_tz = True
                dt = now.replace(hour=hour, minute=minute, tzinfo=parse_tz)
                if dt < datetime.now(parse_tz):
                    dt += timedelta(days=1)
                dates.append(ExtractedDate(
                    datetime_value=dt,
                    confidence=75,
                    original_text=f"{hour}:{minute:02d}",
                    timezone=parse_tz_name,
                    is_relative=False,
                    has_explicit_timezone=has_explicit_tz,
                ))

        return dates

    def _extract_time(self, text: str) -> tuple[int, int] | None:
        """Extract time (hour, minute) from text.

        Args:
            text: Lowercase text to search

        Returns:
            Tuple of (hour, minute) in 24-hour format, or None
        """
        result = self._extract_time_with_explicit_tz(text, text)
        if result:
            return (result[0], result[1])
        return None

    def _extract_time_with_explicit_tz(
        self, original_text: str, text_lower: str
    ) -> tuple[int, int, str | None] | None:
        """Extract time with optional explicit timezone from text.

        Args:
            original_text: Original text (for case-sensitive timezone match)
            text_lower: Lowercase text for time extraction

        Returns:
            Tuple of (hour, minute, timezone_name) where timezone_name is an
            IANA timezone string if explicitly specified, or None if not.
        """
        # First check for explicit timezone pattern (e.g., "9am EST")
        explicit_match = self.EXPLICIT_TZ_PATTERN.search(original_text)
        if explicit_match:
            hour = int(explicit_match.group(1))
            minute = int(explicit_match.group(2)) if explicit_match.group(2) else 0
            ampm = explicit_match.group(3).lower() if explicit_match.group(3) else None
            tz_abbrev = explicit_match.group(4).upper()

            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0

            if tz_abbrev in TIMEZONE_ABBREVIATIONS:
                return (hour, minute, TIMEZONE_ABBREVIATIONS[tz_abbrev])

        # "3:30pm" or "3.30 pm"
        match = re.search(r"(\d{1,2})\s*(?::|\.)\s*(\d{2})\s*(am|pm)?", text_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            ampm = match.group(3)
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return (hour, minute, None)

        # "3pm" or "3 pm"
        match = re.search(r"(\d{1,2})\s*(am|pm)", text_lower)
        if match:
            hour = int(match.group(1))
            ampm = match.group(2)
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return (hour, 0, None)

        return None
