"""DQL (Dataview Query Language) parser and compiler.

A minimal Dataview-style query language for the Bases feature store.

Syntax:
    WHERE <expression>           - Filter rows
    ORDER BY <col> [ASC|DESC]   - Sort results
    LIMIT <n>                   - Limit rows returned
    AS OF "<timestamp>"         - Time-travel (historical bases only)
    GROUP BY <col>              - Group rows

Expression operators:
    = != < <= > >=              - Comparison
    AND OR NOT                  - Logical
    LIKE                        - Pattern matching
    IN                          - Set membership

Example:
    >>> query = parse_dql("WHERE age > 30 AND status = 'active' ORDER BY created_at DESC LIMIT 100")
    >>> print(query.where.expression)
"""

from gaius.bases.dql.parser import (
    parse_dql,
    DQLQuery,
    WhereClause,
    OrderClause,
    OrderSpec,
    LimitClause,
    AsOfClause,
    GroupClause,
)
from gaius.bases.dql.ast import (
    Expression,
    BinaryOp,
    UnaryOp,
    Identifier,
    Literal,
)

__all__ = [
    # Parser
    "parse_dql",
    "DQLQuery",
    "WhereClause",
    "OrderClause",
    "OrderSpec",
    "LimitClause",
    "AsOfClause",
    "GroupClause",
    # AST
    "Expression",
    "BinaryOp",
    "UnaryOp",
    "Identifier",
    "Literal",
]
