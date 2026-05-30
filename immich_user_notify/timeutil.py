"""Datetime helpers. Everything internal is tz-aware UTC."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_immich_dt(value: str) -> datetime:
    """Parse an Immich ISO-8601 timestamp (often with a trailing 'Z') to UTC."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso_utc(dt: datetime) -> str:
    """Serialize a datetime to ISO-8601 UTC text for storage."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
