# SQL DDL Latest Plan

- Source path: `sql/ddl`, `sql/tests`, `sql/seeds`
- Related source path: `src/infrastructure/persistence`
- Status: `done` for current DDL coverage.
- Governs: SQL schema specs, generated DDL organization, and schema checks.

## Current Plan

SQL DDL is organized by domain under `sql/ddl/<domain>` with table, index, and constraint files. It documents persistence coverage beyond the currently implemented repository adapters.

## History

- 2026-05-24: SQL DDL management design. See `history/2026-05-24-sql-ddl-management-design.md`.
- 2026-05-24: SQL DDL implementation plan. See `history/2026-05-24-sql-ddl-management.md`.

## Follow-Up

Keep DDL changes aligned with repository ports and adapter plans. Schema-only changes should still update this latest plan with the reason and migration impact.

