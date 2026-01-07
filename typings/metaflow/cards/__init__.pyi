"""Type stubs for metaflow.cards module."""

from typing import Any

class MetaflowCard:
    """Base class for Metaflow cards."""
    type: str
    def __init__(self, **kwargs: Any) -> None: ...
    def append(self, component: Any) -> None: ...
    def refresh(self, data: Any = None) -> None: ...

class BlankCard(MetaflowCard):
    """Blank card for custom content."""
    ...

class Markdown(MetaflowCard):
    """Markdown content card."""
    def __init__(self, text: str = "", **kwargs: Any) -> None: ...

class Image(MetaflowCard):
    """Image card."""
    def __init__(self, src: str = "", **kwargs: Any) -> None: ...

class Table(MetaflowCard):
    """Table card."""
    def __init__(self, data: Any = None, **kwargs: Any) -> None: ...

class Artifact(MetaflowCard):
    """Artifact reference card."""
    def __init__(self, name: str = "", **kwargs: Any) -> None: ...
