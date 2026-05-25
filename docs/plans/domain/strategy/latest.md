# Strategy Latest Plan

- Source path: `src/domain/strategy`
- Module: D
- Status: `done`
- Governs: strategy protocol, strategy context, and strategy result contract.

## Current Plan

Strategies consume market snapshots and indicator sets through `StrategyContext` and return `StrategyResult` without knowing about persistence, exchange clients, or scheduling. Strategy implementations may live under `src/domain/strategy/implementations` only when they are pure domain logic.

## History

- 2026-05-24: Design split for strategy boundaries. See `history/2026-05-24-module-d-strategy-design.md`.
- 2026-05-24: Implementation plan for strategy contract. See `history/2026-05-24-module-d-strategy.md`.

## Follow-Up

The repo still needs concrete production strategies and indicator wiring before live execution can make real decisions.

