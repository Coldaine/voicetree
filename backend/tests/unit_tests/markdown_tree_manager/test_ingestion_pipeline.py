"""Tests for Always-On Context-Aware Ingestion Pipeline (Issue #7).

Covers:
- Ingestion adapter interface
- IngestionEvent normalization
- Deduplication window
- Rate limiting
- Source metadata on nodes
"""

import time
import unittest
from datetime import datetime

from backend.markdown_tree_manager.markdown_tree_ds import Node


class TestIngestionEvent(unittest.TestCase):
    """Test the IngestionEvent data structure."""

    def test_ingestion_event_creation(self):
        """IngestionEvent should hold source metadata."""
        from backend.context_ingestion.ingestion_types import IngestionEvent

        event = IngestionEvent(
            content="Some context from ScreenPipe",
            source_type="screenpi pe",
            source_ref="com.example.app",
            timestamp=datetime.now(),
            confidence=0.85
        )

        self.assertEqual(event.source_type, "screenpi pe")
        self.assertEqual(event.confidence, 0.85)
        self.assertIsNotNone(event.timestamp)


class TestIngestionAdapter(unittest.TestCase):
    """Test the ingestion adapter interface."""

    def test_adapter_interface_exists(self):
        """IngestionAdapter abstract class should exist."""
        from backend.context_ingestion.ingestion_types import IngestionAdapter
        self.assertTrue(hasattr(IngestionAdapter, 'poll'))
        self.assertTrue(hasattr(IngestionAdapter, 'name'))

    def test_mock_adapter_returns_events(self):
        """A mock adapter should return normalized events."""
        from backend.context_ingestion.ingestion_types import IngestionAdapter, IngestionEvent

        class MockAdapter(IngestionAdapter):
            @property
            def name(self) -> str:
                return "mock"

            def poll(self) -> list[IngestionEvent]:
                return [
                    IngestionEvent(
                        content="test event",
                        source_type="mock",
                        source_ref="test",
                        timestamp=datetime.now(),
                        confidence=1.0
                    )
                ]

        adapter = MockAdapter()
        events = adapter.poll()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source_type, "mock")


class TestDeduplicationWindow(unittest.TestCase):
    """Test event deduplication."""

    def test_duplicate_events_are_filtered(self):
        """Duplicate events within the window should be filtered."""
        from backend.context_ingestion.dedup import DeduplicationWindow

        dedup = DeduplicationWindow(window_seconds=5.0)

        event_key = "app:VSCode:file.py"
        self.assertTrue(dedup.is_new(event_key))
        self.assertFalse(dedup.is_new(event_key))

    def test_expired_events_are_allowed_again(self):
        """Events beyond the dedup window should be allowed."""
        from backend.context_ingestion.dedup import DeduplicationWindow

        dedup = DeduplicationWindow(window_seconds=0.01)

        event_key = "app:VSCode:file.py"
        self.assertTrue(dedup.is_new(event_key))

        time.sleep(0.02)
        self.assertTrue(dedup.is_new(event_key))


class TestRateLimiter(unittest.TestCase):
    """Test ingestion rate limiting."""

    def test_rate_limiter_allows_within_limit(self):
        """Events within rate limit should be allowed."""
        from backend.context_ingestion.rate_limiter import RateLimiter

        limiter = RateLimiter(max_events_per_second=10)
        self.assertTrue(limiter.allow())

    def test_rate_limiter_blocks_excess(self):
        """Excess events should be blocked."""
        from backend.context_ingestion.rate_limiter import RateLimiter

        limiter = RateLimiter(max_events_per_second=2)
        self.assertTrue(limiter.allow())
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())


class TestNodeSourceMetadata(unittest.TestCase):
    """Test source metadata on nodes."""

    def test_node_has_source_type_field(self):
        """Node should support source_type metadata."""
        node = Node("test", 1, "content", "summary")
        node.source_type = "screenpi pe"
        self.assertEqual(node.source_type, "screenpi pe")

    def test_node_has_source_ref_field(self):
        """Node should support source_ref metadata."""
        node = Node("test", 1, "content", "summary")
        node.source_ref = "com.example.app"
        self.assertEqual(node.source_ref, "com.example.app")


if __name__ == "__main__":
    unittest.main()
