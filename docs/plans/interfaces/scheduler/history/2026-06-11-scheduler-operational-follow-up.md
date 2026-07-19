# Scheduler Interfaces Latest Plan

- Source path: `src/interfaces/scheduler`
- Module: S
- Status: `done` for framework-neutral scheduler entry points, `follow-up required` for operational runners.
- Governs: scheduler-facing wrappers around trade and lifecycle use cases.

## Current Plan

Schedulers receive already-constructed use cases and command factories, call one use case per scheduled method, and return immutable execution records with timing, command, result, and error state. They do not own APScheduler, cron, process lifecycle, or adapter composition.

## History

- 2026-05-25: Scheduler design. See `history/2026-05-25-module-s-interfaces-scheduler-design.md`.
- 2026-05-25: Scheduler implementation plan. See `history/2026-05-25-module-s-interfaces-scheduler.md`.

## Follow-Up

- Operational deployment still needs a runner or composition root that builds adapters, repositories, strategies, command factories, and scheduler triggers.
- Align the runner with the runtime readiness checklist in `docs/plans/interfaces/api/latest.md`, especially overlap prevention, idempotent client order ids, persisted scheduler results, and failure visibility.

