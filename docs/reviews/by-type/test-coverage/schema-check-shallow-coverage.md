# Schema Check Is Too Shallow

- Severity: `medium`
- Status: `resolved`
- Found: `2026-05-25`

## Summary

`sql/tests/persistence_schema_checks.sql` currently checks table names and a subset of index names. It does not validate the schema details that the `docs/plan/sql` files specify.

## Missing Coverage

- Column presence and order
- Column type affinity
- `NOT NULL` requirements
- Defaults such as `use_yn DEFAULT 'Y'`
- `CHECK` constraints, including `use_yn IN ('Y', 'N')`
- Foreign keys
- Unique constraints
- Composite primary keys
- Index column composition

## Impact

A DDL file can drift away from the plan while the current schema check still returns expected table and index names.

## Suggested Fix

Add schema assertions using SQLite metadata:

```sql
PRAGMA table_info(table_name);
PRAGMA foreign_key_list(table_name);
PRAGMA index_list(table_name);
PRAGMA index_info(index_name);
```

For constraints that SQLite metadata does not expose cleanly, assert selected fragments from `sqlite_master.sql`.

## Resolution

`sql/tests/persistence_schema_checks.sql` now adds violation queries for missing expected tables, missing expected indexes, required common columns, nullable text primary keys, `use_yn` defaults, `use_yn` checks, foreign-key metadata, and index column metadata.
