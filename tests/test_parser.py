import pytest
import pytz
from datetime import datetime, timedelta
from assistant.services.parser import Parser, ParsedIntent


class TestParser:
    def setup_method(self):
        self.parser = Parser(timezone="America/Los_Angeles")

    def test_parse_simple_task(self):
        result = self.parser.parse("Buy milk")
        assert result.intent_type == "task"
        assert "milk" in result.title.lower()
        assert result.confidence >= 50

    def test_parse_task_with_tomorrow(self):
        result = self.parser.parse("Call dentist tomorrow")
        assert result.intent_type == "task"
        assert result.due_date is not None
        assert result.due_date.date() == (datetime.now().date() + timedelta(days=1))

    def test_parse_task_with_time(self):
        result = self.parser.parse("Meeting at 2pm")
        assert result.due_date is not None
        assert result.due_date.hour == 14

    def test_parse_task_with_person(self):
        result = self.parser.parse("Lunch with Sarah")
        assert "Sarah" in result.people

    def test_parse_task_with_place(self):
        result = self.parser.parse("Dinner at Everyman")
        assert "Everyman" in result.places

    def test_parse_unclear_message(self):
        result = self.parser.parse("uhh that thing you know")
        assert result.confidence < 80

    def test_parse_weekday(self):
        result = self.parser.parse("Call mom Friday")
        assert result.due_date is not None
        assert result.due_date.weekday() == 4

    def test_parse_relative_time(self):
        result = self.parser.parse("Remind me in 2 hours")
        assert result.due_date is not None
        # Use timezone-aware comparison since parser uses configured timezone
        tz = pytz.timezone("America/Los_Angeles")
        expected = datetime.now(tz) + timedelta(hours=2)
        assert abs((result.due_date - expected).total_seconds()) < 60

    def test_high_confidence_with_verb_and_time(self):
        result = self.parser.parse("Buy groceries tomorrow at 5pm")
        assert result.confidence >= 80

    def test_title_generation_removes_time(self):
        result = self.parser.parse("Call dentist tomorrow at 3pm")
        assert "tomorrow" not in result.title.lower()
        assert "3pm" not in result.title.lower()
        assert "dentist" in result.title.lower()
