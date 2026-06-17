# Strategy Lifecycle Use Cases Latest Plan

- Source path: `src/application/usecases/strategy_lifecycle`
- Module: M
- Status: `implemented-follow-up`
- Governs: strategy registration, promotion, and lifecycle run orchestration.

## Current Plan

Lifecycle use cases persist strategy and generator definitions, evaluate promotion policies, promote selected evaluations, and run cataloged strategy backtest cycles. They stay framework-neutral and repository-port based.

The strategy backtest cycle now coordinates the research module with lifecycle persistence:

- discover explicit production strategy candidates through the code-native `StrategyCatalog`;
- register or refresh each candidate's `StrategyDefinition`;
- run recent-lookback backtests through the research use cases;
- save `StrategyEvaluation(status=BACKTESTED)` records;
- leave promotion to the existing `RunStrategyLifecycleUseCase`.

This preserves the current boundary: research owns backtest execution, lifecycle owns registration/evaluation persistence/promotion, and the new cycle use case owns orchestration.

## History

- 2026-06-17: Strategy backtest cycle design. See `history/2026-06-17-strategy-backtest-cycle-design.md`.
- 2026-06-17: Strategy backtest cycle implementation plan. See `history/2026-06-17-strategy-backtest-cycle.md`.
- 2026-05-24: Strategy lifecycle design. See `history/2026-05-24-module-m-application-strategy-lifecycle-design.md`.
- 2026-05-24: Strategy lifecycle implementation plan. See `history/2026-05-24-module-m-application-strategy-lifecycle.md`.

## Follow-Up

Local runtime composition can execute the strategy backtest cycle through the scheduler entry point with local market data and an in-memory strategy repository. Extend the same pattern for dry-run/testnet runtime composition so operational runs execute the backtest cycle first and then invoke promotion orchestration through existing lifecycle use cases. Keep API and scheduler entry points behind command factories so they do not duplicate lifecycle rules.

Improve the pipeline after wiring by adding richer backtest metrics, promotion orchestration across saved `BACKTESTED` evaluations, and runtime visibility for per-strategy failures.

