"""Type stubs for metaflow.exception module."""

class MetaflowException(Exception):
    """Base exception for Metaflow errors."""
    ...

class MetaflowNotFound(MetaflowException):
    """Resource not found."""
    ...

class MetaflowInternalError(MetaflowException):
    """Internal Metaflow error."""
    ...
