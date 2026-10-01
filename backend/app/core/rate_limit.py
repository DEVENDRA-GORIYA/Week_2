import time
from collections import defaultdict, deque
from threading import Lock

from app.core.errors import RateLimited


class SlidingWindowLimiter:
    """In-process per-user request limit. One API replica only.

    A multi-worker deployment needs a shared store (Redis or similar).
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: int) -> int:
        """Record one hit and return the remaining budget in the window."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise RateLimited(f"Rate limit of {self.limit} requests per minute exceeded.")
            hits.append(now)
            return self.limit - len(hits)
