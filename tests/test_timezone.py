"""Tests for the timezone handling service (T-116).

Tests PRD Section 5.4 requirements:
- User-configured timezone from settings/Preferences
- Explicit timezone parsing (e.g., "9am EST")
- ISO 8601 formatting with timezone offset
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from assistant.services.timezone import (
    TIMEZONE_ABBREVIATIONS,
    TimezoneAwareDateTime,
    TimezoneService,
    get_timezone_service,
    localize,
    now,
    parse_time_with_timezone,
    reset_timezone_service,
    today,
)


class TestTimezoneAbbreviations:
    """Tests for timezone abbreviation mapping."""

    def test_us_timezones_present(self):
        """Common US timezones should be mapped."""
        assert "EST" in TIMEZONE_ABBREVIATIONS
        assert "EDT" in TIMEZONE_ABBREVIATIONS
        assert "CST" in TIMEZONE_ABBREVIATIONS
        assert "CDT" in TIMEZONE_ABBREVIATIONS
        assert "MST" in TIMEZONE_ABBREVIATIONS
        assert "MDT" in TIMEZONE_ABBREVIATIONS
        assert "PST" in TIMEZONE_ABBREVIATIONS
        assert "PDT" in TIMEZONE_ABBREVIATIONS

    def test_european_timezones_present(self):
        """Common European timezones should be mapped."""
        assert "GMT" in TIMEZONE_ABBREVIATIONS
        assert "BST" in TIMEZONE_ABBREVIATIONS
        assert "CET" in TIMEZONE_ABBREVIATIONS
        assert "CEST" in TIMEZONE_ABBREVIATIONS

    def test_utc_present(self):
        """UTC should be mapped."""
        assert "UTC" in TIMEZONE_ABBREVIATIONS
        assert TIMEZONE_ABBREVIATIONS["UTC"] == "UTC"

    def test_abbreviations_map_to_iana(self):
        """Abbreviations should map to valid IANA timezone names."""
        for abbrev, iana in TIMEZONE_ABBREVIATIONS.items():
            # This will raise if invalid
            tz = ZoneInfo(iana)
            assert tz is not None


class TestTimezoneAwareDateTime:
    """Tests for TimezoneAwareDateTime dataclass."""

    def setup_method(self):
        self.tz = ZoneInfo("America/Los_Angeles")
        self.dt = datetime(2024, 1, 15, 14, 0, 0, tzinfo=self.tz)
        self.aware_dt = TimezoneAwareDateTime(
            datetime_value=self.dt,
            timezone_name="America/Los_Angeles",
        )

    def test_creation(self):
        """Should create TimezoneAwareDateTime correctly."""
        assert self.aware_dt.datetime_value == self.dt
        assert self.aware_dt.timezone_name == "America/Los_Angeles"

    def test_is_utc_false(self):
        """is_utc should return False for non-UTC timezones."""
        assert self.aware_dt.is_utc is False

    def test_is_utc_true(self):
        """is_utc should return True for UTC timezone."""
        utc_dt = TimezoneAwareDateTime(
            datetime_value=datetime.now(ZoneInfo("UTC")),
            timezone_name="UTC",
        )
        assert utc_dt.is_utc is True

    def test_to_iso8601(self):
        """to_iso8601 should format with timezone offset."""
        iso_str = self.aware_dt.to_iso8601()
        assert iso_str.startswith("2024-01-15T14:00:00")
        # PST offset is -08:00
        assert "-08:00" in iso_str

    def test_to_iso8601_utc(self):
        """to_iso8601_utc should convert to UTC with Z suffix."""
        utc_str = self.aware_dt.to_iso8601_utc()
        assert utc_str.endswith("Z")
        # 2pm PST is 10pm UTC
        assert "T22:00:00Z" in utc_str

    def test_to_utc(self):
        """to_utc should convert to UTC datetime."""
        utc_dt = self.aware_dt.to_utc()
        assert utc_dt.hour == 22  # 2pm PST = 10pm UTC

    def test_to_timezone(self):
        """to_timezone should convert to different timezone."""
        nyc_dt = self.aware_dt.to_timezone("America/New_York")
        assert nyc_dt.timezone_name == "America/New_York"
        assert nyc_dt.datetime_value.hour == 17  # 2pm PST = 5pm EST


class TestTimezoneService:
    """Tests for TimezoneService class."""

    def setup_method(self):
        self.service = TimezoneService("America/Los_Angeles")

    def test_default_timezone(self):
        """Should use provided timezone as default."""
        assert self.service.default_timezone == "America/Los_Angeles"

    def test_invalid_timezone_fallback(self):
        """Invalid timezone should fallback to UTC."""
        service = TimezoneService("Invalid/Timezone")
        assert service.default_timezone == "UTC"

    def test_now(self):
        """now() should return current time in user timezone."""
        result = self.service.now()
        assert result.timezone_name == "America/Los_Angeles"
        assert result.datetime_value.tzinfo is not None

    def test_today(self):
        """today() should return midnight in user timezone."""
        result = self.service.today()
        assert result.timezone_name == "America/Los_Angeles"
        assert result.datetime_value.hour == 0
        assert result.datetime_value.minute == 0

    def test_parse_explicit_timezone_est(self):
        """Should parse EST timezone marker."""
        result = self.service.parse_explicit_timezone("Meeting at 9am EST")
        assert result is not None
        assert result.timezone_name == "America/New_York"
        assert result.original_text == "EST"
        assert result.confidence >= 90

    def test_parse_explicit_timezone_pst(self):
        """Should parse PST timezone marker."""
        result = self.service.parse_explicit_timezone("Call at 2pm PST")
        assert result is not None
        assert result.timezone_name == "America/Los_Angeles"

    def test_parse_explicit_timezone_utc(self):
        """Should parse UTC timezone marker."""
        result = self.service.parse_explicit_timezone("Deploy at 10am UTC")
        assert result is not None
        assert result.timezone_name == "UTC"

    def test_parse_explicit_timezone_none(self):
        """Should return None when no explicit timezone."""
        result = self.service.parse_explicit_timezone("Meeting at 3pm")
        assert result is None

    def test_create_datetime(self):
        """create_datetime should create timezone-aware datetime."""
        result = self.service.create_datetime(2024, 1, 15, 14, 30)
        assert result.datetime_value.year == 2024
        assert result.datetime_value.month == 1
        assert result.datetime_value.day == 15
        assert result.datetime_value.hour == 14
        assert result.datetime_value.minute == 30
        assert result.timezone_name == "America/Los_Angeles"

    def test_create_datetime_with_explicit_timezone(self):
        """create_datetime should respect explicit timezone."""
        result = self.service.create_datetime(2024, 1, 15, 14, 30, timezone="America/New_York")
        assert result.timezone_name == "America/New_York"

    def test_localize_naive(self):
        """localize should attach timezone to naive datetime."""
        naive_dt = datetime(2024, 1, 15, 14, 0, 0)
        result = self.service.localize(naive_dt)
        assert result.datetime_value.tzinfo is not None
        assert result.timezone_name == "America/Los_Angeles"

    def test_localize_aware(self):
        """localize should convert aware datetime to target timezone."""
        utc_dt = datetime(2024, 1, 15, 22, 0, 0, tzinfo=ZoneInfo("UTC"))
        result = self.service.localize(utc_dt)
        # 10pm UTC = 2pm PST
        assert result.datetime_value.hour == 14

    def test_parse_time_with_timezone_explicit(self):
        """parse_time_with_timezone should respect explicit timezone."""
        result = self.service.parse_time_with_timezone("Call at 9am EST")
        assert result is not None
        assert result.datetime_value.hour == 9
        assert result.timezone_name == "America/New_York"

    def test_parse_time_with_timezone_default(self):
        """parse_time_with_timezone should use default timezone."""
        result = self.service.parse_time_with_timezone("Call at 2pm")
        assert result is not None
        assert result.datetime_value.hour == 14
        assert result.timezone_name == "America/Los_Angeles"

    def test_format_for_display_simple(self):
        """format_for_display should format time nicely."""
        dt = datetime(2024, 1, 15, 14, 0, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        result = self.service.format_for_display(dt)
        assert result == "2pm"

    def test_format_for_display_with_minutes(self):
        """format_for_display should include minutes when present."""
        dt = datetime(2024, 1, 15, 14, 30, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        result = self.service.format_for_display(dt)
        assert result == "2:30pm"

    def test_format_for_display_morning(self):
        """format_for_display should handle morning times."""
        dt = datetime(2024, 1, 15, 9, 0, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        result = self.service.format_for_display(dt)
        assert result == "9am"


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def setup_method(self):
        reset_timezone_service()

    def teardown_method(self):
        reset_timezone_service()

    def test_get_timezone_service_singleton(self):
        """get_timezone_service should return singleton."""
        service1 = get_timezone_service("America/Los_Angeles")
        service2 = get_timezone_service()
        assert service1 is service2

    def test_reset_timezone_service(self):
        """reset_timezone_service should clear singleton."""
        # Initialize with one timezone
        get_timezone_service("America/Los_Angeles")
        reset_timezone_service()
        service2 = get_timezone_service("America/New_York")
        # After reset, new service should have new timezone
        assert service2.default_timezone == "America/New_York"

    def test_now_function(self):
        """now() function should return current time."""
        get_timezone_service("America/Los_Angeles")
        result = now()
        assert result.timezone_name == "America/Los_Angeles"

    def test_today_function(self):
        """today() function should return today's date."""
        get_timezone_service("America/Los_Angeles")
        result = today()
        assert result.datetime_value.hour == 0

    def test_localize_function(self):
        """localize() function should localize datetime."""
        get_timezone_service("America/Los_Angeles")
        naive_dt = datetime(2024, 1, 15, 14, 0, 0)
        result = localize(naive_dt)
        assert result.datetime_value.tzinfo is not None

    def test_parse_time_with_timezone_function(self):
        """parse_time_with_timezone() function should parse time."""
        get_timezone_service("America/Los_Angeles")
        result = parse_time_with_timezone("Call at 9am EST")
        assert result is not None
        assert result.timezone_name == "America/New_York"


class TestAT119Acceptance:
    """Acceptance tests for AT-119: Timezone Parsing."""

    def test_at119_full_acceptance(self):
        """AT-119: Full acceptance test.

        Given: User timezone is "America/Los_Angeles" (PST/PDT)
        When: User sends "tomorrow 2pm"
        Then: due_date stored as 2pm in PST/PDT
        And: due_timezone field set to "America/Los_Angeles"
        """
        from assistant.services.entities import EntityExtractor

        extractor = EntityExtractor(timezone="America/Los_Angeles")
        result = extractor.extract_dates("tomorrow 2pm")

        assert len(result) >= 1
        assert result[0].datetime_value.hour == 14
        assert result[0].timezone == "America/Los_Angeles"

        # Verify ISO 8601 includes timezone offset (PST is -08:00, PDT is -07:00)
        iso_str = result[0].to_iso8601()
        assert "T14:" in iso_str  # Hour is 14 (2pm)
        assert "-08:00" in iso_str or "-07:00" in iso_str  # PST/PDT offset

    def test_at119_explicit_timezone_override(self):
        """AT-119: Explicit timezone should override user default.

        PRD 5.4: "9am EST" - Explicit timezone respected
        """
        from assistant.services.entities import EntityExtractor

        extractor = EntityExtractor(timezone="America/Los_Angeles")
        result = extractor.extract_dates("Call at 9am EST")

        assert len(result) >= 1
        assert result[0].datetime_value.hour == 9
        assert result[0].timezone == "America/New_York"
        assert result[0].has_explicit_timezone is True

    def test_at119_relative_time(self):
        """AT-119: Relative times use current timezone.

        PRD 5.4: "in 2 hours" - Current time + 2 hours
        """
        from assistant.services.entities import EntityExtractor

        extractor = EntityExtractor(timezone="America/Los_Angeles")
        result = extractor.extract_dates("Remind me in 2 hours")

        assert len(result) >= 1
        expected = datetime.now(ZoneInfo("America/Los_Angeles")) + timedelta(hours=2)
        actual = result[0].datetime_value

        # Should be within 2 minutes of expected
        assert abs((actual - expected).total_seconds()) < 120
        assert result[0].timezone == "America/Los_Angeles"


class TestPRDSection54Examples:
    """Tests for all examples in PRD Section 5.4."""

    def setup_method(self):
        from assistant.services.entities import EntityExtractor

        self.extractor = EntityExtractor(timezone="America/Los_Angeles")
        self.tz = ZoneInfo("America/Los_Angeles")

    def test_tomorrow_2pm(self):
        """PRD: 'tomorrow 2pm' -> 2pm in user's configured timezone."""
        result = self.extractor.extract_dates("tomorrow 2pm")
        assert len(result) >= 1
        assert result[0].datetime_value.hour == 14
        assert result[0].timezone == "America/Los_Angeles"

    def test_friday_8pm(self):
        """PRD: 'Friday 8pm' -> 8pm in user's timezone on next Friday."""
        result = self.extractor.extract_dates("Friday 8pm")
        assert len(result) >= 1
        assert result[0].datetime_value.weekday() == 4  # Friday
        assert result[0].datetime_value.hour == 20
        assert result[0].timezone == "America/Los_Angeles"

    def test_in_2_hours(self):
        """PRD: 'in 2 hours' -> Current time + 2 hours."""
        result = self.extractor.extract_dates("in 2 hours")
        assert len(result) >= 1

        expected = datetime.now(self.tz) + timedelta(hours=2)
        actual = result[0].datetime_value
        assert abs((actual - expected).total_seconds()) < 120

    def test_9am_est(self):
        """PRD: '9am EST' -> Explicit timezone respected."""
        result = self.extractor.extract_dates("9am EST")
        assert len(result) >= 1
        assert result[0].datetime_value.hour == 9
        assert result[0].timezone == "America/New_York"
        assert result[0].has_explicit_timezone is True
