# SQLite Text Primary Keys Allow NULL

- Severity: `important`
- Status: `resolved`
- Found: `2026-05-25`

## Summary

Most single-column ID tables declare primary keys as `TEXT PRIMARY KEY` without an explicit `NOT NULL`.
SQLite does not automatically enforce `NOT NULL` for non-integer primary-key columns in ordinary rowid tables, so these columns can accept `NULL` values.

## Evidence

- Spec example: `strategy_id` is required in `docs/plan/sql/strategy/strategy_definitions.md`.
- DDL example: `sql/ddl/strategy/tables/strategy_definitions.sql` declares `strategy_id TEXT PRIMARY KEY`.
- The same pattern appears across most `*_id TEXT PRIMARY KEY` table DDL files.

## Impact

The SQL can violate the plan requirement that ID columns are required. It also weakens FK integrity and repository assumptions because rows may be inserted with null logical identifiers.

## Suggested Fix

Add explicit `NOT NULL` to every single-column text primary key, for example:

```sql
strategy_id TEXT NOT NULL PRIMARY KEY
```

Composite primary-key columns already declare `NOT NULL` in the reviewed files, but they should remain covered by schema checks.

## Resolution

All single-column `TEXT PRIMARY KEY` declarations now explicitly include `NOT NULL`, and `sql/tests/persistence_schema_checks.sql` reports nullable text primary-key columns.
