"""Single Asia/Shanghai time contract for market-data PIT decisions."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI)


def as_shanghai(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("market timestamp must be datetime")
    return value.replace(tzinfo=SHANGHAI) if value.tzinfo is None else value.astimezone(SHANGHAI)


def parse_shanghai(value: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise ValueError("market timestamp is required")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError("market timestamp is invalid") from error
    return as_shanghai(parsed)


__all__ = ["SHANGHAI", "as_shanghai", "parse_shanghai", "shanghai_now"]
