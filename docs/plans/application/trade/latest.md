# Trade Use Cases Latest Plan

- Source path: `src/application/usecases/trade`
- Module: K
- Status: `done`
- Governs: execute trade, close position, and sync position use cases.

## Current Plan

Trade use cases orchestrate market snapshot loading, strategy/generator execution, signal logging, risk checks, order submission, reduce-only close orders, and execution-report position sync. They depend on ports and domain contracts only.

## History

- 2026-05-24: Trade use case design. See `history/2026-05-24-module-k-application-trade-design.md`.
- 2026-05-24: Trade use case implementation plan. See `history/2026-05-24-module-k-application-trade.md`.

## Follow-Up

Production execution still needs concrete strategy/generator composition, Binance adapter ownership cleanup, persistence wiring, and scheduler/API runners.

