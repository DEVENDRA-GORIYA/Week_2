from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC timestamp. SQLite does not preserve timezone info."""
    return datetime.now(UTC).replace(tzinfo=None)
