"""Safe parser for fluent query expressions.

Parses user-provided fluent query strings into BaseQuery objects
using Python's AST module. This is a security-critical component
that rejects arbitrary code execution.

Example:
    >>> parse_fluent('Base("events").where(col("age") > 30).limit(10)')
    BaseQuery(_base_name="events", _predicates=[...], _limit_value=10)

Guru Meditation Codes:
- #FLUENT.00000001.BADAST - Invalid AST node
- #FLUENT.00000002.UNSAFEOP - Unsafe operation attempted
"""

from __future__ import annotations

import ast
from typing import Any

from gaius.bases.fluent.builder import Base, BaseQuery
from gaius.bases.fluent.expressions import col, term, ColumnRef, TermRef, Comparison


# Allowed top-level names
ALLOWED_NAMES = frozenset({"Base", "col", "term", "True", "False", "None"})

# Allowed method names on BaseQuery
ALLOWED_METHODS = frozenset({
    "where",
    "select",
    "order_by",
    "limit",
    "as_of",
    "scan",
    # Note: scan() is allowed but will be stripped for dry-run parsing
})

# Allowed methods on column/term refs
ALLOWED_REF_METHODS = frozenset({
    "isin",
    "like",
    "is_null",
    "is_not_null",
})

# Allowed comparison operators
ALLOWED_COMPARE_OPS = frozenset({
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
})


class FluentParseError(Exception):
    """Error parsing fluent query expression.

    Guru Meditation: #FLUENT.00000001.BADAST
    """

    pass


class UnsafeOperationError(Exception):
    """Attempted unsafe operation in fluent expression.

    Guru Meditation: #FLUENT.00000002.UNSAFEOP
    """

    pass


def parse_fluent(expr: str) -> BaseQuery:
    """Parse a fluent query expression string.

    This function safely parses user-provided query strings without
    using eval(). It walks the AST and builds the query object directly.

    Args:
        expr: Fluent query string like 'Base("events").where(col("x") > 1)'

    Returns:
        Constructed BaseQuery object

    Raises:
        FluentParseError: If expression syntax is invalid
        UnsafeOperationError: If expression contains disallowed operations

    Example:
        >>> q = parse_fluent('Base("users").where(col("age") > 30).limit(10)')
        >>> q._base_name
        'users'
        >>> q._limit_value
        10
    """
    if not expr or not expr.strip():
        raise FluentParseError("Empty expression")

    # Strip .scan() if present - we build the query without executing
    expr = expr.strip()
    if expr.endswith(".scan()"):
        expr = expr[:-7]

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise FluentParseError(f"Syntax error: {e}") from e

    return _eval_ast(tree.body)


def _eval_ast(node: ast.AST) -> Any:
    """Recursively evaluate AST node with strict whitelisting."""
    if isinstance(node, ast.Call):
        return _eval_call(node)
    elif isinstance(node, ast.Attribute):
        return _eval_attribute(node)
    elif isinstance(node, ast.Name):
        return _eval_name(node)
    elif isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Compare):
        return _eval_compare(node)
    elif isinstance(node, ast.BinOp):
        return _eval_binop(node)
    elif isinstance(node, ast.UnaryOp):
        return _eval_unaryop(node)
    elif isinstance(node, ast.List):
        return [_eval_ast(elt) for elt in node.elts]
    elif isinstance(node, ast.Tuple):
        return tuple(_eval_ast(elt) for elt in node.elts)
    else:
        raise FluentParseError(
            f"Unsupported AST node: {type(node).__name__}\n"
            "Guru Meditation: #FLUENT.00000001.BADAST"
        )


def _eval_name(node: ast.Name) -> Any:
    """Evaluate a Name node (variable reference)."""
    name = node.id
    if name not in ALLOWED_NAMES:
        raise UnsafeOperationError(
            f"Name '{name}' not allowed\n"
            "Guru Meditation: #FLUENT.00000002.UNSAFEOP"
        )

    # Return the actual function/value
    if name == "Base":
        return Base
    elif name == "col":
        return col
    elif name == "term":
        return term
    elif name == "True":
        return True
    elif name == "False":
        return False
    elif name == "None":
        return None
    else:
        raise UnsafeOperationError(f"Unexpected name: {name}")


def _eval_call(node: ast.Call) -> Any:
    """Evaluate a function call."""
    # Get the callable
    func = _eval_ast(node.func)

    # Evaluate arguments
    args = [_eval_ast(arg) for arg in node.args]

    # Evaluate keyword arguments
    kwargs = {kw.arg: _eval_ast(kw.value) for kw in node.keywords if kw.arg}

    # Call the function
    if callable(func):
        return func(*args, **kwargs)
    else:
        raise FluentParseError(f"Not callable: {func}")


def _eval_attribute(node: ast.Attribute) -> Any:
    """Evaluate an attribute access (method call chain)."""
    obj = _eval_ast(node.value)
    attr = node.attr

    # Check if this is a method on BaseQuery
    if isinstance(obj, BaseQuery):
        if attr not in ALLOWED_METHODS:
            raise UnsafeOperationError(
                f"Method '{attr}' not allowed on BaseQuery\n"
                "Guru Meditation: #FLUENT.00000002.UNSAFEOP"
            )
        return getattr(obj, attr)

    # Check if this is a method on ColumnRef/TermRef
    if isinstance(obj, (ColumnRef, TermRef)):
        if attr not in ALLOWED_REF_METHODS:
            raise UnsafeOperationError(
                f"Method '{attr}' not allowed on column/term reference\n"
                "Guru Meditation: #FLUENT.00000002.UNSAFEOP"
            )
        return getattr(obj, attr)

    raise FluentParseError(f"Cannot access attribute '{attr}' on {type(obj).__name__}")


def _eval_compare(node: ast.Compare) -> Comparison:
    """Evaluate a comparison expression."""
    if len(node.ops) != 1 or len(node.comparators) != 1:
        raise FluentParseError("Only single comparisons supported")

    op = node.ops[0]
    if type(op) not in ALLOWED_COMPARE_OPS:
        raise UnsafeOperationError(
            f"Comparison operator '{type(op).__name__}' not allowed\n"
            "Guru Meditation: #FLUENT.00000002.UNSAFEOP"
        )

    left = _eval_ast(node.left)
    right = _eval_ast(node.comparators[0])

    # Map AST operator to our string representation
    op_map = {
        ast.Eq: "=",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
    }
    op_str = op_map[type(op)]

    # Build Comparison using the expression operators
    if isinstance(left, (ColumnRef, TermRef)):
        if op_str == "=":
            return left == right
        elif op_str == "!=":
            return left != right
        elif op_str == "<":
            return left < right
        elif op_str == "<=":
            return left <= right
        elif op_str == ">":
            return left > right
        elif op_str == ">=":
            return left >= right

    raise FluentParseError(f"Left side of comparison must be col() or term(), got {type(left).__name__}")


def _eval_binop(node: ast.BinOp) -> Any:
    """Evaluate a binary operation (& and | for logical expressions)."""
    left = _eval_ast(node.left)
    right = _eval_ast(node.right)

    if isinstance(node.op, ast.BitAnd):  # &
        if isinstance(left, Comparison) and isinstance(right, Comparison):
            return left & right
        raise FluentParseError("& operator requires Comparison operands")

    elif isinstance(node.op, ast.BitOr):  # |
        if isinstance(left, Comparison) and isinstance(right, Comparison):
            return left | right
        raise FluentParseError("| operator requires Comparison operands")

    else:
        raise UnsafeOperationError(
            f"Binary operator '{type(node.op).__name__}' not allowed\n"
            "Guru Meditation: #FLUENT.00000002.UNSAFEOP"
        )


def _eval_unaryop(node: ast.UnaryOp) -> Any:
    """Evaluate a unary operation (~ for NOT)."""
    operand = _eval_ast(node.operand)

    if isinstance(node.op, ast.Invert):  # ~
        if isinstance(operand, Comparison):
            return ~operand
        raise FluentParseError("~ operator requires Comparison operand")

    else:
        raise UnsafeOperationError(
            f"Unary operator '{type(node.op).__name__}' not allowed\n"
            "Guru Meditation: #FLUENT.00000002.UNSAFEOP"
        )
