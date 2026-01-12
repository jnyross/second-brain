"""Tests for the entity extraction service."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from assistant.services.entities import (
    EntityExtractor,
    ExtractedDate,
    ExtractedEntities,
)


class TestEntityExtractor:
    """Test suite for EntityExtractor."""

    def setup_method(self):
        self.extractor = EntityExtractor(timezone="America/Los_Angeles")
        self.tz = ZoneInfo("America/Los_Angeles")

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
        """'tomorrow' should extract a date in user timezone."""
        result = self.extractor.extract_dates("Call dentist tomorrow")
        assert len(result) >= 1

        # Use timezone-aware comparison
        now = datetime.now(self.tz)
        tomorrow = (now + timedelta(days=1)).date()
        assert result[0].datetime_value.date() == tomorrow
        assert result[0].is_relative is True
        assert result[0].confidence >= 90
        assert result[0].timezone == "America/Los_Angeles"

    def test_extract_today(self):
        """'today' should extract today's date in user timezone."""
        result = self.extractor.extract_dates("Finish report today")
        assert len(result) >= 1

        # Use timezone-aware comparison
        now = datetime.now(self.tz)
        assert result[0].datetime_value.date() == now.date()
        assert result[0].timezone == "America/Los_Angeles"

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
        expected = datetime.now(self.tz) + timedelta(hours=2)
        actual = result[0].datetime_value
        assert abs((actual - expected).total_seconds()) < 120

    def test_extract_relative_days(self):
        """'in X days' should extract relative date."""
        result = self.extractor.extract_dates("Due in 3 days")
        assert len(result) >= 1

        # Use timezone-aware comparison
        now = datetime.now(self.tz)
        expected = (now + timedelta(days=3)).date()
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

        # Use timezone-aware comparison
        now = datetime.now(self.tz)
        tomorrow = (now + timedelta(days=1)).date()
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


class TestTimezoneHandling:
    """Tests for PRD Section 5.4 timezone handling (AT-119)."""

    def setup_method(self):
        # User timezone is America/Los_Angeles (PST/PDT)
        self.extractor = EntityExtractor(timezone="America/Los_Angeles")
        self.tz = ZoneInfo("America/Los_Angeles")

    def test_times_parsed_in_user_timezone(self):
        """Times should be parsed in user's configured timezone."""
        result = self.extractor.extract_dates("Meeting tomorrow at 2pm")
        assert len(result) >= 1
        assert result[0].timezone == "America/Los_Angeles"
        assert result[0].datetime_value.tzinfo is not None

    def test_due_timezone_field_set(self):
        """ExtractedDate.timezone should contain IANA timezone name."""
        result = self.extractor.extract_dates("Call at 3pm")
        assert len(result) >= 1
        assert result[0].timezone == "America/Los_Angeles"

    def test_explicit_timezone_est_respected(self):
        """'9am EST' should use America/New_York timezone."""
        result = self.extractor.extract_dates("Call at 9am EST")
        assert len(result) >= 1
        assert result[0].timezone == "America/New_York"
        assert result[0].has_explicit_timezone is True
        assert result[0].datetime_value.hour == 9

    def test_explicit_timezone_pst_respected(self):
        """'2pm PST' should use America/Los_Angeles timezone."""
        result = self.extractor.extract_dates("Meeting at 2pm PST")
        assert len(result) >= 1
        assert result[0].timezone == "America/Los_Angeles"
        assert result[0].has_explicit_timezone is True

    def test_explicit_timezone_utc_respected(self):
        """'10am UTC' should use UTC timezone."""
        result = self.extractor.extract_dates("Meeting at 10am UTC")
        assert len(result) >= 1
        assert result[0].timezone == "UTC"
        assert result[0].has_explicit_timezone is True

    def test_explicit_timezone_with_tomorrow(self):
        """'tomorrow 9am EST' should combine date with explicit timezone."""
        result = self.extractor.extract_dates("Meeting tomorrow at 9am EST")
        assert len(result) >= 1
        assert result[0].timezone == "America/New_York"
        assert result[0].has_explicit_timezone is True
        assert result[0].datetime_value.hour == 9

    def test_no_explicit_timezone_flag_default(self):
        """has_explicit_timezone should be False when not specified."""
        result = self.extractor.extract_dates("Meeting tomorrow at 2pm")
        assert len(result) >= 1
        assert result[0].has_explicit_timezone is False

    def test_iso8601_formatting(self):
        """ExtractedDate should format as ISO 8601 with timezone offset."""
        result = self.extractor.extract_dates("Meeting at 2pm")
        assert len(result) >= 1
        iso_str = result[0].to_iso8601()
        # Should contain offset like -08:00 or -07:00
        assert "+" in iso_str or "-" in iso_str[-6:]

    def test_iso8601_utc_formatting(self):
        """ExtractedDate should format as ISO 8601 UTC with Z suffix."""
        result = self.extractor.extract_dates("Meeting at 2pm")
        assert len(result) >= 1
        utc_str = result[0].to_iso8601_utc()
        assert utc_str.endswith("Z")

    def test_at119_acceptance(self):
        """AT-119: Full acceptance test for timezone parsing.

        Given: User timezone is "America/Los_Angeles" (PST/PDT)
        When: User sends "tomorrow 2pm"
        Then: due_date stored as 2pm in PST/PDT
        And: due_timezone field set to "America/Los_Angeles"
        """
        result = self.extractor.extract_dates("tomorrow 2pm")
        assert len(result) >= 1
        assert result[0].datetime_value.hour == 14
        assert result[0].timezone == "America/Los_Angeles"

        # Verify ISO 8601 includes timezone offset (PST is -08:00, PDT is -07:00)
        iso_str = result[0].to_iso8601()
        assert "T14:" in iso_str  # Hour is 14 (2pm)
        assert "-08:00" in iso_str or "-07:00" in iso_str  # PST/PDT offset


class TestExtractedDate:
    """Tests for ExtractedDate dataclass."""

    def test_to_iso8601(self):
        """to_iso8601 should include timezone offset."""
        tz = ZoneInfo("America/Los_Angeles")
        dt = datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)
        extracted = ExtractedDate(
            datetime_value=dt,
            confidence=95,
            original_text="2pm",
            timezone="America/Los_Angeles",
        )
        iso_str = extracted.to_iso8601()
        assert iso_str.startswith("2024-01-15T14:00:00")
        # Should have offset
        assert "-08:00" in iso_str or "-07:00" in iso_str

    def test_to_iso8601_utc(self):
        """to_iso8601_utc should convert to UTC with Z suffix."""
        tz = ZoneInfo("America/Los_Angeles")
        dt = datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)  # 2pm PST = 10pm UTC
        extracted = ExtractedDate(
            datetime_value=dt,
            confidence=95,
            original_text="2pm",
            timezone="America/Los_Angeles",
        )
        utc_str = extracted.to_iso8601_utc()
        assert utc_str.endswith("Z")
        # 2pm PST is 10pm UTC
        assert "T22:00:00Z" in utc_str

    def test_has_explicit_timezone_default(self):
        """has_explicit_timezone should default to False."""
        dt = datetime.now(ZoneInfo("UTC"))
        extracted = ExtractedDate(
            datetime_value=dt,
            confidence=95,
            original_text="now",
            timezone="UTC",
        )
        assert extracted.has_explicit_timezone is False


class TestTimezoneAbbreviations:
    """Tests for timezone abbreviation support."""

    def setup_method(self):
        self.extractor = EntityExtractor(timezone="America/Los_Angeles")

    @pytest.mark.parametrize("abbrev,expected_tz", [
        ("EST", "America/New_York"),
        ("PST", "America/Los_Angeles"),
        ("CST", "America/Chicago"),
        ("MST", "America/Denver"),
        ("UTC", "UTC"),
        ("GMT", "Europe/London"),
    ])
    def test_timezone_abbreviation_mapping(self, abbrev, expected_tz):
        """Common timezone abbreviations should map to IANA timezones."""
        result = self.extractor.extract_dates(f"Meeting at 9am {abbrev}")
        assert len(result) >= 1
        assert result[0].timezone == expected_tz

    def test_timezone_case_insensitive(self):
        """Timezone abbreviations should be case-insensitive."""
        result = self.extractor.extract_dates("Meeting at 9am est")
        assert len(result) >= 1
        assert result[0].timezone == "America/New_York"
