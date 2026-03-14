# DQL Query Language

DQL (Domain Query Language) is the text-based query syntax for the [Bases feature store](./bases.md). It provides a safe, sandboxed expression language that compiles to SQL via SQLGlot.

## Syntax

DQL expressions use a fluent Python-like syntax that is parsed via AST walking (never `eval`):

```
Base("events").where(col("age") > 30).limit(10)
Base("users").where(col("status").isin("active", "pending")).select("name", "email")
Base("metrics").where(term("BFO:temporal_region") >= "2026-01-01").order_by("timestamp", desc=True)
```

## Operators

### Column References

`col("name")` creates a column reference for filtering and selection:

```
col("age") > 30
col("status") == "active"
col("name").like("John%")
col("deleted_at").is_null()
col("role").isin("admin", "editor")
```

### Term References

`term("IRI")` creates an ontology-grounded reference that resolves to a column via the base's `@context`:

```
term("BFO:material_entity") == "ENT-12345"
term("BFO:temporal_region") >= "2026-01-01"
```

### Comparison Operators

| Operator | DQL | SQL |
|----------|-----|-----|
| Equal | `==` | `=` |
| Not equal | `!=` | `!=` |
| Less than | `<` | `<` |
| Less or equal | `<=` | `<=` |
| Greater than | `>` | `>` |
| Greater or equal | `>=` | `>=` |

### Logical Operators

Predicates can be combined with bitwise operators:

```
(col("age") > 30) & (col("status") == "active")   # AND
(col("role") == "admin") | (col("role") == "editor")  # OR
~(col("deleted_at").is_null())                       # NOT
```

Multiple `.where()` calls are combined with AND.

## Methods

| Method | Purpose | Example |
|--------|---------|---------|
| `.where(pred)` | Add filter predicate | `.where(col("x") > 1)` |
| `.select(*cols)` | Select specific columns | `.select("name", "email")` |
| `.order_by(col, desc=)` | Sort results | `.order_by("created_at", desc=True)` |
| `.limit(n)` | Limit result count | `.limit(100)` |
| `.as_of(ts)` | Time-travel (historical) | `.as_of("2026-01-01T00:00:00Z")` |
| `.scan()` | Execute query | `await query.scan()` |

## Safety Model

DQL is parsed using Python's `ast` module with strict whitelisting. Only allowed names (`Base`, `col`, `term`, `True`, `False`, `None`), methods, and operators are permitted. Any unrecognized AST node triggers a fail-fast error:

```
#FLUENT.00000001.BADAST - Unsupported AST node
#FLUENT.00000002.UNSAFEOP - Unsafe operation attempted
```

This prevents arbitrary code execution while supporting expressive queries.

## Compilation

The `FluentCompiler` translates DQL expressions to PostgreSQL-compatible SQL using SQLGlot:

```python
query = Base("events").where(col("age") > 30).limit(10)
sql = query.to_sql()
# SELECT * FROM events WHERE age > 30 LIMIT 10
```

Term references are resolved through the base's `@context` dictionary, mapping ontology IRIs to physical column names.

## MCP Usage

DQL queries are passed as strings to the `bases_query` MCP tool:

```bash
uv run gaius-cli --cmd '/bases query events where(col("age") > 30).limit(10)'
```

The parser validates the expression before compilation, ensuring that only safe operations reach the database.
