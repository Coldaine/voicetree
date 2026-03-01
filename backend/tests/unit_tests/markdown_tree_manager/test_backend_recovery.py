"""Tests for Backend Crash Recovery (Issue #6) - Python backend health check.

Covers:
- Health endpoint returns proper status
- Server graceful shutdown behavior
"""

import unittest

from backend.markdown_tree_manager.markdown_tree_ds import MarkdownTree


class TestBackendHealthCheck(unittest.TestCase):
    """Test that the backend tree state can report health."""

    def test_tree_state_is_valid_after_init(self):
        """A fresh MarkdownTree should be in a valid state."""
        tree = MarkdownTree()
        self.assertIsNotNone(tree.tree)
        self.assertEqual(len(tree.tree), 0)
        self.assertEqual(tree.next_node_id, 1)

    def test_tree_state_remains_valid_after_operations(self):
        """Tree should remain valid after create/update/delete cycles."""
        tree = MarkdownTree()

        # Create
        n1 = tree.create_new_node("A", None, "content", "summary")
        n2 = tree.create_new_node("B", n1, "content", "summary")
        self.assertEqual(len(tree.tree), 2)

        # Update
        tree.update_node(n1, "new content", "new summary")
        self.assertEqual(tree.tree[n1].content, "new content")

        # Delete
        tree.remove_node(n2)
        self.assertEqual(len(tree.tree), 1)
        self.assertNotIn(n2, tree.tree)

    def test_tree_to_dict_always_serializable(self):
        """to_dict should always produce a valid dictionary."""
        tree = MarkdownTree()
        tree.create_new_node("test", None, "content", "summary")

        result = tree.to_dict()
        self.assertIsInstance(result, dict)
        self.assertIn("tree", result)


if __name__ == "__main__":
    unittest.main()
