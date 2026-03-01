"""Rate limiter for ingestion events (Issue #7).

Prevents ingestion from overwhelming the system with too many events per second.
"""

import time


class RateLimiter:
    """Token-bucket style rate limiter for ingestion events."""

    def __init__(self, max_events_per_second: int = 10) -> None:
        self._max_events = max_events_per_second
        self._timestamps: list[float] = []

    def allow(self) -> bool:
        """Check if a new event is allowed under the rate limit.

        Returns:
            True if the event is allowed, False if rate limit exceeded.
        """
        now = time.monotonic()

        # Remove timestamps older than 1 second
        self._timestamps = [t for t in self._timestamps if now - t < 1.0]

        if len(self._timestamps) >= self._max_events:
            return False

        self._timestamps.append(now)
        return True
