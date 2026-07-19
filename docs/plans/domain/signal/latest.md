# Signal Latest Plan

- Source path: `src/domain/signal`
- Module: C
- Status: `done`
- Governs: trading signal direction, reason, and trade decision language.

## Current Plan

Signals define the common decision vocabulary shared by strategies, generators, risk, and trade execution. The domain validates confidence range and action/direction compatibility.

## History

- 2026-05-12: Initial signal model plan. See `history/2026-05-12-module-c-signal.md`.

## Follow-Up

New decision types should be added only when downstream risk/execution behavior is also planned.

