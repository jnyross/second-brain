from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo


class _PytzTimezone(tzinfo):
    def __init__(self, name: str) -> None:
        self._zone = ZoneInfo(name)
        self.zone = name

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return self._zone.utcoffset(dt)

    def dst(self, dt: datetime | None) -> timedelta | None:
        return self._zone.dst(dt)

    def tzname(self, dt: datetime | None) -> str | None:
        return self._zone.tzname(dt)

    def fromutc(self, dt: datetime) -> datetime:
        converted = self._zone.fromutc(dt.replace(tzinfo=self._zone))
        return converted.replace(tzinfo=self)

    def localize(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=self)
        return dt.astimezone(self)

    def normalize(self, dt: datetime) -> datetime:
        return dt.astimezone(self)

    def __str__(self) -> str:
        return self.zone

    def __repr__(self) -> str:
        return f"<_PytzTimezone {self.zone}>"


def timezone(name: str) -> _PytzTimezone:
    return _PytzTimezone(name)


UTC = timezone("UTC")
