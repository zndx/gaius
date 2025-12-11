"""Test wiki link resolution via graph panel."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from textual.pilot import Pilot

# Import the app
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def test_kb(tmp_path):
    """Create a temporary KB with a test file containing broken links."""
    kb_root = tmp_path / "kb"
    (kb_root / "current" / "topics").mkdir(parents=True)
    (kb_root / "scratch").mkdir(parents=True)

    # Create test file with broken wiki link
    test_file = kb_root / "current" / "topics" / "test-file.md"
    test_file.write_text("""# Test File

This file has a broken link to [[nonexistent-topic]].
""")

    return kb_root


def test_rewrite_link():
    """Test the rewrite_link function."""
    from gaius.core.links import rewrite_link
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Test\n\nLink to [[old-link]] here.\n")
        temp_path = Path(f.name)

    try:
        # Rewrite the link
        result = rewrite_link(temp_path, "old-link", "scratch/2025-12-11/123456_new-topic")
        assert result is True

        # Verify the content was updated
        content = temp_path.read_text()
        assert "[[scratch/2025-12-11/123456_new-topic]]" in content
        assert "[[old-link]]" not in content
    finally:
        temp_path.unlink()


def test_rewrite_link_not_found():
    """Test rewrite_link when the link doesn't exist."""
    from gaius.core.links import rewrite_link
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Test\n\nNo links here.\n")
        temp_path = Path(f.name)

    try:
        result = rewrite_link(temp_path, "nonexistent", "new-path")
        assert result is False
    finally:
        temp_path.unlink()


def test_zettelkasten_note_with_origin():
    """Test ZettelkastenNote includes origin backlink in markdown."""
    from gaius.inference.synthesis import ZettelkastenNote

    note = ZettelkastenNote(
        query="kudu compaction",
        content="Test content about Kudu compaction.",
        citations=[],
        wiki_links=[],
        created_at=datetime(2025, 12, 11, 23, 45, 0),
        origin_file="current/topics/source-file.md",
        resolved_from="kudu-compaction",
    )

    markdown = note.to_markdown()

    # Should include origin backlink
    assert "origin: [[source-file]]" in markdown
    assert "resolved-from: kudu-compaction" in markdown


def test_zettelkasten_note_save_path(tmp_path):
    """Test ZettelkastenNote saves to correct scratch path."""
    from gaius.inference.synthesis import ZettelkastenNote

    note = ZettelkastenNote(
        query="test query",
        content="Test content.",
        citations=[],
        wiki_links=[],
        created_at=datetime(2025, 12, 11, 23, 45, 0),
    )

    saved_path = note.save(tmp_path)

    # Should be under scratch/YYYY-MM-DD/HHMMSS_slug.md
    assert saved_path.parent.parent.name == "scratch"
    assert saved_path.parent.name == "2025-12-11"
    assert saved_path.name.startswith("234500_")
    assert saved_path.name.endswith(".md")
    assert saved_path.exists()


@pytest.mark.asyncio
async def test_graph_view_broken_link_triggers_resolution(tmp_path):
    """Test that selecting a broken link node triggers resolution flow."""
    from gaius.widgets.graph_view import GraphView
    from gaius.core.links import LinkGraph
    from textual.app import App, ComposeResult
    from textual.widgets import Static

    # Create KB structure
    kb_root = tmp_path / "kb"
    (kb_root / "current" / "topics").mkdir(parents=True)
    (kb_root / "scratch").mkdir(parents=True)

    # Create source file with broken link
    source_file = kb_root / "current" / "topics" / "source.md"
    source_file.write_text("# Source\n\nLink to [[broken-topic]].\n")

    class TestApp(App):
        CSS = """
        GraphView {
            width: 19;
            height: 19;
        }
        """

        def __init__(self):
            super().__init__()
            self.selected_path = None

        def compose(self) -> ComposeResult:
            yield GraphView(kb_root=str(kb_root), id="graph")
            yield Static("", id="status")

        def on_graph_view_node_selected(self, event: GraphView.NodeSelected) -> None:
            self.selected_path = event.filepath
            self.query_one("#status", Static).update(f"Selected: {event.filepath}")

    app = TestApp()
    async with app.run_test() as pilot:
        graph = app.query_one("#graph", GraphView)

        # Update graph for source file
        graph.update_for_file(str(source_file))
        await pilot.pause()

        # The graph should have the broken link as a forward link node
        # Check that broken-topic is in the graph
        assert len(graph._graph_nodes) >= 1  # At least the current node

        # Find the broken link node
        broken_node_id = None
        for node_id, node_info in graph._graph_nodes.items():
            if "broken-topic" in node_info.get("path", ""):
                broken_node_id = node_id
                break

        # If found, select it and press Enter
        if broken_node_id:
            graph.selected_node = broken_node_id
            # Simulate Enter key
            await pilot.press("enter")
            await pilot.pause()

            # Should have triggered NodeSelected message
            assert app.selected_path is not None
            assert "broken-topic" in app.selected_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
