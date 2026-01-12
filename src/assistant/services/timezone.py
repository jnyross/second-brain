"""Timezone handling service for Second Brain.

Implements PRD Section 5.4:
- User-configured timezone from settings/Preferences
- Explicit timezone parsing (e.g., "9am EST")
- ISO 8601 formatting with timezone offset
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from assistant.config import settings

# Common timezone abbreviations mapped to IANA timezone names
# These are the most common ones; can be extended as needed
TIMEZONE_ABBREVIATIONS: dict[str, str] = {
    # US Timezones
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "AKST": "America/Anchorage",
    "AKDT": "America/Anchorage",
    "HST": "Pacific/Honolulu",
    # European Timezones
    "GMT": "Europe/London",
    "BST": "Europe/London",
    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",
    "EET": "Europe/Helsinki",
    "EEST": "Europe/Helsinki",
    # Other common ones
    "UTC": "UTC",
    "IST": "Asia/Kolkata",  # India Standard Time
    "JST": "Asia/Tokyo",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
}


@dataclass
class ParsedTimezone:
    """Result of timezone parsing from text."""

    timezone_name: str  # IANA timezone name (e.g., "America/Los_Angeles")
    original_text: str  # The matched text (e.g., "EST", "Pacific")
    confidence: int  # 0-100


@dataclass
class TimezoneAwareDateTime:
    """A datetime with explicit timezone information.

    Provides convenient formatting and conversion methods.
    """

    datetime_value: datetime
    timezone_name: str

    @property
    def is_utc(self) -> bool:
        """Check if this datetime is in UTC."""
        return self.timezone_name == "UTC"

    def to_iso8601(self) -> str:
        """Format as ISO 8601 string with timezone offset.

        Example: 2024-01-15T14:00:00-08:00
        """
        return self.datetime_value.isoformat()

    def to_iso8601_utc(self) -> str:
        """Format as ISO 8601 string in UTC.

        Example: 2024-01-15T22:00:00Z
        """
        utc_dt = self.to_utc()
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_utc(self) -> datetime:
        """Convert to UTC datetime."""
        return self.datetime_value.astimezone(UTC)

    def to_timezone(self, tz_name: str) -> "TimezoneAwareDateTime":
        """Convert to a different timezone."""
        tz = ZoneInfo(tz_name)
        new_dt = self.datetime_value.astimezone(tz)
        return TimezoneAwareDateTime(datetime_value=new_dt, timezone_name=tz_name)


class TimezoneService:
    """Service for timezone handling per PRD Section 5.4.

    Features:
    - User-configured default timezone from settings
    - Explicit timezone parsing from text (e.g., "9am EST")
    - DateTime normalization and formatting
    """

    # Pattern to match explicit timezone markers
    # Matches: "9am EST", "2pm PST", "14:00 UTC"
    EXPLICIT_TZ_PATTERN = re.compile(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+("
        + "|".join(re.escape(tz) for tz in TIMEZONE_ABBREVIATIONS.keys())
        + r")\b",
        re.IGNORECASE,
    )

    def __init__(self, default_timezone: str | None = None):
        """Initialize timezone service.

        Args:
            default_timezone: IANA timezone name. Defaults to settings.user_timezone.
        """
        self._default_tz_name = default_timezone or settings.user_timezone
        try:
            self._default_tz = ZoneInfo(self._default_tz_name)
        except KeyError:
            # Fallback to UTC if invalid timezone
            self._default_tz_name = "UTC"
            self._default_tz = ZoneInfo("UTC")

    @property
    def default_timezone(self) -> str:
        """Get the default timezone name."""
        return self._default_tz_name

    def now(self) -> TimezoneAwareDateTime:
        """Get current time in user's timezone."""
        dt = datetime.now(self._default_tz)
        return TimezoneAwareDateTime(datetime_value=dt, timezone_name=self._default_tz_name)

    def today(self) -> TimezoneAwareDateTime:
        """Get today's date at midnight in user's timezone."""
        now = datetime.now(self._default_tz)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return TimezoneAwareDateTime(datetime_value=midnight, timezone_name=self._default_tz_name)

    def parse_explicit_timezone(self, text: str) -> ParsedTimezone | None:
        """Extract explicit timezone marker from text.

        Args:
            text: Text to search for timezone markers

        Returns:
            ParsedTimezone if found, None otherwise

        Examples:
            "9am EST" -> ParsedTimezone(timezone_name="America/New_York", ...)
            "2pm PST" -> ParsedTimezone(timezone_name="America/Los_Angeles", ...)
        """
        match = self.EXPLICIT_TZ_PATTERN.search(text)
        if match:
            tz_abbrev = match.group(4).upper()
            if tz_abbrev in TIMEZONE_ABBREVIATIONS:
                return ParsedTimezone(
                    timezone_name=TIMEZONE_ABBREVIATIONS[tz_abbrev],
                    original_text=tz_abbrev,
                    confidence=95,
                )
        return None

    def create_datetime(
        self,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        timezone: str | None = None,
    ) -> TimezoneAwareDateTime:
        """Create a timezone-aware datetime.

        Args:
            year, month, day: Date components
            hour, minute, second: Time components (default 0)
            timezone: IANA timezone name. Defaults to user timezone.

        Returns:
            TimezoneAwareDateTime with proper timezone
        """
        tz_name = timezone or self._default_tz_name
        tz = ZoneInfo(tz_name)
        dt = datetime(year, month, day, hour, minute, second, tzinfo=tz)
        return TimezoneAwareDateTime(datetime_value=dt, timezone_name=tz_name)

    def localize(
        self,
        dt: datetime,
        timezone: str | None = None,
    ) -> TimezoneAwareDateTime:
        """Attach timezone info to a naive datetime or convert aware datetime.

        Args:
            dt: Datetime to localize (naive or aware)
            timezone: Target timezone. Defaults to user timezone.

        Returns:
            TimezoneAwareDateTime in specified timezone
        """
        tz_name = timezone or self._default_tz_name
        tz = ZoneInfo(tz_name)

        if dt.tzinfo is None:
            # Naive datetime: assume it represents time in target timezone
            aware_dt = dt.replace(tzinfo=tz)
        else:
            # Already aware: convert to target timezone
            aware_dt = dt.astimezone(tz)

        return TimezoneAwareDateTime(datetime_value=aware_dt, timezone_name=tz_name)

    def parse_time_with_timezone(
        self,
        text: str,
        base_date: datetime | None = None,
    ) -> TimezoneAwareDateTime | None:
        """Parse time from text, respecting explicit timezone markers.

        If text contains an explicit timezone (e.g., "9am EST"), uses that.
        Otherwise, uses the user's default timezone.

        Args:
            text: Text containing time (e.g., "9am EST", "2pm tomorrow")
            base_date: Base date for relative times. Defaults to today.

        Returns:
            TimezoneAwareDateTime if time found, None otherwise
        """
        # Check for explicit timezone first
        explicit_tz = self.parse_explicit_timezone(text)

        # Parse the time
        match = self.EXPLICIT_TZ_PATTERN.search(text)
        if not match:
            # Try simpler time patterns without timezone
            simple_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text, re.IGNORECASE)
            if not simple_match:
                return None
            hour = int(simple_match.group(1))
            minute = int(simple_match.group(2)) if simple_match.group(2) else 0
            ampm = simple_match.group(3).lower() if simple_match.group(3) else None
        else:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            ampm = match.group(3).lower() if match.group(3) else None

        # Convert to 24-hour format
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0

        # Determine timezone
        if explicit_tz:
            tz_name = explicit_tz.timezone_name
        else:
            tz_name = self._default_tz_name

        # Use base date or today
        if base_date is None:
            base_date = datetime.now(ZoneInfo(tz_name))

        # Create the datetime
        tz = ZoneInfo(tz_name)
        if base_date.tzinfo is None:
            base_date = base_date.replace(tzinfo=tz)

        result_dt = base_date.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

        # If time is in the past today, assume tomorrow
        now = datetime.now(tz)
        if result_dt < now and result_dt.date() == now.date():
            result_dt = result_dt + timedelta(days=1)

        return TimezoneAwareDateTime(
            datetime_value=result_dt.astimezone(tz),
            timezone_name=tz_name,
        )

    def format_for_display(
        self,
        dt: datetime | TimezoneAwareDateTime,
        include_timezone: bool = False,
    ) -> str:
        """Format datetime for user display.

        Args:
            dt: Datetime to format
            include_timezone: Whether to append timezone abbreviation

        Returns:
            Formatted string like "2pm" or "2pm PST"
        """
        if isinstance(dt, TimezoneAwareDateTime):
            dt_value = dt.datetime_value
        else:
            dt_value = dt

        hour = dt_value.hour
        minute = dt_value.minute

        if hour == 0:
            time_str = "12"
            ampm = "am"
        elif hour < 12:
            time_str = str(hour)
            ampm = "am"
        elif hour == 12:
            time_str = "12"
            ampm = "pm"
        else:
            time_str = str(hour - 12)
            ampm = "pm"

        if minute > 0:
            time_str = f"{time_str}:{minute:02d}"

        result = f"{time_str}{ampm}"

        if include_timezone:
            # Get timezone abbreviation
            tz: tzinfo
            if isinstance(dt, TimezoneAwareDateTime):
                tz = ZoneInfo(dt.timezone_name)
            elif dt_value.tzinfo:
                tz = dt_value.tzinfo
            else:
                tz = self._default_tz

            # Get the abbreviation (e.g., PST, PDT)
            if hasattr(tz, "key"):
                tz_abbrev = dt_value.strftime("%Z")
            else:
                tz_abbrev = str(tz)
            result = f"{result} {tz_abbrev}"

        return result


# Module-level singleton
_timezone_service: TimezoneService | None = None


def get_timezone_service(default_timezone: str | None = None) -> TimezoneService:
    """Get the singleton TimezoneService instance.

    Args:
        default_timezone: Optional timezone to use. Only used on first call.

    Returns:
        TimezoneService instance
    """
    global _timezone_service
    if _timezone_service is None:
        _timezone_service = TimezoneService(default_timezone)
    return _timezone_service


def reset_timezone_service() -> None:
    """Reset the singleton (useful for testing)."""
    global _timezone_service
    _timezone_service = None


def now() -> TimezoneAwareDateTime:
    """Get current time in user's timezone."""
    return get_timezone_service().now()


def today() -> TimezoneAwareDateTime:
    """Get today's date in user's timezone."""
    return get_timezone_service().today()


def localize(dt: datetime, timezone: str | None = None) -> TimezoneAwareDateTime:
    """Localize a datetime to specified timezone."""
    return get_timezone_service().localize(dt, timezone)


def parse_time_with_timezone(
    text: str,
    base_date: datetime | None = None,
) -> TimezoneAwareDateTime | None:
    """Parse time from text with timezone awareness."""
    return get_timezone_service().parse_time_with_timezone(text, base_date)
