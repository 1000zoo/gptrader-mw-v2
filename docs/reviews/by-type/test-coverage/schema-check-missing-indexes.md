# Schema Check Omits Generated Indexes

- Severity: `medium`
- Status: `resolved`
- Found: `2026-05-25`

## Summary

`sql/tests/persistence_schema_checks.sql` checks only 33 of the 41 generated indexes.

## Missing Indexes

| Index | File |
|-------|------|
| `idx_research_runs_symbol_timeframe_reg_ymd` | `sql/ddl/application/indexes/research_runs_indexes.sql` |
| `idx_strategy_lifecycle_runs_evaluations` | `sql/ddl/application/indexes/strategy_lifecycle_runs_indexes.sql` |
| `idx_trade_runs_generator_status_reg_ymd` | `sql/ddl/application/indexes/trade_runs_indexes.sql` |
| `idx_execution_reports_position_reg_ymd` | `sql/ddl/execution/indexes/execution_reports_indexes.sql` |
| `idx_order_requests_decision_reg_ymd` | `sql/ddl/execution/indexes/order_requests_indexes.sql` |
| `idx_order_results_exchange_order_reg_ymd` | `sql/ddl/execution/indexes/order_results_indexes.sql` |
| `idx_position_events_symbol_type_reg_ymd` | `sql/ddl/position/indexes/position_events_indexes.sql` |
| `idx_strategy_results_generated_signal` | `sql/ddl/strategy/indexes/strategy_results_indexes.sql` |

## Impact

The generated index files can regress without the schema check showing a difference.

## Suggested Fix

Update `sql/tests/persistence_schema_checks.sql` so every generated index is listed, or replace the static list with a stricter expected-count and expected-name assertion generated from the DDL inventory.

## Resolution

`sql/tests/persistence_schema_checks.sql` now includes all 41 generated index names and reports any expected index missing from `sqlite_master`.
