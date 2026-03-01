"""Tests for Performance with Large Graphs (Issue #9).

Covers:
- Tree operations at scale (100+ nodes)
- get_nodes_by_branching_factor performance
- Serialization performance
- Fuzzy name matching at scale
"""

import time
import unittest

from backend.markdown_tree_manager.markdown_tree_ds import MarkdownTree


class TestLargeGraphPerformance(unittest.TestCase):
    """Test tree operations at scale."""

    def _create_large_tree(self, n: int = 100) -> MarkdownTree:
        """Helper to create a tree with n nodes."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "root content", "root summary")
        for i in range(1, n):
            parent = root if i < 10 else root + (i % 9)
            # Ensure parent exists in tree
            if parent not in tree.tree:
                parent = root
            tree.create_new_node(f"node_{i}", parent, f"content {i}", f"summary {i}")
        return tree

    def test_create_100_nodes(self):
        """Creating 100 nodes should complete in reasonable time."""
        start = time.time()
        tree = self._create_large_tree(100)
        elapsed = time.time() - start

        self.assertEqual(len(tree.tree), 100)
        self.assertLess(elapsed, 5.0, "Creating 100 nodes should be under 5 seconds")

    def test_get_recent_nodes_at_scale(self):
        """get_recent_nodes should be fast with many nodes."""
        tree = self._create_large_tree(100)

        start = time.time()
        recent = tree.get_recent_nodes(10)
        elapsed = time.time() - start

        self.assertEqual(len(recent), 10)
        self.assertLess(elapsed, 1.0, "get_recent_nodes should be under 1 second")

    def test_get_nodes_by_branching_factor_at_scale(self):
        """get_nodes_by_branching_factor should work with many nodes."""
        tree = self._create_large_tree(100)

        start = time.time()
        sorted_nodes = tree.get_nodes_by_branching_factor(limit=10)
        elapsed = time.time() - start

        self.assertEqual(len(sorted_nodes), 10)
        self.assertLess(elapsed, 1.0)

    def test_to_dict_at_scale(self):
        """to_dict should handle large trees efficiently."""
        tree = self._create_large_tree(100)

        start = time.time()
        result = tree.to_dict()
        elapsed = time.time() - start

        self.assertEqual(len(result["tree"]), 100)
        self.assertLess(elapsed, 2.0, "Serialization of 100 nodes should be under 2 seconds")

    def test_fuzzy_search_at_scale(self):
        """Fuzzy name matching should work at scale."""
        tree = self._create_large_tree(100)

        start = time.time()
        result = tree.get_node_id_from_name("node_50")
        elapsed = time.time() - start

        self.assertIsNotNone(result)
        self.assertLess(elapsed, 1.0)

    def test_get_neighbors_at_scale(self):
        """get_neighbors should handle nodes with many children."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "content", "summary")

        # Create 50 children of root
        for i in range(50):
            tree.create_new_node(f"child_{i}", root, f"content {i}", f"summary {i}")

        start = time.time()
        neighbors = tree.get_neighbors(root, max_neighbours=30)
        elapsed = time.time() - start

        self.assertLessEqual(len(neighbors), 30)
        self.assertLess(elapsed, 1.0)


class TestRemoveNodeAtScale(unittest.TestCase):
    """Test node removal at scale."""

    def test_remove_node_updates_parent(self):
        """Removing a node should update parent's children list."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "content", "summary")
        child = tree.create_new_node("child", root, "content", "summary")

        initial_children = len(tree.tree[root].children)
        tree.remove_node(child)

        self.assertEqual(len(tree.tree[root].children), initial_children - 1)

    def test_remove_node_orphans_children(self):
        """Removing a parent should set children's parent_id to None."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "content", "summary")
        mid = tree.create_new_node("mid", root, "content", "summary")
        child = tree.create_new_node("child", mid, "content", "summary")

        tree.remove_node(mid)
        self.assertIsNone(tree.tree[child].parent_id)


if __name__ == "__main__":
    unittest.main()
