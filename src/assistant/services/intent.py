from dataclasses import dataclass, field
from datetime import datetime


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
