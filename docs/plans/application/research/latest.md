# Research Use Cases Latest Plan

- Source path: `src/application/usecases/research`
- Module: L
- Status: `done`
- Governs: backtest, dry-run, and strategy evaluation use cases.

## Current Plan

Research use cases run strategies and signal generators without submitting live orders. They produce evaluation data that lifecycle use cases can later promote.

## History

- 2026-05-24: Research design. See `history/2026-05-24-module-l-application-research-design.md`.
- 2026-05-24: Research implementation plan. See `history/2026-05-24-module-l-application-research.md`.

## Follow-Up

Backtest realism, historical data loading, and result persistence should be planned before using these flows for production promotion.

