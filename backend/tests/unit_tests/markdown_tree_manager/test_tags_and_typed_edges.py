"""Tests for Tag-First Knowledge Model with Multi-Relational Edges (Issue #8).

Covers:
- First-class tags on Node schema
- Typed edge taxonomy (references, depends_on, contradicts, extends, example_of, related_to)
- Tag extraction from content
- Tag-based node querying
- Retrieval scoring with tag overlap
"""

import unittest

from backend.markdown_tree_manager.markdown_tree_ds import MarkdownTree, Node


class TestNodeTags(unittest.TestCase):
    """Test tag support on the Node data structure."""

    def test_node_has_tags_field(self):
        """Node should have a tags list field."""
        node = Node("test", 1, "content", "summary")
        self.assertIsInstance(node.tags, list)
        self.assertEqual(node.tags, [])

    def test_node_tags_can_be_set(self):
        """Tags can be assigned to a node."""
        node = Node("test", 1, "content", "summary")
        node.tags = ["python", "backend", "api"]
        self.assertEqual(node.tags, ["python", "backend", "api"])

    def test_node_color_field_exists(self):
        """Node should have a color attribute."""
        node = Node("test", 1, "content", "summary")
        self.assertIsNone(node.color)


class TestTreeTagOperations(unittest.TestCase):
    """Test tree-level tag operations."""

    def setUp(self):
        self.tree = MarkdownTree()

    def test_create_node_preserves_tags(self):
        """Creating a node should preserve its default empty tags."""
        node_id = self.tree.create_new_node("test", None, "content", "summary")
        self.assertEqual(self.tree.tree[node_id].tags, [])

    def test_add_tags_to_node(self):
        """Tags can be added to existing nodes."""
        node_id = self.tree.create_new_node("test", None, "content", "summary")
        self.tree.tree[node_id].tags = ["architecture", "design"]
        self.assertEqual(self.tree.tree[node_id].tags, ["architecture", "design"])

    def test_get_nodes_by_tag(self):
        """Should be able to find nodes by tag."""
        n1 = self.tree.create_new_node("Node A", None, "Python backend", "summary A")
        n2 = self.tree.create_new_node("Node B", n1, "React frontend", "summary B")
        n3 = self.tree.create_new_node("Node C", n1, "Python API", "summary C")

        self.tree.tree[n1].tags = ["python", "backend"]
        self.tree.tree[n2].tags = ["react", "frontend"]
        self.tree.tree[n3].tags = ["python", "api"]

        # Query by tag
        python_nodes = self.tree.get_nodes_by_tag("python")
        self.assertIn(n1, python_nodes)
        self.assertIn(n3, python_nodes)
        self.assertNotIn(n2, python_nodes)

    def test_get_nodes_by_tag_empty(self):
        """Querying a nonexistent tag should return empty list."""
        self.tree.create_new_node("test", None, "content", "summary")
        result = self.tree.get_nodes_by_tag("nonexistent")
        self.assertEqual(result, [])

    def test_get_all_tags(self):
        """Should return all unique tags across all nodes."""
        n1 = self.tree.create_new_node("A", None, "content", "summary")
        n2 = self.tree.create_new_node("B", n1, "content", "summary")

        self.tree.tree[n1].tags = ["python", "api"]
        self.tree.tree[n2].tags = ["python", "frontend"]

        all_tags = self.tree.get_all_tags()
        self.assertEqual(sorted(all_tags), ["api", "frontend", "python"])


class TestTypedEdges(unittest.TestCase):
    """Test multi-relational typed edge support."""

    VALID_RELATION_TYPES = [
        "child_of", "references", "depends_on", "contradicts",
        "extends", "example_of", "related_to"
    ]

    def setUp(self):
        self.tree = MarkdownTree()

    def test_default_relationship_type(self):
        """Default relationship should be 'child of'."""
        parent_id = self.tree.create_new_node("parent", None, "content", "summary")
        child_id = self.tree.create_new_node("child", parent_id, "content", "summary")
        self.assertEqual(
            self.tree.tree[child_id].relationships[parent_id],
            "child of"
        )

    def test_custom_relationship_type(self):
        """Should support custom relationship types."""
        parent_id = self.tree.create_new_node("parent", None, "content", "summary")
        child_id = self.tree.create_new_node(
            "child", parent_id, "content", "summary",
            relationship_to_parent="depends_on"
        )
        self.assertEqual(
            self.tree.tree[child_id].relationships[parent_id],
            "depends_on"
        )

    def test_set_parent_child_with_relationship(self):
        """set_parent_child_connection should support typed relationships."""
        n1 = self.tree.create_new_node("A", None, "content", "summary")
        n2 = self.tree.create_new_node("B", None, "content", "summary")

        self.tree.set_parent_child_connection(n1, n2, relationship="extends")
        self.assertEqual(self.tree.tree[n2].relationships[n1], "extends")

    def test_multiple_relationships_per_node(self):
        """A node should support relationships to multiple other nodes."""
        n1 = self.tree.create_new_node("A", None, "content", "summary")
        n2 = self.tree.create_new_node("B", n1, "content", "summary")
        n3 = self.tree.create_new_node("C", None, "content", "summary")

        # Add additional relationship
        self.tree.tree[n2].relationships[n3] = "references"

        self.assertIn(n1, self.tree.tree[n2].relationships)
        self.assertIn(n3, self.tree.tree[n2].relationships)


class TestTreeSerialization(unittest.TestCase):
    """Test tree serialization includes tags and typed edges."""

    def test_to_dict_includes_tags(self):
        """to_dict should include tags in serialization."""
        tree = MarkdownTree()
        node_id = tree.create_new_node("test", None, "content", "summary")
        tree.tree[node_id].tags = ["python", "backend"]

        result = tree.to_dict()
        node_data = result["tree"][str(node_id)]
        self.assertIn("tags", node_data)
        self.assertEqual(node_data["tags"], ["python", "backend"])

    def test_to_dict_includes_relationships(self):
        """to_dict should include relationship types."""
        tree = MarkdownTree()
        parent = tree.create_new_node("parent", None, "content", "summary")
        child = tree.create_new_node("child", parent, "content", "summary",
                                      relationship_to_parent="depends_on")

        result = tree.to_dict()
        child_data = result["tree"][str(child)]
        self.assertIn("relationships", child_data)
        self.assertEqual(child_data["relationships"][parent], "depends_on")


class TestTagExtraction(unittest.TestCase):
    """Test automatic tag extraction from content."""

    def test_extract_hashtags_from_content(self):
        """Should extract hashtag-style tags from content."""
        from backend.markdown_tree_manager.utils import extract_tags_from_content
        content = "This is about #python and #machinelearning"
        tags = extract_tags_from_content(content)
        self.assertIn("python", tags)
        self.assertIn("machinelearning", tags)

    def test_extract_no_tags_from_plain_content(self):
        """Plain content without hashtags should return empty."""
        from backend.markdown_tree_manager.utils import extract_tags_from_content
        content = "This is plain content with no tags"
        tags = extract_tags_from_content(content)
        self.assertEqual(tags, [])

    def test_extract_tags_ignores_markdown_headers(self):
        """Should not extract markdown headers as tags."""
        from backend.markdown_tree_manager.utils import extract_tags_from_content
        content = "# Header\n## Subheader\nSome #realtag here"
        tags = extract_tags_from_content(content)
        self.assertNotIn("Header", tags)
        self.assertNotIn("Subheader", tags)
        self.assertIn("realtag", tags)


if __name__ == "__main__":
    unittest.main()
