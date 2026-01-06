"""Gaius TUI widgets."""

from .grid import MainGrid
from .minigrid import MiniGrid
from .filetree import FileTree, FileTreeHighlight
from .info_panel import InfoPanel
from .command import CommandInput
from .location import LocationIndicator
from .note_editor import NoteEditor
from .graph_view import GraphView
from .link_preview import LinkPreview
from .think_panel import ThinkPanel
from .evolution_panel import EvolutionPanel
from .connection_indicator import ConnectionIndicator, ConnectionStatusBar

# Backwards compatibility alias (deprecated, remove in future)
ContentPanel = InfoPanel

__all__ = [
    "MainGrid",
    "MiniGrid",
    "FileTree",
    "FileTreeHighlight",
    "InfoPanel",
    "ContentPanel",  # deprecated alias
    "CommandInput",
    "LocationIndicator",
    "NoteEditor",
    "GraphView",
    "LinkPreview",
    "ThinkPanel",
    "EvolutionPanel",
    "ConnectionIndicator",
    "ConnectionStatusBar",
]
