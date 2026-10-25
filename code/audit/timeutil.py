"""Strict ISO-8601 UTC timestamp handling (plan A.1.4)."""
import re
from datetime import datetime, timezone

TS_PATTERN = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
_TS_RE = re.compile(r"^" + TS_PATTERN + r"$")


def is_strict_ts(value):
    return isinstance(value, str) and bool(_TS_RE.match(value))


def parse_ts(value):
    """Parse 'YYYY-MM-DDTHH:MM:SSZ' into an aware UTC datetime; raise ValueError otherwise."""
    if not is_strict_ts(value):
        raise ValueError(f"not a strict ISO-8601 UTC timestamp: {value!r}")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def try_parse_ts(value):
    """Like parse_ts but returns None for anything that is not a strict timestamp."""
    try:
        return parse_ts(value)
    except (ValueError, TypeError):
        return None
