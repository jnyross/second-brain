"""Entity extraction service for Second Brain.

Extracts structured entities (people, dates, places) from natural language input.
Designed for extensibility with future Google Maps integration and NLP enhancements.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import pytz

from assistant.config import settings


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
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None


@dataclass
class ExtractedDate:
    """A date/time entity extracted from text."""
    datetime_value: datetime
    confidence: int  # 0-100
    original_text: str  # The matched text fragment
    timezone: str = "UTC"
    is_relative: bool = False  # "tomorrow" vs "2024-01-15"


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

    def __init__(self, timezone: str | None = None):
        self.timezone = pytz.timezone(timezone or settings.user_timezone)

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

        Handles:
        - Relative dates: "tomorrow", "today", weekdays
        - Relative times: "in 2 hours", "in 30 minutes"
        - Explicit times: "3pm", "14:30"

        Args:
            text: Natural language input text

        Returns:
            List of ExtractedDate entities
        """
        dates = []
        text_lower = text.lower()
        now = datetime.now(self.timezone)

        # Check for "tomorrow"
        if "tomorrow" in text_lower:
            dt = now + timedelta(days=1)
            time_tuple = self._extract_time(text_lower)
            if time_tuple:
                dt = dt.replace(hour=time_tuple[0], minute=time_tuple[1])
            else:
                dt = dt.replace(hour=9, minute=0)  # Default to 9am
            dates.append(ExtractedDate(
                datetime_value=dt,
                confidence=95,
                original_text="tomorrow",
                timezone=str(self.timezone),
                is_relative=True,
            ))

        # Check for "today"
        if "today" in text_lower:
            dt = now
            time_tuple = self._extract_time(text_lower)
            if time_tuple:
                dt = dt.replace(hour=time_tuple[0], minute=time_tuple[1])
            dates.append(ExtractedDate(
                datetime_value=dt,
                confidence=95,
                original_text="today",
                timezone=str(self.timezone),
                is_relative=True,
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
                time_tuple = self._extract_time(text_lower)
                if time_tuple:
                    dt = dt.replace(hour=time_tuple[0], minute=time_tuple[1])
                else:
                    dt = dt.replace(hour=9, minute=0)
                dates.append(ExtractedDate(
                    datetime_value=dt,
                    confidence=90,
                    original_text=day_name,
                    timezone=str(self.timezone),
                    is_relative=True,
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
                timezone=str(self.timezone),
                is_relative=True,
            ))

        # Check for standalone time (if no date context found yet)
        if not dates:
            time_tuple = self._extract_time(text_lower)
            if time_tuple:
                dt = now.replace(hour=time_tuple[0], minute=time_tuple[1])
                if dt < now:
                    dt += timedelta(days=1)
                dates.append(ExtractedDate(
                    datetime_value=dt,
                    confidence=75,
                    original_text=f"{time_tuple[0]}:{time_tuple[1]:02d}",
                    timezone=str(self.timezone),
                    is_relative=False,
                ))

        return dates

    def _extract_time(self, text: str) -> Optional[tuple[int, int]]:
        """Extract time (hour, minute) from text.

        Args:
            text: Lowercase text to search

        Returns:
            Tuple of (hour, minute) in 24-hour format, or None
        """
        # "3:30pm" or "3.30 pm"
        match = re.search(r"(\d{1,2})\s*(?::|\.)\s*(\d{2})\s*(am|pm)?", text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            ampm = match.group(3)
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return (hour, minute)

        # "3pm" or "3 pm"
        match = re.search(r"(\d{1,2})\s*(am|pm)", text)
        if match:
            hour = int(match.group(1))
            ampm = match.group(2)
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return (hour, 0)

        return None
