"""DQL Parser - parse tokens into AST.

Grammar (EBNF-ish):
    query       ::= clause*
    clause      ::= where_clause | order_clause | limit_clause | as_of_clause | group_clause
    where_clause ::= "WHERE" expression
    order_clause ::= "ORDER" "BY" order_spec ("," order_spec)*
    order_spec  ::= identifier ("ASC" | "DESC")?
    limit_clause ::= "LIMIT" integer
    as_of_clause ::= "AS" "OF" timestamp_literal
    group_clause ::= "GROUP" "BY" identifier ("," identifier)*

    expression  ::= and_expr
    and_expr    ::= or_expr ("AND" or_expr)*
    or_expr     ::= not_expr ("OR" not_expr)*
    not_expr    ::= "NOT"? comparison
    comparison  ::= term (comp_op term)?
    comp_op     ::= "=" | "!=" | "<" | "<=" | ">" | ">=" | "LIKE" | "IN"
    term        ::= identifier | literal | "(" expression ")" | "(" literal_list ")"
    identifier  ::= [a-zA-Z_][a-zA-Z0-9_]*
    literal     ::= string_literal | number_literal | boolean_literal | null_literal
"""

from dataclasses import dataclass, field
from typing import Any, Literal as TypingLiteral

from gaius.bases.dql.lexer import DQLLexer, Token, TokenType, DQLLexerError
from gaius.bases.dql.ast import (
    Expression,
    BinaryOp,
    UnaryOp,
    Identifier,
    Literal,
    ListLiteral,
)


@dataclass
class WhereClause:
    """WHERE clause with filter expression."""

    expression: Expression


@dataclass
class OrderSpec:
    """Single ORDER BY specification."""

    column: str
    direction: TypingLiteral["ASC", "DESC"] = "ASC"


@dataclass
class OrderClause:
    """ORDER BY clause with sort specifications."""

    specs: list[OrderSpec]


@dataclass
class LimitClause:
    """LIMIT clause."""

    count: int


@dataclass
class AsOfClause:
    """AS OF clause for time-travel queries."""

    timestamp: str  # ISO 8601


@dataclass
class GroupClause:
    """GROUP BY clause."""

    columns: list[str]


@dataclass
class DQLQuery:
    """Parsed DQL query."""

    where: WhereClause | None = None
    order_by: OrderClause | None = None
    limit: LimitClause | None = None
    as_of: AsOfClause | None = None
    group_by: GroupClause | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {}

        if self.where:
            result["where"] = _expression_to_dict(self.where.expression)

        if self.order_by:
            result["order_by"] = [
                {"column": spec.column, "direction": spec.direction}
                for spec in self.order_by.specs
            ]

        if self.limit:
            result["limit"] = self.limit.count

        if self.as_of:
            result["as_of"] = self.as_of.timestamp

        if self.group_by:
            result["group_by"] = self.group_by.columns

        return result


def _expression_to_dict(expr: Expression) -> dict[str, Any]:
    """Convert expression AST to dictionary."""
    if isinstance(expr, BinaryOp):
        return {
            "type": "binary",
            "op": expr.op,
            "left": _expression_to_dict(expr.left),
            "right": _expression_to_dict(expr.right),
        }
    elif isinstance(expr, UnaryOp):
        return {
            "type": "unary",
            "op": expr.op,
            "operand": _expression_to_dict(expr.operand),
        }
    elif isinstance(expr, Identifier):
        return {"type": "identifier", "name": expr.name}
    elif isinstance(expr, Literal):
        return {"type": "literal", "value": expr.value, "literal_type": expr.type}
    elif isinstance(expr, ListLiteral):
        return {
            "type": "list",
            "values": [_expression_to_dict(v) for v in expr.values],
        }
    else:
        return {"type": "unknown", "repr": repr(expr)}


class DQLParser:
    """Parse DQL tokens into AST."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> DQLQuery:
        """Parse tokens into DQLQuery."""
        query = DQLQuery()

        while not self._at_end():
            if self._check(TokenType.WHERE):
                if query.where is not None:
                    raise DQLParseError("Duplicate WHERE clause")
                query.where = self._parse_where()
            elif self._check(TokenType.ORDER):
                if query.order_by is not None:
                    raise DQLParseError("Duplicate ORDER BY clause")
                query.order_by = self._parse_order()
            elif self._check(TokenType.LIMIT):
                if query.limit is not None:
                    raise DQLParseError("Duplicate LIMIT clause")
                query.limit = self._parse_limit()
            elif self._check(TokenType.AS):
                if query.as_of is not None:
                    raise DQLParseError("Duplicate AS OF clause")
                query.as_of = self._parse_as_of()
            elif self._check(TokenType.GROUP):
                if query.group_by is not None:
                    raise DQLParseError("Duplicate GROUP BY clause")
                query.group_by = self._parse_group()
            else:
                raise DQLParseError(f"Unexpected token: {self._current()}")

        return query

    def _parse_where(self) -> WhereClause:
        """Parse WHERE clause."""
        self._advance()  # Consume WHERE
        expr = self._parse_expression()
        return WhereClause(expression=expr)

    def _parse_expression(self) -> Expression:
        """Parse expression (entry point for expression parsing)."""
        return self._parse_or()

    def _parse_or(self) -> Expression:
        """Parse OR expressions."""
        left = self._parse_and()
        while self._check(TokenType.OR):
            self._advance()
            right = self._parse_and()
            left = BinaryOp(left, "OR", right)
        return left

    def _parse_and(self) -> Expression:
        """Parse AND expressions."""
        left = self._parse_not()
        while self._check(TokenType.AND):
            self._advance()
            right = self._parse_not()
            left = BinaryOp(left, "AND", right)
        return left

    def _parse_not(self) -> Expression:
        """Parse NOT expressions."""
        if self._check(TokenType.NOT):
            self._advance()
            return UnaryOp("NOT", self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> Expression:
        """Parse comparison expressions."""
        left = self._parse_term()

        op_map = {
            TokenType.EQ: "=",
            TokenType.NE: "!=",
            TokenType.LT: "<",
            TokenType.LE: "<=",
            TokenType.GT: ">",
            TokenType.GE: ">=",
            TokenType.LIKE: "LIKE",
            TokenType.IN: "IN",
        }

        for tok_type, op_str in op_map.items():
            if self._check(tok_type):
                self._advance()
                if op_str == "IN":
                    # IN expects a list
                    right = self._parse_list()
                else:
                    right = self._parse_term()
                return BinaryOp(left, op_str, right)

        return left

    def _parse_list(self) -> ListLiteral:
        """Parse a list of literals for IN operator."""
        self._expect(TokenType.LPAREN)
        values: list[Literal] = []

        while not self._check(TokenType.RPAREN):
            if values:
                self._expect(TokenType.COMMA)

            token = self._current()
            if token.type == TokenType.STRING:
                self._advance()
                values.append(Literal(token.value, "string"))
            elif token.type == TokenType.NUMBER:
                self._advance()
                values.append(Literal(token.value, "number"))
            elif token.type == TokenType.BOOLEAN:
                self._advance()
                values.append(Literal(token.value, "boolean"))
            elif token.type == TokenType.NULL:
                self._advance()
                values.append(Literal(None, "null"))
            elif token.type == TokenType.TIMESTAMP:
                self._advance()
                values.append(Literal(token.value, "timestamp"))
            else:
                raise DQLParseError(f"Expected literal in list, got {token}")

        self._expect(TokenType.RPAREN)
        return ListLiteral(tuple(values))

    def _parse_term(self) -> Expression:
        """Parse a term (identifier, literal, or parenthesized expression)."""
        token = self._current()

        if token.type == TokenType.IDENTIFIER:
            self._advance()
            return Identifier(token.value)
        elif token.type == TokenType.STRING:
            self._advance()
            return Literal(token.value, "string")
        elif token.type == TokenType.NUMBER:
            self._advance()
            return Literal(token.value, "number")
        elif token.type == TokenType.BOOLEAN:
            self._advance()
            return Literal(token.value, "boolean")
        elif token.type == TokenType.NULL:
            self._advance()
            return Literal(None, "null")
        elif token.type == TokenType.TIMESTAMP:
            self._advance()
            return Literal(token.value, "timestamp")
        elif token.type == TokenType.LPAREN:
            self._advance()
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN)
            return expr
        else:
            raise DQLParseError(f"Expected term, got {token}")

    def _parse_order(self) -> OrderClause:
        """Parse ORDER BY clause."""
        self._advance()  # Consume ORDER
        self._expect(TokenType.BY)

        specs: list[OrderSpec] = []
        while True:
            col = self._expect(TokenType.IDENTIFIER).value
            direction: TypingLiteral["ASC", "DESC"] = "ASC"

            if self._check(TokenType.ASC):
                self._advance()
            elif self._check(TokenType.DESC):
                self._advance()
                direction = "DESC"

            specs.append(OrderSpec(col, direction))

            if not self._check(TokenType.COMMA):
                break
            self._advance()

        return OrderClause(specs)

    def _parse_limit(self) -> LimitClause:
        """Parse LIMIT clause."""
        self._advance()  # Consume LIMIT
        count_token = self._expect(TokenType.NUMBER)

        if not isinstance(count_token.value, int):
            if isinstance(count_token.value, float) and count_token.value.is_integer():
                count = int(count_token.value)
            else:
                raise DQLParseError(f"LIMIT must be an integer, got {count_token.value}")
        else:
            count = count_token.value

        if count < 0:
            raise DQLParseError(f"LIMIT must be non-negative, got {count}")

        return LimitClause(count)

    def _parse_as_of(self) -> AsOfClause:
        """Parse AS OF clause."""
        self._advance()  # Consume AS
        self._expect(TokenType.OF)

        ts = self._current()
        if ts.type not in (TokenType.STRING, TokenType.TIMESTAMP):
            raise DQLParseError(f"Expected timestamp after AS OF, got {ts}")
        self._advance()
        return AsOfClause(ts.value)

    def _parse_group(self) -> GroupClause:
        """Parse GROUP BY clause."""
        self._advance()  # Consume GROUP
        self._expect(TokenType.BY)

        columns: list[str] = []
        while True:
            columns.append(self._expect(TokenType.IDENTIFIER).value)
            if not self._check(TokenType.COMMA):
                break
            self._advance()

        return GroupClause(columns)

    def _current(self) -> Token:
        """Get current token."""
        return self.tokens[self.pos]

    def _at_end(self) -> bool:
        """Check if at end of input."""
        return self._current().type == TokenType.EOF

    def _check(self, typ: TokenType) -> bool:
        """Check if current token is of given type."""
        return not self._at_end() and self._current().type == typ

    def _advance(self) -> Token:
        """Advance to next token and return previous."""
        token = self._current()
        if not self._at_end():
            self.pos += 1
        return token

    def _expect(self, typ: TokenType) -> Token:
        """Expect current token to be of given type, then advance."""
        if not self._check(typ):
            raise DQLParseError(f"Expected {typ.name}, got {self._current()}")
        return self._advance()


class DQLParseError(Exception):
    """Error during DQL parsing."""

    pass


def parse_dql(text: str) -> DQLQuery:
    """Parse a DQL query string.

    Args:
        text: DQL query string

    Returns:
        Parsed DQLQuery object

    Raises:
        DQLLexerError: If tokenization fails
        DQLParseError: If parsing fails

    Example:
        >>> query = parse_dql("WHERE age > 30 ORDER BY name LIMIT 10")
        >>> query.limit.count
        10
    """
    if not text or not text.strip():
        return DQLQuery()

    lexer = DQLLexer(text)
    tokens = lexer.tokenize()
    parser = DQLParser(tokens)
    return parser.parse()
