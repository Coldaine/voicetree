"""Deduplication window for ingestion events (Issue #7).

Prevents duplicate context events within a configurable time window.
"""

import time


class DeduplicationWindow:
    """Time-based deduplication for ingestion events."""

    def __init__(self, window_seconds: float = 5.0) -> None:
        self._window_seconds = window_seconds
        self._seen: dict[str, float] = {}

    def is_new(self, event_key: str) -> bool:
        """Check if an event key is new (not seen within the dedup window).

        Args:
            event_key: Unique key identifying the event (e.g., 'app:name:context')

        Returns:
            True if the event is new, False if it's a duplicate within the window.
        """
        now = time.monotonic()

        # Clean expired entries
        expired = [k for k, t in self._seen.items() if now - t > self._window_seconds]
        for k in expired:
            del self._seen[k]

        if event_key in self._seen:
            return False

        self._seen[event_key] = now
        return True
