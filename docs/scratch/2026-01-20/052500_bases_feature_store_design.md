# Bases: Dataview-style Feature Store

A feature store with Obsidian Dataview semantics, exposing data through typed Bases that abstract away the underlying storage backends (PostgreSQL registry, Iceberg offline, Pinot online).

## Conceptual Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MCP Tool Surface                                │
│                                                                              │
│   list_bases()          query_base(name, dql)       get_entity_history()    │
│        │                        │                           │               │
└────────┼────────────────────────┼───────────────────────────┼───────────────┘
         │                        │                           │
         ▼                        ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Base Abstraction                                │
│                                                                              │
│   ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐        │
│   │  Snapshot Base  │    │ Historical Base │    │  Registry Base  │        │
│   │  (latest per    │    │ (event-sourced  │    │   (metadata     │        │
│   │   entity)       │    │  time-travel)   │    │    queries)     │        │
│   └────────┬────────┘    └────────┬────────┘    └────────┬────────┘        │
│            │                      │                      │                  │
│            ▼                      ▼                      ▼                  │
│   ┌─────────────────────────────────────────────────────────────────┐      │
│   │                      DQL Compiler                                │      │
│   │    WHERE → filters   ORDER BY → sort   LIMIT → pagination       │      │
│   │    GROUP BY → agg    AS OF → time-travel                        │      │
│   └─────────────────────────────────────────────────────────────────┘      │
└────────┬────────────────────────┬───────────────────────────┬───────────────┘
         │                        │                           │
         ▼                        ▼                           ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     Pinot       │    │    Iceberg      │    │   PostgreSQL    │
│   (online)      │    │   (offline)     │    │   (registry)    │
│                 │    │                 │    │                 │
│  Low-latency    │    │  Time-travel    │    │  Feature defs   │
│  Latest values  │    │  Event history  │    │  Base metadata  │
│  Many entities  │    │  Point-in-time  │    │  Lineage/ACLs   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 1. PostgreSQL Registry Schema

```sql
-- migrate:up

-- ============================================================================
-- Feature Store Registry Schema
-- ============================================================================
-- Stores feature definitions, base metadata, and Iceberg catalog references.
-- This is the "control plane" - Iceberg/Pinot are the "data plane".

CREATE SCHEMA IF NOT EXISTS bases;
COMMENT ON SCHEMA bases IS 'Feature store registry and Iceberg catalog';

-- ============================================================================
-- Entity Definitions
-- ============================================================================

-- Entity types (user, transaction, device, etc.)
CREATE TABLE bases.entity_types (
    entity_type_id TEXT PRIMARY KEY,           -- e.g., "user", "transaction"
    display_name TEXT NOT NULL,
    description TEXT,
    key_columns JSONB NOT NULL,                -- [{"name": "user_id", "type": "STRING"}]
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE bases.entity_types IS 'Entity types that features can be computed for';

-- ============================================================================
-- Feature Definitions
-- ============================================================================

-- Feature groups (logical groupings like "user_profile", "transaction_risk")
CREATE TABLE bases.feature_groups (
    group_id TEXT PRIMARY KEY,                 -- e.g., "user_profile"
    display_name TEXT NOT NULL,
    description TEXT,
    entity_type_id TEXT REFERENCES bases.entity_types(entity_type_id),
    owner TEXT,                                -- Team/person responsible
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_bases_fg_entity ON bases.feature_groups(entity_type_id);
CREATE INDEX idx_bases_fg_tags ON bases.feature_groups USING GIN(tags);

-- Individual feature definitions
CREATE TABLE bases.features (
    feature_id TEXT PRIMARY KEY,               -- e.g., "user_profile.age"
    group_id TEXT NOT NULL REFERENCES bases.feature_groups(group_id),
    name TEXT NOT NULL,                        -- Short name: "age"
    display_name TEXT,
    description TEXT,

    -- Type information (Arrow-compatible)
    value_type TEXT NOT NULL,                  -- STRING, INT64, FLOAT64, BOOLEAN, TIMESTAMP, ARRAY<T>, STRUCT<...>
    nullable BOOLEAN DEFAULT true,
    default_value JSONB,                       -- Default if missing

    -- Computation metadata
    transformation TEXT,                       -- SQL/expression to compute
    aggregation_type TEXT,                     -- For time-window features: SUM, AVG, COUNT, etc.
    window_duration INTERVAL,                  -- For time-window features

    -- Lifecycle
    status TEXT DEFAULT 'active',              -- active, deprecated, archived
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(group_id, name)
);

CREATE INDEX idx_bases_features_group ON bases.features(group_id);
CREATE INDEX idx_bases_features_status ON bases.features(status);

-- ============================================================================
-- Base Definitions
-- ============================================================================

-- Base types
CREATE TYPE bases.base_type AS ENUM ('snapshot', 'historical', 'registry');

-- Base definitions (the core abstraction)
CREATE TABLE bases.bases (
    base_id TEXT PRIMARY KEY,                  -- e.g., "user_features"
    display_name TEXT NOT NULL,
    description TEXT,
    base_type bases.base_type NOT NULL,

    -- Schema definition (columns exposed by this base)
    schema JSONB NOT NULL,                     -- [{name, type, nullable, description}]

    -- Source binding
    source_entity_type TEXT REFERENCES bases.entity_types(entity_type_id),
    source_feature_groups TEXT[],              -- Which feature groups to pull from

    -- Physical binding (which backend to query)
    physical_table TEXT,                       -- Iceberg table or Pinot table name
    pinot_table TEXT,                          -- For snapshot bases: Pinot table

    -- Default query parameters
    default_dql TEXT,                          -- Default filter/sort (Dataview-style)
    default_time_range INTERVAL DEFAULT '7 days',  -- For historical bases
    max_time_range INTERVAL DEFAULT '90 days',     -- Guardrail

    -- Access control
    read_acl TEXT[] DEFAULT '{"*"}',           -- Who can read (* = all)

    -- Metadata
    owner TEXT,
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_bases_bases_type ON bases.bases(base_type);
CREATE INDEX idx_bases_bases_entity ON bases.bases(source_entity_type);

-- ============================================================================
-- Iceberg Catalog (minimal - PyIceberg handles most)
-- ============================================================================

-- Track Iceberg tables registered with this feature store
CREATE TABLE bases.iceberg_tables (
    table_id TEXT PRIMARY KEY,                 -- Fully qualified: namespace.table_name
    namespace TEXT NOT NULL,                   -- e.g., "features", "events"
    table_name TEXT NOT NULL,
    location TEXT NOT NULL,                    -- s3://... or file://...

    -- Schema info (cached from Iceberg metadata)
    current_schema_id INTEGER,
    partition_spec JSONB,
    sort_order JSONB,

    -- Stats
    record_count BIGINT,
    file_count INTEGER,
    total_size_bytes BIGINT,

    -- Lifecycle
    last_commit_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(namespace, table_name)
);

CREATE INDEX idx_bases_iceberg_ns ON bases.iceberg_tables(namespace);

-- ============================================================================
-- Lineage
-- ============================================================================

-- Track feature dependencies (for impact analysis)
CREATE TABLE bases.feature_lineage (
    id SERIAL PRIMARY KEY,
    source_feature_id TEXT REFERENCES bases.features(feature_id),
    target_feature_id TEXT REFERENCES bases.features(feature_id),
    relationship TEXT DEFAULT 'derived_from',   -- derived_from, aggregates, transforms
    transformation TEXT,                        -- Expression/SQL
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(source_feature_id, target_feature_id)
);

CREATE INDEX idx_bases_lineage_source ON bases.feature_lineage(source_feature_id);
CREATE INDEX idx_bases_lineage_target ON bases.feature_lineage(target_feature_id);

-- ============================================================================
-- Query Audit Log (for guardrails)
-- ============================================================================

CREATE TABLE bases.query_log (
    id BIGSERIAL PRIMARY KEY,
    base_id TEXT REFERENCES bases.bases(base_id),
    dql_query TEXT NOT NULL,
    compiled_sql TEXT,
    backend TEXT,                              -- postgres, iceberg, pinot
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    duration_ms INTEGER,
    rows_returned INTEGER,
    client_id TEXT,                            -- MCP client identifier
    error TEXT                                 -- NULL if successful
);

CREATE INDEX idx_bases_qlog_base ON bases.query_log(base_id, executed_at DESC);
CREATE INDEX idx_bases_qlog_time ON bases.query_log(executed_at DESC);

-- Prune old logs (keep 30 days)
-- Will be managed by pg_cron

-- migrate:down
DROP SCHEMA IF EXISTS bases CASCADE;
```

## 2. Iceberg Event-Sourced Schema

The Iceberg tables follow an append-only, event-sourced pattern:

```
features_{group}_events
├── entity_id: STRING (partition key)
├── event_time: TIMESTAMP (when the event occurred in the real world)
├── ingestion_time: TIMESTAMP (when we received it)
├── version: INT64 (monotonic within entity)
├── operation: STRING (INSERT, UPDATE, DELETE)
├── {feature_columns...}: Various types
└── _metadata: STRUCT<source, trace_id, ...>
```

### PyIceberg Schema Definition

```python
from pyiceberg.schema import Schema
from pyiceberg.types import (
    NestedField, StringType, TimestampType, LongType,
    DoubleType, BooleanType, StructType, ListType
)

def create_feature_event_schema(
    group_id: str,
    features: list[dict],  # [{name, value_type, nullable}]
) -> Schema:
    """Create Iceberg schema for a feature group's event table."""

    # Core event columns
    fields = [
        NestedField(1, "entity_id", StringType(), required=True),
        NestedField(2, "event_time", TimestampType(), required=True),
        NestedField(3, "ingestion_time", TimestampType(), required=True),
        NestedField(4, "version", LongType(), required=True),
        NestedField(5, "operation", StringType(), required=True),
    ]

    # Feature columns (dynamic based on feature definitions)
    field_id = 100
    for feat in features:
        iceberg_type = _map_type(feat["value_type"])
        fields.append(NestedField(
            field_id,
            feat["name"],
            iceberg_type,
            required=not feat.get("nullable", True),
        ))
        field_id += 1

    # Metadata column (always last)
    fields.append(NestedField(
        999,
        "_metadata",
        StructType(
            NestedField(1000, "source", StringType()),
            NestedField(1001, "trace_id", StringType()),
            NestedField(1002, "batch_id", StringType()),
        ),
        required=False,
    ))

    return Schema(*fields)
```

### Partition Strategy

```python
from pyiceberg.partitioning import PartitionSpec, PartitionField
from pyiceberg.transforms import DayTransform, IdentityTransform

def feature_partition_spec(schema: Schema) -> PartitionSpec:
    """Standard partition spec for feature event tables.

    Partition by:
    - event_time (day) - For time-range pruning
    - entity_id (identity, bucketed) - For entity lookups
    """
    return PartitionSpec(
        PartitionField(
            source_id=2,  # event_time
            field_id=1000,
            transform=DayTransform(),
            name="event_day",
        ),
        # For high-cardinality entity_id, use bucket transform
        # PartitionField(source_id=1, transform=BucketTransform(256), name="entity_bucket")
    )
```

## 3. DQL Parser/Translator

A minimal Dataview-style query language:

```
WHERE age > 30 AND status = "active"
ORDER BY created_at DESC
LIMIT 100
AS OF "2024-01-15T00:00:00Z"
GROUP BY region
```

### Grammar (EBNF-ish)

```
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
term        ::= identifier | literal | "(" expression ")"
identifier  ::= [a-zA-Z_][a-zA-Z0-9_]*
literal     ::= string_literal | number_literal | boolean_literal | null_literal
```

### Python Implementation

```python
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Literal
import re


class TokenType(Enum):
    # Keywords
    WHERE = auto()
    ORDER = auto()
    BY = auto()
    LIMIT = auto()
    AS = auto()
    OF = auto()
    GROUP = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    ASC = auto()
    DESC = auto()
    IN = auto()
    LIKE = auto()

    # Operators
    EQ = auto()      # =
    NE = auto()      # !=
    LT = auto()      # <
    LE = auto()      # <=
    GT = auto()      # >
    GE = auto()      # >=
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    COMMA = auto()   # ,

    # Values
    IDENTIFIER = auto()
    STRING = auto()
    NUMBER = auto()
    BOOLEAN = auto()
    NULL = auto()
    TIMESTAMP = auto()

    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: Any
    position: int


@dataclass
class WhereClause:
    expression: "Expression"


@dataclass
class OrderSpec:
    column: str
    direction: Literal["ASC", "DESC"] = "ASC"


@dataclass
class OrderClause:
    specs: list[OrderSpec]


@dataclass
class LimitClause:
    count: int


@dataclass
class AsOfClause:
    timestamp: str  # ISO 8601


@dataclass
class GroupClause:
    columns: list[str]


@dataclass
class DQLQuery:
    """Parsed DQL query."""
    where: WhereClause | None = None
    order_by: OrderClause | None = None
    limit: LimitClause | None = None
    as_of: AsOfClause | None = None
    group_by: GroupClause | None = None


# Expression AST nodes
@dataclass
class BinaryOp:
    left: "Expression"
    op: str  # AND, OR, =, !=, <, <=, >, >=, LIKE, IN
    right: "Expression"


@dataclass
class UnaryOp:
    op: str  # NOT
    operand: "Expression"


@dataclass
class Identifier:
    name: str


@dataclass
class Literal:
    value: Any
    type: str  # string, number, boolean, null, timestamp


Expression = BinaryOp | UnaryOp | Identifier | Literal


class DQLLexer:
    """Tokenize DQL input."""

    KEYWORDS = {
        "WHERE", "ORDER", "BY", "LIMIT", "AS", "OF", "GROUP",
        "AND", "OR", "NOT", "ASC", "DESC", "IN", "LIKE",
        "TRUE", "FALSE", "NULL",
    }

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        while self.pos < len(self.text):
            self._skip_whitespace()
            if self.pos >= len(self.text):
                break

            # Check operators first
            if self._match_operators():
                continue

            # Check for strings
            if self.text[self.pos] in ('"', "'"):
                self._read_string()
                continue

            # Check for numbers
            if self.text[self.pos].isdigit() or (
                self.text[self.pos] == '-' and
                self.pos + 1 < len(self.text) and
                self.text[self.pos + 1].isdigit()
            ):
                self._read_number()
                continue

            # Check for identifiers/keywords
            if self.text[self.pos].isalpha() or self.text[self.pos] == '_':
                self._read_identifier()
                continue

            raise ValueError(f"Unexpected character at position {self.pos}: {self.text[self.pos]}")

        self.tokens.append(Token(TokenType.EOF, None, self.pos))
        return self.tokens

    def _skip_whitespace(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _match_operators(self) -> bool:
        ops = [
            ("!=", TokenType.NE),
            ("<=", TokenType.LE),
            (">=", TokenType.GE),
            ("=", TokenType.EQ),
            ("<", TokenType.LT),
            (">", TokenType.GT),
            ("(", TokenType.LPAREN),
            (")", TokenType.RPAREN),
            (",", TokenType.COMMA),
        ]
        for op, tok_type in ops:
            if self.text[self.pos:].startswith(op):
                self.tokens.append(Token(tok_type, op, self.pos))
                self.pos += len(op)
                return True
        return False

    def _read_string(self):
        quote = self.text[self.pos]
        start = self.pos
        self.pos += 1
        value = []
        while self.pos < len(self.text) and self.text[self.pos] != quote:
            if self.text[self.pos] == '\\' and self.pos + 1 < len(self.text):
                self.pos += 1
            value.append(self.text[self.pos])
            self.pos += 1
        if self.pos >= len(self.text):
            raise ValueError(f"Unterminated string at position {start}")
        self.pos += 1  # Skip closing quote

        # Check if it looks like a timestamp
        val_str = ''.join(value)
        if re.match(r'^\d{4}-\d{2}-\d{2}', val_str):
            self.tokens.append(Token(TokenType.TIMESTAMP, val_str, start))
        else:
            self.tokens.append(Token(TokenType.STRING, val_str, start))

    def _read_number(self):
        start = self.pos
        if self.text[self.pos] == '-':
            self.pos += 1
        while self.pos < len(self.text) and (self.text[self.pos].isdigit() or self.text[self.pos] == '.'):
            self.pos += 1
        value = self.text[start:self.pos]
        self.tokens.append(Token(TokenType.NUMBER, float(value) if '.' in value else int(value), start))

    def _read_identifier(self):
        start = self.pos
        while self.pos < len(self.text) and (self.text[self.pos].isalnum() or self.text[self.pos] == '_'):
            self.pos += 1
        value = self.text[start:self.pos]
        upper = value.upper()

        if upper in ("TRUE", "FALSE"):
            self.tokens.append(Token(TokenType.BOOLEAN, upper == "TRUE", start))
        elif upper == "NULL":
            self.tokens.append(Token(TokenType.NULL, None, start))
        elif upper in self.KEYWORDS:
            self.tokens.append(Token(TokenType[upper], value, start))
        else:
            self.tokens.append(Token(TokenType.IDENTIFIER, value, start))


class DQLParser:
    """Parse DQL tokens into AST."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> DQLQuery:
        query = DQLQuery()

        while not self._at_end():
            if self._check(TokenType.WHERE):
                query.where = self._parse_where()
            elif self._check(TokenType.ORDER):
                query.order_by = self._parse_order()
            elif self._check(TokenType.LIMIT):
                query.limit = self._parse_limit()
            elif self._check(TokenType.AS):
                query.as_of = self._parse_as_of()
            elif self._check(TokenType.GROUP):
                query.group_by = self._parse_group()
            else:
                raise ValueError(f"Unexpected token: {self._current()}")

        return query

    def _parse_where(self) -> WhereClause:
        self._advance()  # Consume WHERE
        expr = self._parse_expression()
        return WhereClause(expression=expr)

    def _parse_expression(self) -> Expression:
        return self._parse_or()

    def _parse_or(self) -> Expression:
        left = self._parse_and()
        while self._check(TokenType.OR):
            self._advance()
            right = self._parse_and()
            left = BinaryOp(left, "OR", right)
        return left

    def _parse_and(self) -> Expression:
        left = self._parse_not()
        while self._check(TokenType.AND):
            self._advance()
            right = self._parse_not()
            left = BinaryOp(left, "AND", right)
        return left

    def _parse_not(self) -> Expression:
        if self._check(TokenType.NOT):
            self._advance()
            return UnaryOp("NOT", self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> Expression:
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
                right = self._parse_term()
                return BinaryOp(left, op_str, right)

        return left

    def _parse_term(self) -> Expression:
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
            raise ValueError(f"Expected term, got {token}")

    def _parse_order(self) -> OrderClause:
        self._advance()  # Consume ORDER
        self._expect(TokenType.BY)

        specs = []
        while True:
            col = self._expect(TokenType.IDENTIFIER).value
            direction = "ASC"
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
        self._advance()  # Consume LIMIT
        count = self._expect(TokenType.NUMBER).value
        return LimitClause(int(count))

    def _parse_as_of(self) -> AsOfClause:
        self._advance()  # Consume AS
        self._expect(TokenType.OF)
        ts = self._current()
        if ts.type not in (TokenType.STRING, TokenType.TIMESTAMP):
            raise ValueError(f"Expected timestamp after AS OF, got {ts}")
        self._advance()
        return AsOfClause(ts.value)

    def _parse_group(self) -> GroupClause:
        self._advance()  # Consume GROUP
        self._expect(TokenType.BY)

        columns = []
        while True:
            columns.append(self._expect(TokenType.IDENTIFIER).value)
            if not self._check(TokenType.COMMA):
                break
            self._advance()

        return GroupClause(columns)

    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _at_end(self) -> bool:
        return self._current().type == TokenType.EOF

    def _check(self, typ: TokenType) -> bool:
        return not self._at_end() and self._current().type == typ

    def _advance(self) -> Token:
        token = self._current()
        if not self._at_end():
            self.pos += 1
        return token

    def _expect(self, typ: TokenType) -> Token:
        if not self._check(typ):
            raise ValueError(f"Expected {typ}, got {self._current()}")
        return self._advance()


def parse_dql(text: str) -> DQLQuery:
    """Parse a DQL query string."""
    lexer = DQLLexer(text)
    tokens = lexer.tokenize()
    parser = DQLParser(tokens)
    return parser.parse()
```

### Backend Compilers

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CompiledQuery:
    """Result of compiling DQL to backend-specific query."""
    sql: str
    parameters: dict[str, Any]
    backend: str  # postgres, iceberg, pinot


class DQLCompiler(ABC):
    """Base class for backend-specific DQL compilers."""

    @abstractmethod
    def compile(self, query: DQLQuery, base: "BaseDefinition") -> CompiledQuery:
        """Compile DQL to backend-specific query."""
        pass

    def _compile_expression(self, expr: Expression) -> tuple[str, dict]:
        """Compile expression to SQL fragment and parameters."""
        if isinstance(expr, BinaryOp):
            left_sql, left_params = self._compile_expression(expr.left)
            right_sql, right_params = self._compile_expression(expr.right)

            op = expr.op
            if op in ("AND", "OR"):
                return f"({left_sql} {op} {right_sql})", {**left_params, **right_params}
            else:
                return f"{left_sql} {op} {right_sql}", {**left_params, **right_params}

        elif isinstance(expr, UnaryOp):
            operand_sql, operand_params = self._compile_expression(expr.operand)
            return f"NOT ({operand_sql})", operand_params

        elif isinstance(expr, Identifier):
            # Quote identifier to prevent injection
            return f'"{expr.name}"', {}

        elif isinstance(expr, Literal):
            param_name = f"p{id(expr)}"
            return f":{param_name}", {param_name: expr.value}

        raise ValueError(f"Unknown expression type: {type(expr)}")


class PostgresCompiler(DQLCompiler):
    """Compile DQL to PostgreSQL queries (for registry/metadata)."""

    def compile(self, query: DQLQuery, base: "BaseDefinition") -> CompiledQuery:
        parts = [f"SELECT * FROM {base.physical_table}"]
        params = {}

        if query.where:
            where_sql, where_params = self._compile_expression(query.where.expression)
            parts.append(f"WHERE {where_sql}")
            params.update(where_params)

        if query.order_by:
            order_parts = [
                f'"{spec.column}" {spec.direction}'
                for spec in query.order_by.specs
            ]
            parts.append(f"ORDER BY {', '.join(order_parts)}")

        if query.limit:
            parts.append(f"LIMIT {query.limit.count}")

        return CompiledQuery(
            sql=" ".join(parts),
            parameters=params,
            backend="postgres",
        )


class IcebergCompiler(DQLCompiler):
    """Compile DQL to Iceberg SQL (for historical queries with time-travel)."""

    def compile(self, query: DQLQuery, base: "BaseDefinition") -> CompiledQuery:
        # For historical bases, we need to handle AS OF
        table = base.physical_table

        # Build SELECT with optional time-travel
        if query.as_of:
            # PyIceberg time-travel syntax
            parts = [f"SELECT * FROM {table} FOR SYSTEM_TIME AS OF TIMESTAMP '{query.as_of.timestamp}'"]
        else:
            parts = [f"SELECT * FROM {table}"]

        params = {}

        # Always add time range filter for historical bases (guardrail)
        time_filter = self._build_time_filter(query, base)

        if query.where:
            where_sql, where_params = self._compile_expression(query.where.expression)
            if time_filter:
                parts.append(f"WHERE ({where_sql}) AND {time_filter}")
            else:
                parts.append(f"WHERE {where_sql}")
            params.update(where_params)
        elif time_filter:
            parts.append(f"WHERE {time_filter}")

        if query.order_by:
            order_parts = [
                f'"{spec.column}" {spec.direction}'
                for spec in query.order_by.specs
            ]
            parts.append(f"ORDER BY {', '.join(order_parts)}")

        if query.limit:
            parts.append(f"LIMIT {query.limit.count}")

        return CompiledQuery(
            sql=" ".join(parts),
            parameters=params,
            backend="iceberg",
        )

    def _build_time_filter(self, query: DQLQuery, base: "BaseDefinition") -> str:
        """Build time range filter for guardrails."""
        if query.as_of:
            # AS OF overrides default time range
            return ""

        # Default: last N days
        default_range = base.default_time_range or "7 days"
        return f"event_time >= NOW() - INTERVAL '{default_range}'"


class PinotCompiler(DQLCompiler):
    """Compile DQL to Pinot SQL (for snapshot/online queries)."""

    def compile(self, query: DQLQuery, base: "BaseDefinition") -> CompiledQuery:
        parts = [f"SELECT * FROM {base.pinot_table}"]
        params = {}

        if query.where:
            where_sql, where_params = self._compile_expression(query.where.expression)
            parts.append(f"WHERE {where_sql}")
            params.update(where_params)

        if query.order_by:
            order_parts = [
                f'"{spec.column}" {spec.direction}'
                for spec in query.order_by.specs
            ]
            parts.append(f"ORDER BY {', '.join(order_parts)}")

        if query.limit:
            parts.append(f"LIMIT {query.limit.count}")
        else:
            # Pinot default limit for safety
            parts.append("LIMIT 1000")

        return CompiledQuery(
            sql=" ".join(parts),
            parameters=params,
            backend="pinot",
        )
```

## 4. MCP Tool Surface

```python
from dataclasses import dataclass
from typing import Any, Literal
from datetime import datetime


# ============================================================================
# Response Types
# ============================================================================

@dataclass
class ColumnSchema:
    """Schema for a single column in query results."""
    name: str
    type: str  # STRING, INT64, FLOAT64, BOOLEAN, TIMESTAMP, ARRAY, STRUCT
    nullable: bool = True
    description: str | None = None


@dataclass
class QueryResult:
    """Structured result from query_base."""
    columns: list[ColumnSchema]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool  # True if LIMIT applied
    query_time_ms: int
    backend: str  # postgres, iceberg, pinot


@dataclass
class BaseInfo:
    """Metadata about a Base."""
    name: str
    display_name: str
    description: str | None
    base_type: Literal["snapshot", "historical", "registry"]
    schema: list[ColumnSchema]
    entity_type: str | None
    feature_groups: list[str]
    default_dql: str | None
    tags: list[str]


@dataclass
class EntityHistoryResult:
    """Result from get_entity_history."""
    entity_id: str
    entity_type: str
    events: list[dict[str, Any]]  # Ordered by event_time DESC
    total_events: int
    time_range: tuple[datetime, datetime]


# ============================================================================
# MCP Tool Definitions
# ============================================================================

async def list_bases(
    base_type: Literal["snapshot", "historical", "registry", "all"] = "all",
    tags: list[str] | None = None,
) -> list[BaseInfo]:
    """List available Bases with their metadata.

    Args:
        base_type: Filter by base type. "all" returns all types.
        tags: Filter by tags (matches if base has ANY of the tags).

    Returns:
        List of BaseInfo objects describing available bases.

    Example:
        >>> bases = await list_bases(base_type="snapshot", tags=["user"])
        >>> for base in bases:
        ...     print(f"{base.name}: {base.description}")
    """
    pass


async def query_base(
    base_name: str,
    dql: str | None = None,
    options: dict[str, Any] | None = None,
) -> QueryResult:
    """Execute a DQL query against a Base.

    Args:
        base_name: Name of the Base to query.
        dql: Dataview-style query (WHERE, ORDER BY, LIMIT, AS OF, GROUP BY).
             If None, uses the base's default_dql.
        options: Additional options:
            - timeout_ms: Query timeout (default 30000)
            - max_rows: Override LIMIT (max 10000)
            - include_metadata: Include _metadata column (default False)

    Returns:
        QueryResult with columns, rows, and metadata.

    Example:
        >>> result = await query_base(
        ...     "user_features",
        ...     "WHERE age > 25 AND region = 'US' ORDER BY created_at DESC LIMIT 100"
        ... )
        >>> for row in result.rows:
        ...     print(f"{row['user_id']}: {row['age']}")

    DQL Syntax:
        WHERE <expression>      - Filter rows
        ORDER BY <col> [ASC|DESC] - Sort results
        LIMIT <n>               - Limit rows returned
        AS OF "<timestamp>"     - Time-travel (historical bases only)
        GROUP BY <col>          - Group rows (with implicit aggregation)

    Expression Operators:
        = != < <= > >=          - Comparison
        AND OR NOT              - Logical
        LIKE                    - Pattern matching
        IN                      - Set membership
    """
    pass


async def get_entity_history(
    entity_id: str,
    entity_type: str | None = None,
    base_name: str | None = None,
    options: dict[str, Any] | None = None,
) -> EntityHistoryResult:
    """Get event-sourced history for an entity.

    Convenience method that fetches all events for a specific entity
    from a historical Base.

    Args:
        entity_id: The entity identifier.
        entity_type: Entity type (required if base_name not provided).
        base_name: Specific historical base to query. If None, uses
                   the default historical base for the entity type.
        options: Additional options:
            - time_range: Tuple of (start, end) datetime
            - max_events: Maximum events to return (default 1000)
            - include_deleted: Include DELETE operations (default False)

    Returns:
        EntityHistoryResult with event history.

    Example:
        >>> history = await get_entity_history("user_123", entity_type="user")
        >>> for event in history.events:
        ...     print(f"{event['event_time']}: {event['operation']}")
    """
    pass
```

## 5. Guardrails Implementation

```python
from dataclasses import dataclass
from datetime import timedelta
from typing import Any


@dataclass
class QueryGuardrails:
    """Enforced limits on query execution."""

    # Time range limits (for historical bases)
    default_time_range: timedelta = timedelta(days=7)
    max_time_range: timedelta = timedelta(days=90)
    require_time_range: bool = True

    # Result limits
    default_limit: int = 1000
    max_limit: int = 10000

    # Timeout
    default_timeout_ms: int = 30000
    max_timeout_ms: int = 120000

    # Read-only enforcement
    read_only: bool = True


class GuardrailEnforcer:
    """Enforce guardrails on DQL queries."""

    def __init__(self, guardrails: QueryGuardrails):
        self.guardrails = guardrails

    def enforce(self, query: DQLQuery, base: "BaseDefinition") -> DQLQuery:
        """Apply guardrails to a parsed query.

        May modify the query to add missing constraints.
        Raises ValueError if guardrails are violated.
        """
        # Check read-only
        if self.guardrails.read_only:
            # DQL is inherently read-only by design
            pass

        # Enforce LIMIT
        if query.limit is None:
            query.limit = LimitClause(self.guardrails.default_limit)
        elif query.limit.count > self.guardrails.max_limit:
            raise ValueError(
                f"LIMIT {query.limit.count} exceeds maximum {self.guardrails.max_limit}"
            )

        # Enforce time range for historical bases
        if base.base_type == "historical" and self.guardrails.require_time_range:
            if query.as_of is None and not self._has_time_filter(query):
                # Add default time filter
                # This is handled by the compiler, but we validate here
                pass

        return query

    def _has_time_filter(self, query: DQLQuery) -> bool:
        """Check if query has an explicit time filter."""
        if query.where is None:
            return False
        return self._expression_has_time_filter(query.where.expression)

    def _expression_has_time_filter(self, expr: Expression) -> bool:
        """Recursively check for time column references."""
        if isinstance(expr, BinaryOp):
            return (
                self._expression_has_time_filter(expr.left) or
                self._expression_has_time_filter(expr.right)
            )
        elif isinstance(expr, UnaryOp):
            return self._expression_has_time_filter(expr.operand)
        elif isinstance(expr, Identifier):
            return expr.name in ("event_time", "ingestion_time", "created_at", "updated_at")
        return False
```

## 6. Code Structure

```
src/gaius/bases/
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── base.py           # BaseDefinition, BaseType
│   ├── feature.py        # Feature, FeatureGroup, EntityType
│   ├── schema.py         # ColumnSchema, QueryResult
│   └── lineage.py        # FeatureLineage
├── dql/
│   ├── __init__.py
│   ├── lexer.py          # DQLLexer
│   ├── parser.py         # DQLParser, AST nodes
│   ├── compiler.py       # DQLCompiler base
│   ├── postgres.py       # PostgresCompiler
│   ├── iceberg.py        # IcebergCompiler
│   └── pinot.py          # PinotCompiler
├── registry/
│   ├── __init__.py
│   ├── client.py         # Registry client (Postgres)
│   └── cache.py          # In-memory cache for base definitions
├── execution/
│   ├── __init__.py
│   ├── executor.py       # Query executor (routes to backends)
│   ├── guardrails.py     # Guardrail enforcement
│   └── audit.py          # Query audit logging
├── backends/
│   ├── __init__.py
│   ├── postgres.py       # PostgreSQL backend
│   ├── iceberg.py        # Iceberg backend (PyIceberg)
│   └── pinot.py          # Pinot backend
├── mcp/
│   ├── __init__.py
│   └── tools.py          # MCP tool implementations
└── service.py            # BasesService (Engine-First pattern)
```

## 7. Integration with Existing Systems

### Engine-First Pattern

```python
class BasesService(BaseDaemon):
    """Bases service for Engine-First architecture."""

    @property
    def name(self) -> str:
        return "bases"

    @property
    def criticality(self) -> DaemonCriticality:
        return DaemonCriticality.OPTIONAL

    def __init__(self, config: BasesConfig, db_pool: Any = None):
        self.config = config
        self._db_pool = db_pool
        self._registry: RegistryClient | None = None
        self._executors: dict[str, Backend] = {}

    async def start(self) -> None:
        # Initialize registry client
        self._registry = RegistryClient(self._db_pool)

        # Initialize backends
        self._executors["postgres"] = PostgresBackend(self._db_pool)

        if self.config.iceberg_enabled:
            self._executors["iceberg"] = IcebergBackend(
                catalog_uri=self.config.iceberg_catalog_uri
            )

        if self.config.pinot_enabled:
            self._executors["pinot"] = PinotBackend(
                broker_url=self.config.pinot_broker_url
            )

    async def list_bases(self, base_type: str = "all", tags: list[str] | None = None) -> list[BaseInfo]:
        """List available bases."""
        return await self._registry.list_bases(base_type, tags)

    async def query_base(self, base_name: str, dql: str | None, options: dict | None) -> QueryResult:
        """Execute DQL query against a base."""
        # Get base definition
        base = await self._registry.get_base(base_name)

        # Parse DQL
        query = parse_dql(dql or base.default_dql or "")

        # Apply guardrails
        guardrails = GuardrailEnforcer(self.config.guardrails)
        query = guardrails.enforce(query, base)

        # Select compiler and backend
        backend_name = self._select_backend(base)
        compiler = self._get_compiler(backend_name)

        # Compile and execute
        compiled = compiler.compile(query, base)
        executor = self._executors[backend_name]

        result = await executor.execute(compiled)

        # Audit log
        await self._log_query(base_name, dql, compiled, result)

        return result
```

### gRPC Servicer Integration

Add to `gaius_servicer.py`:

```python
async def BasesListBases(self, request, context) -> BasesListBasesResponse:
    """List available bases."""
    bases_service = self._services.bases_service
    if not bases_service:
        # Fail-fast
        context.abort(grpc.StatusCode.UNAVAILABLE, "BasesService not available")

    bases = await bases_service.list_bases(
        base_type=request.base_type or "all",
        tags=list(request.tags) if request.tags else None,
    )

    return BasesListBasesResponse(bases=[b.to_proto() for b in bases])


async def BasesQueryBase(self, request, context) -> BasesQueryBaseResponse:
    """Execute DQL query."""
    bases_service = self._services.bases_service
    if not bases_service:
        context.abort(grpc.StatusCode.UNAVAILABLE, "BasesService not available")

    result = await bases_service.query_base(
        base_name=request.base_name,
        dql=request.dql or None,
        options=json.loads(request.options_json) if request.options_json else None,
    )

    return BasesQueryBaseResponse(
        columns=[c.to_proto() for c in result.columns],
        rows_json=json.dumps(result.rows),
        row_count=result.row_count,
        truncated=result.truncated,
        query_time_ms=result.query_time_ms,
        backend=result.backend,
    )
```

## 8. Example Usage

```python
# From MCP client perspective:

# List snapshot bases for user features
bases = await mcp.list_bases(base_type="snapshot", tags=["user"])
# [BaseInfo(name="user_features", base_type="snapshot", ...)]

# Query latest user features
result = await mcp.query_base(
    "user_features",
    "WHERE region = 'US' AND age > 25 ORDER BY signup_date DESC LIMIT 100"
)
# QueryResult(columns=[...], rows=[{user_id: "u1", age: 30, ...}, ...])

# Get historical feature evolution for a user
history = await mcp.get_entity_history(
    entity_id="user_123",
    entity_type="user",
    options={"time_range": ("2024-01-01", "2024-01-31")}
)
# EntityHistoryResult(entity_id="user_123", events=[...])

# Time-travel query
result = await mcp.query_base(
    "user_features_history",
    'WHERE user_id = "user_123" AS OF "2024-01-15T00:00:00Z"'
)
# Returns features as they were on Jan 15
```
