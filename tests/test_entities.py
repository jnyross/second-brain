"""Tests for the entity extraction service."""

import pytest
from datetime import datetime, timedelta

from assistant.services.entities import (
    EntityExtractor,
    ExtractedEntities,
    ExtractedPerson,
    ExtractedPlace,
    ExtractedDate,
)


class TestEntityExtractor:
    """Test suite for EntityExtractor."""

    def setup_method(self):
        self.extractor = EntityExtractor(timezone="America/Los_Angeles")

    # === People Extraction Tests ===

    def test_extract_person_with_pattern(self):
        """'with Name' pattern should have high confidence."""
        result = self.extractor.extract_people("Lunch with Sarah")
        assert len(result) == 1
        assert result[0].name == "Sarah"
        assert result[0].confidence >= 85

    def test_extract_person_call_pattern(self):
        """'call Name' pattern should extract person."""
        result = self.extractor.extract_people("Call John tomorrow")
        assert len(result) >= 1
        assert result[0].name == "John"
        assert result[0].confidence >= 60

    def test_extract_person_email_pattern(self):
        """'email Name' pattern should extract person."""
        result = self.extractor.extract_people("Email Mike about the project")
        assert len(result) >= 1
        assert result[0].name == "Mike"

    def test_extract_multiple_people(self):
        """Should extract multiple people from text."""
        result = self.extractor.extract_people("Meet with Alice and call Bob")
        names = [p.name for p in result]
        assert "Alice" in names
        assert "Bob" in names

    def test_no_false_positive_weekdays(self):
        """Weekday names should not be extracted as people."""
        result = self.extractor.extract_people("Call mom Monday")
        names = [p.name for p in result]
        assert "Monday" not in names

    def test_no_false_positive_months(self):
        """Month names should not be extracted as people."""
        result = self.extractor.extract_people("Meeting in March")
        names = [p.name for p in result]
        assert "March" not in names

    def test_extract_full_name(self):
        """Should extract full names (first + last)."""
        result = self.extractor.extract_people("Lunch with Sarah Chen")
        assert len(result) >= 1
        # Should capture at least "Sarah Chen" or "Sarah"
        assert any("Sarah" in p.name for p in result)

    # === Places Extraction Tests ===

    def test_extract_place_at_pattern(self):
        """'at Place' pattern should extract place."""
        result = self.extractor.extract_places("Dinner at Everyman")
        assert len(result) == 1
        assert result[0].name == "Everyman"
        assert result[0].confidence >= 75

    def test_extract_place_near_pattern(self):
        """'near Place' pattern should extract place."""
        result = self.extractor.extract_places("Meet me near Starbucks")
        assert len(result) == 1
        assert result[0].name == "Starbucks"

    def test_extract_multi_word_place(self):
        """Should extract multi-word place names."""
        result = self.extractor.extract_places("Lunch at The Coffee Shop")
        assert len(result) >= 1
        assert any("Coffee" in p.name for p in result)

    # === Date Extraction Tests ===

    def test_extract_tomorrow(self):
        """'tomorrow' should extract a date."""
        result = self.extractor.extract_dates("Call dentist tomorrow")
        assert len(result) >= 1
        tomorrow = datetime.now().date() + timedelta(days=1)
        assert result[0].datetime_value.date() == tomorrow
        assert result[0].is_relative is True
        assert result[0].confidence >= 90

    def test_extract_today(self):
        """'today' should extract today's date."""
        result = self.extractor.extract_dates("Finish report today")
        assert len(result) >= 1
        assert result[0].datetime_value.date() == datetime.now().date()

    def test_extract_weekday(self):
        """Weekday names should extract the next occurrence."""
        result = self.extractor.extract_dates("Meeting Friday")
        assert len(result) >= 1
        assert result[0].datetime_value.weekday() == 4  # Friday
        assert result[0].is_relative is True

    def test_extract_relative_hours(self):
        """'in X hours' should extract relative time."""
        result = self.extractor.extract_dates("Remind me in 2 hours")
        assert len(result) >= 1
        # Compare timezone-aware datetimes properly
        import pytz
        tz = pytz.timezone("America/Los_Angeles")
        expected = datetime.now(tz) + timedelta(hours=2)
        actual = result[0].datetime_value
        assert abs((actual - expected).total_seconds()) < 120

    def test_extract_relative_days(self):
        """'in X days' should extract relative date."""
        result = self.extractor.extract_dates("Due in 3 days")
        assert len(result) >= 1
        expected = datetime.now().date() + timedelta(days=3)
        assert result[0].datetime_value.date() == expected

    def test_extract_time_pm(self):
        """'3pm' should extract afternoon time."""
        result = self.extractor.extract_dates("Meeting at 3pm")
        assert len(result) >= 1
        assert result[0].datetime_value.hour == 15

    def test_extract_time_with_minutes(self):
        """'3:30pm' should extract time with minutes."""
        result = self.extractor.extract_dates("Call at 3:30pm")
        assert len(result) >= 1
        assert result[0].datetime_value.hour == 15
        assert result[0].datetime_value.minute == 30

    def test_extract_tomorrow_with_time(self):
        """'tomorrow at 2pm' should combine date and time."""
        result = self.extractor.extract_dates("Meeting tomorrow at 2pm")
        assert len(result) >= 1
        tomorrow = datetime.now().date() + timedelta(days=1)
        assert result[0].datetime_value.date() == tomorrow
        assert result[0].datetime_value.hour == 14

    # === Combined Extraction Tests ===

    def test_extract_all_entities(self):
        """extract() should return all entity types."""
        result = self.extractor.extract("Lunch with Sarah at Everyman tomorrow at noon")
        assert isinstance(result, ExtractedEntities)
        assert len(result.people) >= 1
        assert len(result.places) >= 1
        assert len(result.dates) >= 1
        assert result.raw_text == "Lunch with Sarah at Everyman tomorrow at noon"

    def test_extract_no_entities(self):
        """Should handle text with no entities gracefully."""
        result = self.extractor.extract("buy milk")
        assert isinstance(result, ExtractedEntities)
        assert len(result.people) == 0
        assert len(result.places) == 0
        # May still extract implicit "today" or not

    def test_extracted_entities_raw_text(self):
        """ExtractedEntities should preserve raw text."""
        text = "Call Bob tomorrow"
        result = self.extractor.extract(text)
        assert result.raw_text == text
