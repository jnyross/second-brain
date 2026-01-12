import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytz

from assistant.config import settings


@dataclass
class ParsedIntent:
    intent_type: str
    title: str
    confidence: int
    due_date: datetime | None = None
    due_timezone: str | None = None
    people: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    raw_text: str = ""


class Parser:
    TIME_PATTERNS = [
        (r"\b(\d{1,2})\s*(?::|\.)\s*(\d{2})\s*(am|pm)?\b", "time"),
        (r"\b(\d{1,2})\s*(am|pm)\b", "time_simple"),
        (r"\btomorrow\b", "tomorrow"),
        (r"\btoday\b", "today"),
        (r"\bmonday\b", "weekday"),
        (r"\btuesday\b", "weekday"),
        (r"\bwednesday\b", "weekday"),
        (r"\bthursday\b", "weekday"),
        (r"\bfriday\b", "weekday"),
        (r"\bsaturday\b", "weekday"),
        (r"\bsunday\b", "weekday"),
        (r"\bnext week\b", "next_week"),
        (r"\bin (\d+) (day|hour|minute|week)s?\b", "relative"),
    ]

    TASK_INDICATORS = [
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
    ]

    def __init__(self, timezone: str | None = None):
        self.timezone = pytz.timezone(timezone or settings.user_timezone)

    def parse(self, text: str) -> ParsedIntent:
        text_lower = text.lower()

        intent_type = self._detect_intent_type(text_lower)
        confidence = self._calculate_confidence(text_lower, intent_type)
        due_date, due_tz = self._extract_datetime(text_lower)
        people = self._extract_people(text)
        places = self._extract_places(text)
        title = self._generate_title(text, intent_type)

        return ParsedIntent(
            intent_type=intent_type,
            title=title,
            confidence=confidence,
            due_date=due_date,
            due_timezone=due_tz,
            people=people,
            places=places,
            raw_text=text,
        )

    def _detect_intent_type(self, text: str) -> str:
        for indicator in self.TASK_INDICATORS:
            if indicator in text:
                return "task"

        if any(word in text for word in ["idea", "thought", "maybe", "consider"]):
            return "idea"

        if any(word in text for word in ["remember", "note", "important"]):
            return "note"

        return "task"

    def _calculate_confidence(self, text: str, intent_type: str) -> int:
        confidence = 50

        has_verb = any(ind in text for ind in self.TASK_INDICATORS)
        if has_verb:
            confidence += 20

        has_time = any(re.search(pat, text) for pat, _ in self.TIME_PATTERNS)
        if has_time:
            confidence += 15

        words = text.split()
        if len(words) >= 3:
            confidence += 10

        filler_words = ["uhh", "umm", "like", "you know", "that thing"]
        if any(filler in text for filler in filler_words):
            confidence -= 30

        if "?" in text:
            confidence -= 10

        return max(0, min(100, confidence))

    def _extract_datetime(self, text: str) -> tuple[datetime | None, str | None]:
        now = datetime.now(self.timezone)

        if "tomorrow" in text:
            date = now + timedelta(days=1)
            time_match = self._extract_time(text)
            if time_match:
                date = date.replace(hour=time_match[0], minute=time_match[1])
            else:
                date = date.replace(hour=9, minute=0)
            return date, str(self.timezone)

        if "today" in text:
            date = now
            time_match = self._extract_time(text)
            if time_match:
                date = date.replace(hour=time_match[0], minute=time_match[1])
            return date, str(self.timezone)

        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        for day_name, day_num in weekdays.items():
            if day_name in text:
                days_ahead = day_num - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                date = now + timedelta(days=days_ahead)
                time_match = self._extract_time(text)
                if time_match:
                    date = date.replace(hour=time_match[0], minute=time_match[1])
                else:
                    date = date.replace(hour=9, minute=0)
                return date, str(self.timezone)

        relative_match = re.search(r"in (\d+) (day|hour|minute|week)s?", text)
        if relative_match:
            amount = int(relative_match.group(1))
            unit = relative_match.group(2)
            if unit == "minute":
                date = now + timedelta(minutes=amount)
            elif unit == "hour":
                date = now + timedelta(hours=amount)
            elif unit == "day":
                date = now + timedelta(days=amount)
            elif unit == "week":
                date = now + timedelta(weeks=amount)
            else:
                return None, None
            return date, str(self.timezone)

        time_match = self._extract_time(text)
        if time_match:
            date = now.replace(hour=time_match[0], minute=time_match[1])
            if date < now:
                date += timedelta(days=1)
            return date, str(self.timezone)

        return None, None

    def _extract_time(self, text: str) -> tuple[int, int] | None:
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

    def _extract_people(self, text: str) -> list[str]:
        words = text.split()
        people = []

        with_pattern = re.search(r"with\s+([A-Z][a-z]+)", text)
        if with_pattern:
            people.append(with_pattern.group(1))

        for i, word in enumerate(words):
            if word[0].isupper() and len(word) > 1:
                if i > 0 and words[i - 1].lower() not in ["i", "the", "a", "an", "at", "on", "in"]:
                    if word.lower() not in [
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                        "january",
                        "february",
                        "march",
                        "april",
                        "may",
                        "june",
                        "july",
                        "august",
                        "september",
                        "october",
                        "november",
                        "december",
                    ]:
                        if word not in people:
                            people.append(word)

        return people

    def _extract_places(self, text: str) -> list[str]:
        places = []

        at_pattern = re.search(r"at\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text)
        if at_pattern:
            places.append(at_pattern.group(1))

        return places

    def _generate_title(self, text: str, intent_type: str) -> str:
        title = text.strip()

        time_patterns = [
            r"\btomorrow\b",
            r"\btoday\b",
            r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
            r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
        ]

        for pattern in time_patterns:
            title = re.sub(pattern, "", title, flags=re.IGNORECASE)

        title = re.sub(r"\s+", " ", title).strip()

        if len(title) > 100:
            title = title[:97] + "..."

        return title or text[:50]
