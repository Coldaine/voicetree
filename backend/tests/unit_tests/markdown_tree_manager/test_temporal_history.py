"""Tests for Temporal Graph and Project History (Issue #11).

Covers:
- Node version history tracking
- Temporal queries (get_graph_at_timestamp, get_changes_since)
- Version snapshots on content updates
"""

import time
import unittest
from datetime import datetime, timedelta

from backend.markdown_tree_manager.markdown_tree_ds import MarkdownTree, Node


class TestNodeVersionHistory(unittest.TestCase):
    """Test version history tracking on nodes."""

    def test_node_has_version_history(self):
        """Node should have a version_history list."""
        node = Node("test", 1, "content", "summary")
        self.assertIsInstance(node.version_history, list)
        self.assertEqual(len(node.version_history), 0)

    def test_update_node_creates_version(self):
        """Updating a node should create a version history entry."""
        tree = MarkdownTree()
        node_id = tree.create_new_node("test", None, "original content", "original summary")

        time.sleep(0.01)  # Ensure timestamp difference
        tree.update_node(node_id, "updated content", "updated summary")

        node = tree.tree[node_id]
        self.assertGreaterEqual(len(node.version_history), 1)

        # Latest version should have the old content
        latest_version = node.version_history[-1]
        self.assertEqual(latest_version["content"], "original content")
        self.assertEqual(latest_version["summary"], "original summary")
        self.assertIn("timestamp", latest_version)

    def test_multiple_updates_create_multiple_versions(self):
        """Multiple updates should track all versions."""
        tree = MarkdownTree()
        node_id = tree.create_new_node("test", None, "v1 content", "v1 summary")

        tree.update_node(node_id, "v2 content", "v2 summary")
        tree.update_node(node_id, "v3 content", "v3 summary")

        node = tree.tree[node_id]
        self.assertEqual(len(node.version_history), 2)
        self.assertEqual(node.version_history[0]["content"], "v1 content")
        self.assertEqual(node.version_history[1]["content"], "v2 content")

    def test_version_history_has_timestamps(self):
        """Each version entry should have a timestamp."""
        tree = MarkdownTree()
        node_id = tree.create_new_node("test", None, "original", "summary")

        tree.update_node(node_id, "updated", "new summary")

        version = tree.tree[node_id].version_history[0]
        self.assertIn("timestamp", version)
        self.assertIsInstance(version["timestamp"], str)


class TestTemporalQueries(unittest.TestCase):
    """Test temporal query capabilities."""

    def test_get_changes_since(self):
        """Should return nodes modified since a given timestamp."""
        tree = MarkdownTree()
        n1 = tree.create_new_node("old node", None, "content", "summary")

        # Record timestamp
        time.sleep(0.01)
        cutoff = datetime.now()
        time.sleep(0.01)

        n2 = tree.create_new_node("new node", n1, "content", "summary")

        changed = tree.get_changes_since(cutoff)
        self.assertIn(n2, changed)

    def test_get_changes_since_includes_modified(self):
        """Should include nodes that were modified after the cutoff."""
        tree = MarkdownTree()
        n1 = tree.create_new_node("node", None, "original", "summary")

        time.sleep(0.01)
        cutoff = datetime.now()
        time.sleep(0.01)

        tree.update_node(n1, "modified content", "new summary")

        changed = tree.get_changes_since(cutoff)
        self.assertIn(n1, changed)

    def test_get_changes_since_excludes_old(self):
        """Should not include nodes that haven't changed since cutoff."""
        tree = MarkdownTree()
        n1 = tree.create_new_node("old node", None, "content", "summary")

        time.sleep(0.01)
        cutoff = datetime.now()
        time.sleep(0.01)

        # Create new node but don't modify n1
        tree.create_new_node("new node", n1, "content", "summary")

        changed = tree.get_changes_since(cutoff)
        self.assertNotIn(n1, changed)


class TestNodeVersionSerialization(unittest.TestCase):
    """Test serialization of version history."""

    def test_to_dict_includes_version_count(self):
        """to_dict should include version_count for each node."""
        tree = MarkdownTree()
        node_id = tree.create_new_node("test", None, "v1", "summary")
        tree.update_node(node_id, "v2", "summary")

        result = tree.to_dict()
        node_data = result["tree"][str(node_id)]
        self.assertIn("version_count", node_data)
        self.assertEqual(node_data["version_count"], 1)


if __name__ == "__main__":
    unittest.main()
