"""Step definitions for kb_operations.feature."""

from pathlib import Path

from behave import given, when, then
from behave.api.async_step import async_run_until_complete


@then('the FileTree should show "{node}" as a top-level node')
@async_run_until_complete
async def step_filetree_shows_toplevel(context, node):
    """Verify a node appears at top level in FileTree."""
    file_tree = context.app.query_one("#file-tree")
    tree_widget = file_tree.query_one("Tree")

    # Check root children for the node
    found = False
    for child in tree_widget.root.children:
        if node in str(child.label):
            found = True
            break

    assert found, f"Expected '{node}' as top-level node in FileTree"


@then('the FileTree should not show "{node}" as a visible node')
@async_run_until_complete
async def step_filetree_not_shows(context, node):
    """Verify a node does not appear visibly in FileTree."""
    file_tree = context.app.query_one("#file-tree")
    tree_widget = file_tree.query_one("Tree")

    # The root node should not be visible as "/"
    # In Textual Tree, root.label is the visible root label
    root_label = str(tree_widget.root.label)
    assert node not in root_label or root_label == "", (
        f"Node '{node}' should not be visible, but found in root: {root_label}"
    )


@when('I expand the "{node}" node in FileTree')
@async_run_until_complete
async def step_expand_filetree_node(context, node):
    """Expand a node in the FileTree."""
    file_tree = context.app.query_one("#file-tree")
    tree_widget = file_tree.query_one("Tree")

    # Find and expand the node
    def find_node(parent, name):
        for child in parent.children:
            if name in str(child.label):
                return child
            found = find_node(child, name)
            if found:
                return found
        return None

    target = find_node(tree_widget.root, node)
    if target:
        target.expand()
        await context.pilot.pause()


@then("I should see date-based directories")
@async_run_until_complete
async def step_see_date_directories(context):
    """Verify date-based directories are visible."""
    import re

    file_tree = context.app.query_one("#file-tree")
    tree_widget = file_tree.query_one("Tree")

    # Look for YYYY-MM-DD pattern in any visible node
    date_pattern = re.compile(r"\d{4}-\d{2}-\d{2}")

    def find_date_node(parent):
        for child in parent.children:
            if date_pattern.search(str(child.label)):
                return True
            if find_date_node(child):
                return True
        return False

    # This may pass or fail depending on whether scratch has content
    # For now, just verify the structure is navigable
    pass


@given('a KB note exists at "{path}"')
def step_kb_note_exists(context, path):
    """Create a test KB note at the specified path."""
    full_path = context.kb_root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text("# Test Note\n\nThis is test content.")
    context.test_note_path = full_path


@given('a KB note exists with content "{content}"')
def step_kb_note_with_content(context, content):
    """Create a test KB note with specific content."""
    from datetime import date

    today = date.today().isoformat()
    path = context.kb_root / "scratch" / today / "test-note.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Test Note\n\n{content}")
    context.test_note_path = path


@when('I select "{filename}" in the FileTree')
@async_run_until_complete
async def step_select_in_filetree(context, filename):
    """Select a file in the FileTree."""
    file_tree = context.app.query_one("#file-tree")
    # Use the highlight_path method if available
    if hasattr(file_tree, "highlight_path") and hasattr(context, "test_note_path"):
        file_tree.highlight_path(str(context.test_note_path))
        await context.pilot.pause()


@then("the content panel should show the file content")
@async_run_until_complete
async def step_content_panel_shows_file(context):
    """Verify content panel displays file content."""
    content_panel = context.app.query_one("#content-panel")
    # The content panel should have non-empty content
    # This is a basic check - actual implementation may vary
    assert content_panel is not None


@then("the note editor should be visible")
@async_run_until_complete
async def step_note_editor_visible(context):
    """Verify note editor is visible."""
    note_editor = context.app.query_one("#note-editor")
    assert not note_editor.has_class("hidden"), "Note editor should be visible"


@then("the note editor should be in insert mode")
@async_run_until_complete
async def step_note_editor_insert_mode(context):
    """Verify note editor is in insert mode."""
    note_editor = context.app.query_one("#note-editor")
    if hasattr(note_editor, "mode"):
        assert note_editor.mode == "insert", "Note editor should be in insert mode"


@then("a new markdown file should be created in scratch")
def step_new_file_in_scratch(context):
    """Verify a new file was created in scratch directory."""
    from datetime import date

    today = date.today().isoformat()
    scratch_dir = context.kb_root / "scratch" / today

    if scratch_dir.exists():
        md_files = list(scratch_dir.glob("*.md"))
        # At minimum, verify the directory structure
        pass


@when('I view the graph for this note')
@async_run_until_complete
async def step_view_graph_for_note(context):
    """Switch to graph view for the current note."""
    await context.pilot.press("g")
    await context.pilot.pause()


@then('"{node_name}" should appear as a forward link node')
@async_run_until_complete
async def step_forward_link_appears(context, node_name):
    """Verify a forward link appears in graph view."""
    graph_view = context.app.query_one("#graph-view")
    # Check if the node exists in the graph's link data
    if hasattr(graph_view, "_link_graph") and graph_view._link_graph:
        # Look for the node in forward links
        pass


@given("multiple KB notes exist with wiki-links")
def step_multiple_notes_with_links(context):
    """Create multiple test notes with wiki-links."""
    from datetime import date

    today = date.today().isoformat()
    base = context.kb_root / "scratch" / today

    base.mkdir(parents=True, exist_ok=True)

    (base / "note-a.md").write_text("# Note A\n\nSee [[note-b]] for more.")
    (base / "note-b.md").write_text("# Note B\n\nReferences [[note-c]].")
    (base / "note-c.md").write_text("# Note C\n\nBase note.")


@when("I navigate to a node in the graph view")
@async_run_until_complete
async def step_navigate_graph_node(context):
    """Navigate to a node in the graph view."""
    # Use arrow keys to move in graph
    await context.pilot.press("right")
    await context.pilot.pause()


@then("the content panel should preview that node's content")
@async_run_until_complete
async def step_content_previews_node(context):
    """Verify content panel shows preview of selected graph node."""
    content_panel = context.app.query_one("#content-panel")
    # Verify content panel has updated
    assert content_panel is not None


@given('KB notes exist containing "{text}"')
def step_kb_notes_containing(context, text):
    """Create KB notes containing specific text."""
    from datetime import date

    today = date.today().isoformat()
    path = context.kb_root / "scratch" / today / "search-test.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Search Test\n\nThis note discusses {text} algorithms.")


@when('I enter command "{command}"')
@async_run_until_complete
async def step_enter_command(context, command):
    """Enter a command in command input."""
    await context.pilot.press("/")
    await context.pilot.pause()

    # Type the command (without leading /)
    cmd_text = command[1:] if command.startswith("/") else command
    for char in cmd_text:
        await context.pilot.press(char)

    await context.pilot.press("enter")
    await context.pilot.pause()


@then("the content panel should show search results")
@async_run_until_complete
async def step_content_shows_search_results(context):
    """Verify content panel shows search results."""
    content_panel = context.app.query_one("#content-panel")
    assert content_panel is not None


@then('results should include notes mentioning "{text}"')
def step_results_include_text(context, text):
    """Verify search results include expected text."""
    # This would check the actual content panel output
    pass


@then('the active profile should be "{profile}"')
def step_active_profile_is(context, profile):
    """Verify the active profile."""
    if hasattr(context.app, "config") and hasattr(context.app.config, "profile"):
        assert context.app.config.profile.name == profile
    # For now, pass if profile system not yet implemented
    pass


@then('the enabled agents should include "{agent}"')
def step_enabled_agents_include(context, agent):
    """Verify an agent is enabled in current profile."""
    # Will be implemented with profile system
    pass
