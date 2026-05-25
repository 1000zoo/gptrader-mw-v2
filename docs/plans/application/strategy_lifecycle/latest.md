# Strategy Lifecycle Use Cases Latest Plan

- Source path: `src/application/usecases/strategy_lifecycle`
- Module: M
- Status: `done`
- Governs: strategy registration, promotion, and lifecycle run orchestration.

## Current Plan

Lifecycle use cases persist strategy and generator definitions, evaluate promotion policies, and promote selected evaluations. They stay framework-neutral and repository-port based.

## History

- 2026-05-24: Strategy lifecycle design. See `history/2026-05-24-module-m-application-strategy-lifecycle-design.md`.
- 2026-05-24: Strategy lifecycle implementation plan. See `history/2026-05-24-module-m-application-strategy-lifecycle.md`.

## Follow-Up

API and scheduler entry points should call these use cases through command factories, not duplicate lifecycle rules.

