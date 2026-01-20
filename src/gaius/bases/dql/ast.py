"""AST nodes for DQL expressions."""

from dataclasses import dataclass
from typing import Any, Literal, Union


@dataclass(frozen=True)
class BinaryOp:
    """Binary operation (e.g., AND, OR, =, !=, <, etc.)."""

    left: "Expression"
    op: str  # AND, OR, =, !=, <, <=, >, >=, LIKE, IN
    right: "Expression"

    def __repr__(self) -> str:
        return f"({self.left} {self.op} {self.right})"


@dataclass(frozen=True)
class UnaryOp:
    """Unary operation (e.g., NOT)."""

    op: str  # NOT
    operand: "Expression"

    def __repr__(self) -> str:
        return f"({self.op} {self.operand})"


@dataclass(frozen=True)
class Identifier:
    """Column or field identifier."""

    name: str

    def __repr__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Literal:
    """Literal value (string, number, boolean, null, timestamp)."""

    value: Any
    type: str  # string, number, boolean, null, timestamp

    def __repr__(self) -> str:
        if self.type == "string":
            return f"'{self.value}'"
        elif self.type == "null":
            return "NULL"
        return str(self.value)


@dataclass(frozen=True)
class ListLiteral:
    """List of literals for IN operator."""

    values: tuple[Literal, ...]

    def __repr__(self) -> str:
        return f"({', '.join(repr(v) for v in self.values)})"


# Type alias for all expression types
Expression = Union[BinaryOp, UnaryOp, Identifier, Literal, ListLiteral]
