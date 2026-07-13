# Boolean Spec To SQLite Integer Mapping Is Undocumented

- Severity: `low`
- Status: `resolved`
- Found: `2026-05-25`

## Summary

Several specs use `boolean`, while the SQLite DDL represents those values as `INTEGER` with `CHECK (... IN (0, 1))`.

## Examples

| Spec Column | DDL Column |
|-------------|------------|
| `docs/plan/sql/execution/execution_reports.md` `reduce_only boolean` | `sql/ddl/execution/tables/execution_reports.sql` `reduce_only INTEGER ... CHECK (reduce_only IN (0, 1))` |
| `docs/plan/sql/execution/order_requests.md` `reduce_only boolean` | `sql/ddl/execution/tables/order_requests.sql` `reduce_only INTEGER ... CHECK (reduce_only IN (0, 1))` |
| `docs/plan/sql/risk/risk_checks.md` `allowed boolean` | `sql/ddl/risk/tables/risk_checks.sql` `allowed INTEGER ... CHECK (allowed IN (0, 1))` |
| `docs/plan/sql/application/strategy_lifecycle_runs.md` `promoted boolean` | `sql/ddl/application/tables/strategy_lifecycle_runs.sql` `promoted INTEGER CHECK (promoted IN (0, 1))` |

## Impact

The generated SQL is likely valid for SQLite, but the representation is implicit. Future agents may treat the type mismatch as a bug or generate inconsistent boolean storage.

## Suggested Fix

Document the mapping in `sql/README.md` or in the relevant SQL plan documents:

```text
SQLite boolean columns are stored as INTEGER values constrained to 0 or 1.
```

## Resolution

`sql/README.md` now documents that plan-level `boolean` columns are stored as SQLite `INTEGER` values constrained to `0` or `1`.
