"""Comprehensive tests for core tree operations.

Covers:
- Tree operations: add, remove, move, rename
- Tree serialization (to_dict, markdown conversion)
- Undo/redo operations
- Node content management
"""

import unittest

from backend.markdown_tree_manager.markdown_tree_ds import MarkdownTree, Node


class TestTreeAdd(unittest.TestCase):
    """Test adding nodes to the tree."""

    def test_add_root_node(self):
        """Can create a root node with no parent."""
        tree = MarkdownTree()
        nid = tree.create_new_node("root", None, "content", "summary")
        self.assertIn(nid, tree.tree)
        self.assertIsNone(tree.tree[nid].parent_id)

    def test_add_child_node(self):
        """Child node is linked to parent."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "content", "summary")
        child = tree.create_new_node("child", root, "child content", "child summary")

        self.assertEqual(tree.tree[child].parent_id, root)
        self.assertIn(child, tree.tree[root].children)

    def test_add_with_nonexistent_parent_falls_back_to_root(self):
        """Creating with nonexistent parent should set parent to None."""
        tree = MarkdownTree()
        nid = tree.create_new_node("orphan", 999, "content", "summary")
        self.assertIsNone(tree.tree[nid].parent_id)

    def test_node_ids_increment(self):
        """Node IDs should increment sequentially."""
        tree = MarkdownTree()
        n1 = tree.create_new_node("a", None, "c", "s")
        n2 = tree.create_new_node("b", n1, "c", "s")
        n3 = tree.create_new_node("c", n1, "c", "s")
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 2)
        self.assertEqual(n3, 3)

    def test_add_with_custom_relationship(self):
        """Node can be created with a custom relationship type."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "c", "s")
        child = tree.create_new_node("child", root, "c", "s",
                                      relationship_to_parent="implements")
        self.assertEqual(tree.tree[child].relationships[root], "implements")

    def test_add_skip_title(self):
        """Node with skip_title=True should have that flag set."""
        tree = MarkdownTree()
        nid = tree.create_new_node("test", None, "c", "s", skip_title=True)
        self.assertTrue(tree.tree[nid].skip_title)

    def test_add_generates_filename(self):
        """New node should have a filename generated."""
        tree = MarkdownTree()
        nid = tree.create_new_node("My Test Node", None, "content", "summary")
        self.assertIsNotNone(tree.tree[nid].filename)
        self.assertTrue(tree.tree[nid].filename.endswith(".md"))


class TestTreeRemove(unittest.TestCase):
    """Test removing nodes from the tree."""

    def test_remove_leaf_node(self):
        """Removing a leaf node should succeed."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "c", "s")
        leaf = tree.create_new_node("leaf", root, "c", "s")
        result = tree.remove_node(leaf)
        self.assertTrue(result)
        self.assertNotIn(leaf, tree.tree)

    def test_remove_nonexistent_node(self):
        """Removing a nonexistent node returns False."""
        tree = MarkdownTree()
        result = tree.remove_node(999)
        self.assertFalse(result)

    def test_remove_updates_parent_children(self):
        """Parent's children list should be updated on removal."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "c", "s")
        child = tree.create_new_node("child", root, "c", "s")
        tree.remove_node(child)
        self.assertNotIn(child, tree.tree[root].children)

    def test_remove_parent_orphans_children(self):
        """Children of removed node should have parent_id set to None."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "c", "s")
        mid = tree.create_new_node("mid", root, "c", "s")
        child = tree.create_new_node("child", mid, "c", "s")

        tree.remove_node(mid)
        self.assertIsNone(tree.tree[child].parent_id)


class TestTreeMove(unittest.TestCase):
    """Test moving nodes via set_parent_child_connection."""

    def test_move_node_to_new_parent(self):
        """Can move a node to a different parent."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "c", "s")
        a = tree.create_new_node("A", root, "c", "s")
        b = tree.create_new_node("B", root, "c", "s")
        child = tree.create_new_node("child", a, "c", "s")

        # Move child from A to B
        tree.set_parent_child_connection(b, child, "child_of")

        self.assertEqual(tree.tree[child].parent_id, b)
        self.assertIn(child, tree.tree[b].children)

    def test_move_nonexistent_node_raises(self):
        """Moving nonexistent node should raise KeyError."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "c", "s")
        with self.assertRaises(KeyError):
            tree.set_parent_child_connection(root, 999)

    def test_move_to_nonexistent_parent_raises(self):
        """Moving to nonexistent parent should raise KeyError."""
        tree = MarkdownTree()
        child = tree.create_new_node("child", None, "c", "s")
        with self.assertRaises(KeyError):
            tree.set_parent_child_connection(999, child)


class TestTreeRename(unittest.TestCase):
    """Test renaming nodes."""

    def test_rename_node(self):
        """Can change a node's title."""
        tree = MarkdownTree()
        nid = tree.create_new_node("Original", None, "c", "s")
        tree.tree[nid].title = "Renamed"
        self.assertEqual(tree.tree[nid].title, "Renamed")

    def test_find_renamed_node_by_name(self):
        """Should find renamed node by its new name."""
        tree = MarkdownTree()
        nid = tree.create_new_node("Original", None, "c", "s")
        tree.tree[nid].title = "Renamed"
        found = tree.get_node_id_from_name("Renamed")
        self.assertEqual(found, nid)


class TestTreeSerialization(unittest.TestCase):
    """Test tree serialization to dictionary format."""

    def test_to_dict_structure(self):
        """to_dict should return proper structure."""
        tree = MarkdownTree()
        nid = tree.create_new_node("test", None, "content", "summary")

        result = tree.to_dict()
        self.assertIn("tree", result)
        self.assertIn(str(nid), result["tree"])

    def test_to_dict_node_fields(self):
        """Each node in to_dict should have required fields."""
        tree = MarkdownTree()
        nid = tree.create_new_node("test", None, "content", "summary")

        result = tree.to_dict()
        node_data = result["tree"][str(nid)]
        required_fields = ["id", "title", "content", "summary", "parent_id",
                           "children", "relationships"]
        for field in required_fields:
            self.assertIn(field, node_data, f"Missing field: {field}")

    def test_to_dict_preserves_hierarchy(self):
        """Serialization should preserve parent-child relationships."""
        tree = MarkdownTree()
        root = tree.create_new_node("root", None, "c", "s")
        child = tree.create_new_node("child", root, "c", "s")

        result = tree.to_dict()
        root_data = result["tree"][str(root)]
        child_data = result["tree"][str(child)]

        self.assertIn(child, root_data["children"])
        self.assertEqual(child_data["parent_id"], root)

    def test_empty_tree_serialization(self):
        """Empty tree should serialize cleanly."""
        tree = MarkdownTree()
        result = tree.to_dict()
        self.assertEqual(result, {"tree": {}})


class TestUndoRedo(unittest.TestCase):
    """Test undo/redo functionality for tree operations."""

    def test_undo_stack_exists(self):
        """Tree should have an undo stack."""
        tree = MarkdownTree()
        self.assertIsInstance(tree.undo_stack, list)

    def test_redo_stack_exists(self):
        """Tree should have a redo stack."""
        tree = MarkdownTree()
        self.assertIsInstance(tree.redo_stack, list)

    def test_create_node_pushes_to_undo(self):
        """Creating a node should push an undo operation."""
        tree = MarkdownTree()
        tree.create_new_node("test", None, "content", "summary")
        self.assertGreaterEqual(len(tree.undo_stack), 1)

    def test_undo_create_removes_node(self):
        """Undo after create should remove the created node."""
        tree = MarkdownTree()
        nid = tree.create_new_node("test", None, "content", "summary")

        tree.undo()
        self.assertNotIn(nid, tree.tree)

    def test_redo_after_undo_recreates(self):
        """Redo after undo should restore the node."""
        tree = MarkdownTree()
        nid = tree.create_new_node("test", None, "content", "summary")

        tree.undo()
        self.assertNotIn(nid, tree.tree)

        tree.redo()
        self.assertIn(nid, tree.tree)

    def test_undo_on_empty_stack_is_noop(self):
        """Undo with empty stack should not raise."""
        tree = MarkdownTree()
        tree.undo()  # Should not raise

    def test_redo_on_empty_stack_is_noop(self):
        """Redo with empty stack should not raise."""
        tree = MarkdownTree()
        tree.redo()  # Should not raise


class TestNodeContentOperations(unittest.TestCase):
    """Test content manipulation operations."""

    def test_append_content(self):
        """Appending content should add to node content."""
        tree = MarkdownTree()
        nid = tree.create_new_node("test", None, "original", "summary")
        tree.append_node_content(nid, "appended")
        self.assertIn("appended", tree.tree[nid].content)
        self.assertIn("original", tree.tree[nid].content)

    def test_append_increments_counter(self):
        """Appending should increment num_appends counter."""
        tree = MarkdownTree()
        nid = tree.create_new_node("test", None, "original", "summary")
        self.assertEqual(tree.tree[nid].num_appends, 0)
        tree.append_node_content(nid, "new")
        self.assertEqual(tree.tree[nid].num_appends, 1)

    def test_update_replaces_content(self):
        """Update should replace, not append."""
        tree = MarkdownTree()
        nid = tree.create_new_node("test", None, "original", "summary")
        tree.update_node(nid, "replaced", "new summary")
        self.assertEqual(tree.tree[nid].content, "replaced")
        self.assertNotIn("original", tree.tree[nid].content)

    def test_update_nonexistent_node_raises(self):
        """Updating nonexistent node should raise KeyError."""
        tree = MarkdownTree()
        with self.assertRaises(KeyError):
            tree.update_node(999, "c", "s")

    def test_append_nonexistent_node_raises(self):
        """Appending to nonexistent node should raise KeyError."""
        tree = MarkdownTree()
        with self.assertRaises(KeyError):
            tree.append_node_content(999, "c")


class TestNodeLookup(unittest.TestCase):
    """Test node lookup by name and ID."""

    def test_exact_name_match(self):
        """Should find node by exact name (case-insensitive)."""
        tree = MarkdownTree()
        nid = tree.create_new_node("TestNode", None, "c", "s")
        found = tree.get_node_id_from_name("testnode")
        self.assertEqual(found, nid)

    def test_fuzzy_name_match(self):
        """Should find node by fuzzy match."""
        tree = MarkdownTree()
        nid = tree.create_new_node("architecture_design", None, "c", "s")
        found = tree.get_node_id_from_name("architecture design")
        self.assertEqual(found, nid)

    def test_no_match_returns_none(self):
        """Should return None for no match."""
        tree = MarkdownTree()
        tree.create_new_node("test", None, "c", "s")
        found = tree.get_node_id_from_name("completely_different_xyzzy")
        self.assertIsNone(found)

    def test_empty_name_returns_none(self):
        """Empty name should return None."""
        tree = MarkdownTree()
        found = tree.get_node_id_from_name("")
        self.assertIsNone(found)

    def test_empty_tree_returns_none(self):
        """Search on empty tree returns None."""
        tree = MarkdownTree()
        found = tree.get_node_id_from_name("anything")
        self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
