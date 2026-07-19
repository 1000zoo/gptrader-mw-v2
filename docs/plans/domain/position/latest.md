# Position Latest Plan

- Source path: `src/domain/position`
- Module: G
- Status: `done`
- Governs: position state, position events, and event application.

## Current Plan

Positions are updated by domain events derived from execution reports or streams. Closed/open invariants and quantity/price validation stay in the domain.

## History

- 2026-05-24: Position design plan. See `history/2026-05-24-module-g-position-design.md`.
- 2026-05-24: Position implementation plan. See `history/2026-05-24-module-g-position.md`.

## Follow-Up

Module T must map live stream events into these domain events without leaking vendor payloads.

