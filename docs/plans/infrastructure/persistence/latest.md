# Persistence Infrastructure Latest Plan

- Source path: `src/infrastructure/persistence`
- Module: O
- Status: `done` for SQLite lifecycle/signal-log repositories, `follow-up required` for broader operational persistence.
- Governs: repository implementations, persistence records, and migration ownership.

## Current Plan

Persistence currently implements SQLite adapters for strategy repository, signal log repository, and local runtime state. SQL DDL exists for broader domain persistence and now includes the `runtime_positions`, `runtime_position_events`, and `runtime_records` local runtime tables. Operational Postgres wiring and full repositories for order/execution/trade-run state remain follow-up work.

## History

- 2026-05-24: Persistence design. See `history/2026-05-24-module-o-infrastructure-persistence-design.md`.
- 2026-05-24: Persistence implementation plan. See `history/2026-05-24-module-o-infrastructure-persistence.md`.
- 2026-05-24: SQL DDL management moved under `sql-ddl/latest.md`.

## Follow-Up

- Before production runners are added, decide whether composition uses SQLite, Postgres, or separate adapters per deployment mode.
- Implement or explicitly defer operational repositories for order requests, order results, execution reports, and trade runs before live trading. Local runtime position and generic runtime-record storage exists, but production recovery/reconciliation still needs an explicit deployment adapter decision. See the runtime readiness checklist in `docs/plans/interfaces/api/latest.md`.

