"""Tests for ThetaAgent document augmentation.

Tests the wikilink and action link injection functionality.
"""

import pytest

from gaius.agents.theta.augmentation import (
    inject_wikilinks,
    inject_action_links,
    inject_mixed,
    strip_augmentation,
    has_augmentation,
    AugmentationResult,
    create_augmentation_block,
    extract_augmentation,
    parse_augmentation_metadata,
)


class TestAugmentationBlock:
    """Tests for augmentation block creation."""

    def test_create_block_wikilinks_only(self):
        """Test creating block with only wikilinks."""
        block = create_augmentation_block(
            wikilinks=["neural networks", "machine learning"],
            action_links=[],
            slice_id="2025-W52",
        )

        assert "BEGIN THETA_AUGMENTATION" in block
        assert "END THETA_AUGMENTATION" in block
        assert "[[neural networks]]" in block
        assert "[[machine learning]]" in block
        assert "slice=2025-W52" in block

    def test_create_block_action_links_only(self):
        """Test creating block with only action links."""
        block = create_augmentation_block(
            wikilinks=[],
            action_links=["kudu optimization", "flink streaming"],
            slice_id="2025-W52",
        )

        assert "[action:search \"kudu optimization\"]" in block
        assert "[action:search \"flink streaming\"]" in block

    def test_create_block_mixed(self):
        """Test creating block with both types."""
        block = create_augmentation_block(
            wikilinks=["concept1"],
            action_links=["query1"],
            slice_id="test",
        )

        assert "[[concept1]]" in block
        assert "[action:search \"query1\"]" in block


class TestWikilinkInjection:
    """Tests for wikilink-style augmentation."""

    def test_inject_wikilinks(self):
        """Test injecting wikilinks into content."""
        content = "This document discusses neural networks."
        concepts = ["neural networks", "machine learning"]

        new_content, count = inject_wikilinks(
            content=content,
            concepts=concepts,
            slice_id="2025-W52",
        )

        assert count == 2
        assert "[[neural networks]]" in new_content
        assert "[[machine learning]]" in new_content
        assert "BEGIN THETA_AUGMENTATION" in new_content

    def test_inject_empty_concepts(self):
        """Test injecting with no concepts."""
        content = "Original content."

        new_content, count = inject_wikilinks(
            content=content,
            concepts=[],
            slice_id="test",
        )

        assert count == 0
        assert new_content == content


class TestActionLinkInjection:
    """Tests for action link augmentation."""

    def test_inject_action_links(self):
        """Test injecting action links."""
        content = "Research topic document."
        queries = ["query1", "query2"]

        new_content, count = inject_action_links(
            content=content,
            queries=queries,
            slice_id="2025-W52",
        )

        assert count == 2
        assert "[action:search \"query1\"]" in new_content
        assert "[action:search \"query2\"]" in new_content


class TestMixedInjection:
    """Tests for combined wikilink and action link injection."""

    def test_inject_mixed(self):
        """Test mixed wikilink and action link injection."""
        content = "Document content here."
        wikilinks = ["concept1", "concept2"]
        action_links = ["search1"]

        new_content, wiki_count, action_count = inject_mixed(
            content=content,
            wikilinks=wikilinks,
            action_links=action_links,
            slice_id="test",
        )

        assert wiki_count == 2
        assert action_count == 1
        assert "[[concept1]]" in new_content
        assert "[[concept2]]" in new_content
        assert "[action:search \"search1\"]" in new_content


class TestAugmentationStripping:
    """Tests for removing augmentation from content."""

    def test_strip_augmentation(self):
        """Test stripping augmentation block."""
        # Create content with augmentation
        original = "Original document content."
        augmented, _ = inject_wikilinks(
            content=original,
            concepts=["test"],
            slice_id="2025-W52",
        )

        # Strip should remove the block
        stripped = strip_augmentation(augmented)

        assert "BEGIN THETA_AUGMENTATION" not in stripped
        assert "END THETA_AUGMENTATION" not in stripped
        assert "Original document content." in stripped

    def test_strip_clean_content(self):
        """Test stripping content without augmentation."""
        content = "This has no augmentation."
        stripped = strip_augmentation(content)

        assert stripped == content.rstrip()


class TestHasAugmentation:
    """Tests for augmentation detection."""

    def test_has_augmentation_true(self):
        """Test detecting augmented content."""
        content, _ = inject_wikilinks(
            content="Test",
            concepts=["concept"],
            slice_id="test",
        )

        assert has_augmentation(content) is True

    def test_has_augmentation_false(self):
        """Test clean content detection."""
        content = "This is a plain document without any special markup."
        assert has_augmentation(content) is False


class TestMetadataExtraction:
    """Tests for augmentation metadata extraction."""

    def test_extract_augmentation(self):
        """Test extracting augmentation block."""
        content, _ = inject_wikilinks(
            content="Test",
            concepts=["concept"],
            slice_id="2025-W52",
            cycle_id="abc123",
        )

        block = extract_augmentation(content)
        assert block is not None
        assert "slice=2025-W52" in block
        assert "cycle_id=abc123" in block

    def test_parse_metadata(self):
        """Test parsing augmentation metadata."""
        content, _ = inject_wikilinks(
            content="Test",
            concepts=["concept"],
            slice_id="2025-W52",
            cycle_id="abc123",
        )

        metadata = parse_augmentation_metadata(content)
        assert metadata is not None
        assert metadata["slice_id"] == "2025-W52"
        assert metadata["cycle_id"] == "abc123"
        assert "timestamp" in metadata
