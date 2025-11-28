"""File tree widget for KB navigation (Plan 9 inspired)."""

from textual.widget import Widget
from textual.widgets import Tree
from textual.widgets.tree import TreeNode
from rich.text import Text

from ..core.state import AppState


class FileTree(Widget):
    """Hierarchical file/agent browser.

    Plan 9 inspired: agents are represented as files.
    Structure:
    /
    ├── Agents/     (virtual, represents swarm)
    └── KB/
        ├── current/  (manual organization)
        ├── scratch/  (Zettelkasten, date-organized)
        └── archive/  (quarterly)
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
        file_tree: dict | None = None,
        agents: list | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.state = state
        self._file_tree = file_tree or {}
        self._agents = agents or []

    def compose(self):
        """Compose the tree widget."""
        tree = Tree("/", id="kb-tree")
        tree.root.expand()

        # Add agents section first (Plan 9: agents as files)
        if self._agents:
            agents_node = tree.root.add("Agents/", expand=True)
            agents_node.data = {"type": "dir", "path": "/Agents"}
            for agent in self._agents:
                agent_node = agents_node.add(f"{agent['name'].lower()}")
                agent_node.data = {
                    "type": "agent",
                    "name": agent["name"],
                    "color": agent.get("color", "white"),
                }

        # Add KB section with file structure
        kb_node = tree.root.add("KB/", expand=True)
        kb_node.data = {"type": "dir", "path": "/KB"}
        self._build_tree(kb_node, self._file_tree)

        yield tree

    def _build_tree(self, parent: TreeNode, structure: dict, path: str = "") -> None:
        """Recursively build tree from dict structure (alphabetically sorted)."""
        for key, value in sorted(structure.items()):
            current_path = f"{path}/{key}" if path else key

            if isinstance(value, dict):
                # Directory
                node = parent.add(f"{key}/")
                node.data = {"type": "dir", "path": current_path}
                self._build_tree(node, value, current_path)
            elif isinstance(value, list):
                # Directory with file list
                node = parent.add(f"{key}/")
                node.data = {"type": "dir", "path": current_path}
                for item in sorted(value):
                    if item.endswith("/"):
                        # Subdirectory
                        subnode = node.add(item)
                        subnode.data = {"type": "dir", "path": f"{current_path}/{item}"}
                    else:
                        # File
                        file_node = node.add(item)
                        file_node.data = {"type": "file", "path": f"{current_path}/{item}"}
            else:
                # Single file
                file_node = parent.add(key)
                file_node.data = {"type": "file", "path": current_path}

    def update_tree(self, file_tree: dict, agents: list) -> None:
        """Update the tree with new data."""
        self._file_tree = file_tree
        self._agents = agents
        # Would need to rebuild tree - for now just store
        self.refresh()

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


class FileTreeSelection:
    """Message sent when a file/agent is selected."""

    def __init__(self, data: dict) -> None:
        self.data = data
