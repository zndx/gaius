"""File tree widget for KB navigation (Plan 9 inspired)."""

from pathlib import Path

from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Tree
from textual.widgets.tree import TreeNode
from textual.message import Message

from ..core.state import AppState


class VimTree(Tree):
    """Tree widget with vim-style navigation keys."""

    BINDINGS = [
        Binding("G", "goto_last", "Go to last", show=False),
        Binding("g", "goto_first_prefix", "Go to first (gg)", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._g_pressed = False

    def action_goto_last(self) -> None:
        """Jump to the absolute last leaf node, expanding folders as needed (G)."""
        self._g_pressed = False  # Reset any pending g

        # Find the absolute last leaf, expanding collapsed folders along the way
        def get_absolute_last_leaf(node: TreeNode) -> TreeNode:
            """Recursively find the absolute last leaf, expanding as we go."""
            if not node.children:
                return node

            # Expand the node to access children
            if not node.is_expanded:
                node.expand()

            # Recurse into the last child
            return get_absolute_last_leaf(node.children[-1])

        if self.root.children:
            last_node = get_absolute_last_leaf(self.root.children[-1])
            # Schedule cursor move after tree refreshes from expansions
            self.call_after_refresh(self._focus_node, last_node)

    def _focus_node(self, node: TreeNode) -> None:
        """Move cursor to node and ensure it's visible (called after refresh)."""
        self.move_cursor(node)
        self.scroll_to_node(node)
        self.focus()

    def action_goto_first_prefix(self) -> None:
        """Handle first 'g' press - wait for second 'g' for gg."""
        if self._g_pressed:
            # Second g - go to first
            self._g_pressed = False
            if self.root.children:
                first_node = self.root.children[0]
                self._focus_node(first_node)
        else:
            # First g - set flag, reset after short timeout
            self._g_pressed = True
            self.set_timer(0.5, self._reset_g_pressed)

    def _reset_g_pressed(self) -> None:
        """Reset the g-pressed state after timeout."""
        self._g_pressed = False


class FileTreeSelection(Message):
    """Message sent when a file/agent is selected (Enter pressed)."""

    def __init__(self, data: dict) -> None:
        self.data = data
        super().__init__()


class FileTreeHighlight(Message):
    """Message sent when cursor moves to a new node (for graph preview)."""

    def __init__(self, data: dict) -> None:
        self.data = data
        super().__init__()


class FileTree(Widget):
    """Hierarchical file/agent browser.

    Plan 9 inspired: agents are represented as files.
    Structure (root node hidden):
    Agents/     (virtual, represents swarm)
    KB/
    ├── current/  (manual organization)
    ├── scratch/  (Zettelkasten, date-organized)
    └── archive/  (quarterly)

    The KB section scans the actual filesystem under kb_root.
    """

    DEFAULT_CSS = """
    FileTree {
        width: 100%;
        height: 100%;
        background: $surface;
    }

    FileTree > Tree {
        width: 100%;
        height: 100%;
        scrollbar-size: 1 1;
    }
    """

    def __init__(
        self,
        state: AppState,
        agents: list | None = None,
        kb_root: str = "build/dev",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.state = state
        self._agents = agents or []
        self._kb_root = Path(kb_root)
        self._tree: VimTree | None = None

    def compose(self):
        """Compose the tree widget."""
        self._tree = VimTree("Gaius", id="kb-tree")
        self._tree.show_root = False  # Hide the root node for cleaner UX
        self._tree.root.expand()
        self._populate_tree()
        yield self._tree

    def _populate_tree(self) -> None:
        """Populate the tree from filesystem and agent data."""
        if not self._tree:
            return

        # Clear existing nodes (keep root)
        self._tree.root.remove_children()

        # Add agents section first (Plan 9: agents as files)
        if self._agents:
            agents_node = self._tree.root.add("Agents/", expand=True)
            agents_node.data = {"type": "dir", "path": "/Agents"}
            for agent in sorted(self._agents, key=lambda a: a["name"].lower()):
                agent_node = agents_node.add(f"{agent['name'].lower()}")
                agent_node.data = {
                    "type": "agent",
                    "name": agent["name"],
                    "role": agent.get("role", ""),
                    "color": agent.get("color", "white"),
                    "last": agent.get("last", ""),
                }

        # Add KB section from filesystem
        kb_node = self._tree.root.add("KB/", expand=True)
        kb_node.data = {"type": "dir", "path": str(self._kb_root)}

        # Scan the three KB directories
        for subdir in ["archive", "current", "scratch"]:
            subdir_path = self._kb_root / subdir
            if subdir_path.exists():
                self._add_directory(kb_node, subdir_path, subdir)

    def _add_directory(self, parent: TreeNode, path: Path, name: str) -> None:
        """Recursively add a directory to the tree."""
        node = parent.add(f"{name}/")
        node.data = {"type": "dir", "path": str(path)}

        # Get sorted contents (directories first, then files)
        try:
            items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        for item in items:
            if item.name.startswith("."):
                continue  # Skip hidden files

            if item.is_dir():
                self._add_directory(node, item, item.name)
            else:
                file_node = node.add(item.name)
                file_node.data = {"type": "file", "path": str(item)}

    def refresh_tree(self) -> None:
        """Refresh the tree by rescanning the filesystem."""
        self._populate_tree()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle tree node selection."""
        node = event.node
        if node.data:
            if node.data["type"] == "file":
                self.state.selected_file = node.data["path"]
                self.state.selected_agent = None
            elif node.data["type"] == "agent":
                self.state.selected_agent = node.data["name"]
                self.state.selected_file = None
            # Post message for parent to handle
            self.post_message(FileTreeSelection(node.data))

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Handle cursor movement - post highlight for graph preview."""
        node = event.node
        if node.data:
            self.post_message(FileTreeHighlight(node.data))

    def highlight_path(self, filepath: str) -> None:
        """Move cursor to the node matching filepath (for graph sync)."""
        if not self._tree:
            return

        # Recursive search for node with matching path
        def find_node(node: TreeNode) -> TreeNode | None:
            if node.data and node.data.get("path") == filepath:
                return node
            for child in node.children:
                result = find_node(child)
                if result:
                    return result
            return None

        found = find_node(self._tree.root)
        if found:
            # Expand parent nodes to make target visible
            parent = found.parent
            while parent:
                parent.expand()
                parent = parent.parent
            # Scroll to make the node visible
            self._tree.scroll_to_node(found)
