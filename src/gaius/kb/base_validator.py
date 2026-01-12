"""Obsidian .base format validator and parser.

Obsidian Bases provide database-like views over markdown files.
This module validates .base YAML files against the Obsidian schema.

Schema reference: https://help.obsidian.md/bases/syntax

.base files support:
- sources: file paths or folder references
- filters: boolean operators and property comparisons
- formulas: computed properties using prop() function
- views: table, cards, gallery, list with columns/sorting
"""

from dataclasses import dataclass, field
from typing import Any
import yaml


# Valid operators for filter conditions
VALID_OPERATORS = frozenset({
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "before",
    "after",
    "greater_than",
    "less_than",
    "greater_than_or_equal",
    "less_than_or_equal",
    "is_empty",
    "is_not_empty",
})

# Valid view types
VALID_VIEW_TYPES = frozenset({
    "table",
    "cards",
    "gallery",
    "list",
})

# Valid source types
VALID_SOURCE_TYPES = frozenset({
    "file",
    "folder",
})


@dataclass
class ValidationResult:
    """Result of validating a .base file."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
        self.valid = False

    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)

    def merge(self, other: "ValidationResult") -> None:
        """Merge another validation result into this one."""
        if not other.valid:
            self.valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


def validate_base(content: str) -> ValidationResult:
    """Validate .base file content against Obsidian schema.

    Args:
        content: YAML content of the .base file

    Returns:
        ValidationResult with valid flag, errors, and warnings
    """
    result = ValidationResult(valid=True)

    # Parse YAML
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        result.add_error(f"Invalid YAML: {e}")
        return result

    # Handle empty files
    if data is None:
        result.add_error("Empty .base file")
        return result

    # Root must be a mapping
    if not isinstance(data, dict):
        result.add_error(f"Root must be a mapping, got {type(data).__name__}")
        return result

    # Validate optional name/description
    if "name" in data and not isinstance(data["name"], str):
        result.add_error(f"'name' must be a string, got {type(data['name']).__name__}")

    if "description" in data and not isinstance(data["description"], str):
        result.add_error(f"'description' must be a string, got {type(data['description']).__name__}")

    # Validate sources
    if "sources" in data:
        result.merge(_validate_sources(data["sources"]))

    # Validate filter (string shorthand) or filters (structured)
    if "filter" in data:
        result.merge(_validate_filter_string(data["filter"]))

    if "filters" in data:
        result.merge(_validate_filters(data["filters"]))

    # Validate formulas
    if "formulas" in data:
        result.merge(_validate_formulas(data["formulas"]))

    # Validate views
    if "views" in data:
        result.merge(_validate_views(data["views"]))

    return result


def _validate_sources(sources: Any) -> ValidationResult:
    """Validate sources section."""
    result = ValidationResult(valid=True)

    if not isinstance(sources, list):
        result.add_error(f"'sources' must be a list, got {type(sources).__name__}")
        return result

    for i, source in enumerate(sources):
        if not isinstance(source, dict):
            result.add_error(f"Source {i} must be a mapping, got {type(source).__name__}")
            continue

        # Check for valid source keys
        if "file" in source:
            if not isinstance(source["file"], str):
                result.add_error(f"Source {i} 'file' must be a string")
        elif "type" in source:
            # Type-based source definition
            if source["type"] not in VALID_SOURCE_TYPES:
                result.add_error(f"Source {i} has invalid type: {source['type']}")
            if "path" not in source:
                result.add_error(f"Source {i} with type requires 'path'")
        elif "folder" in source:
            # Legacy folder syntax
            if not isinstance(source["folder"], str):
                result.add_error(f"Source {i} 'folder' must be a string")
        else:
            result.add_warning(f"Source {i} has no recognized source key (file, folder, or type)")

    return result


def _validate_filter_string(filter_str: Any) -> ValidationResult:
    """Validate filter string shorthand."""
    result = ValidationResult(valid=True)

    if not isinstance(filter_str, str):
        result.add_error(f"'filter' must be a string, got {type(filter_str).__name__}")

    return result


def _validate_filters(filters: Any) -> ValidationResult:
    """Validate filters section (structured format)."""
    result = ValidationResult(valid=True)

    if isinstance(filters, list):
        for i, f in enumerate(filters):
            result.merge(_validate_filter_item(f, f"filters[{i}]"))
    elif isinstance(filters, dict):
        result.merge(_validate_filter_item(filters, "filters"))
    else:
        result.add_error(f"'filters' must be list or mapping, got {type(filters).__name__}")

    return result


def _validate_filter_item(item: Any, path: str) -> ValidationResult:
    """Validate a single filter item (may contain boolean operators)."""
    result = ValidationResult(valid=True)

    if not isinstance(item, dict):
        result.add_error(f"{path} must be a mapping, got {type(item).__name__}")
        return result

    # Check for boolean operators
    if "and" in item:
        if not isinstance(item["and"], list):
            result.add_error(f"{path}.and must be a list")
        else:
            for i, sub in enumerate(item["and"]):
                result.merge(_validate_filter_item(sub, f"{path}.and[{i}]"))

    if "or" in item:
        if not isinstance(item["or"], list):
            result.add_error(f"{path}.or must be a list")
        else:
            for i, sub in enumerate(item["or"]):
                result.merge(_validate_filter_item(sub, f"{path}.or[{i}]"))

    if "not" in item:
        result.merge(_validate_filter_item(item["not"], f"{path}.not"))

    # Validate leaf filter with operator
    if "operator" in item:
        if item["operator"] not in VALID_OPERATORS:
            result.add_error(f"{path} has invalid operator: {item['operator']}")

        # Property is required for most operators
        if "property" not in item:
            result.add_warning(f"{path} has operator but no property")

    return result


def _validate_formulas(formulas: Any) -> ValidationResult:
    """Validate formulas section."""
    result = ValidationResult(valid=True)

    if not isinstance(formulas, dict):
        result.add_error(f"'formulas' must be a mapping, got {type(formulas).__name__}")
        return result

    for name, formula_def in formulas.items():
        if not isinstance(name, str):
            result.add_error(f"Formula name must be a string, got {type(name).__name__}")
            continue

        # Formula can be a string or a dict with 'formula' key
        if isinstance(formula_def, str):
            # String shorthand - valid
            pass
        elif isinstance(formula_def, dict):
            if "formula" not in formula_def:
                result.add_error(f"Formula '{name}' missing 'formula' key")
            elif not isinstance(formula_def["formula"], str):
                result.add_error(f"Formula '{name}' formula must be a string")
        else:
            result.add_error(f"Formula '{name}' must be string or mapping, got {type(formula_def).__name__}")

    return result


def _validate_views(views: Any) -> ValidationResult:
    """Validate views section."""
    result = ValidationResult(valid=True)

    if not isinstance(views, dict):
        result.add_error(f"'views' must be a mapping, got {type(views).__name__}")
        return result

    for name, view_def in views.items():
        if not isinstance(name, str):
            result.add_error(f"View name must be a string")
            continue

        if not isinstance(view_def, dict):
            result.add_error(f"View '{name}' must be a mapping, got {type(view_def).__name__}")
            continue

        # Validate view type
        if "type" in view_def:
            if view_def["type"] not in VALID_VIEW_TYPES:
                result.add_error(f"View '{name}' has invalid type: {view_def['type']}")

        # Validate columns (for table views)
        if "columns" in view_def:
            if not isinstance(view_def["columns"], list):
                result.add_error(f"View '{name}' columns must be a list")
            else:
                for i, col in enumerate(view_def["columns"]):
                    # Column can be a string (property name) or dict with property key
                    if not isinstance(col, (str, dict)):
                        result.add_error(f"View '{name}' column {i} must be string or mapping")
                    elif isinstance(col, dict) and "property" not in col:
                        result.add_warning(f"View '{name}' column {i} mapping has no 'property' key")

        # Validate sort_by
        if "sort_by" in view_def:
            sort_by = view_def["sort_by"]
            if not isinstance(sort_by, (str, list)):
                result.add_error(f"View '{name}' sort_by must be string or list")

        # Validate sort (alternative syntax)
        if "sort" in view_def:
            sort_val = view_def["sort"]
            if not isinstance(sort_val, list):
                result.add_error(f"View '{name}' sort must be a list")

        # Validate limit
        if "limit" in view_def:
            if not isinstance(view_def["limit"], int):
                result.add_error(f"View '{name}' limit must be an integer")

        # Validate view-level filter
        if "filter" in view_def:
            if not isinstance(view_def["filter"], str):
                result.add_error(f"View '{name}' filter must be a string")

    return result


def parse_base(content: str) -> dict[str, Any] | None:
    """Parse .base file content into a dictionary.

    Args:
        content: YAML content of the .base file

    Returns:
        Parsed dictionary or None if parsing fails
    """
    try:
        return yaml.safe_load(content)
    except yaml.YAMLError:
        return None
