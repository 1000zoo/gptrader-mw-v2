# Strategy Backtest Cycle Design

## Goal

Define the pipeline that discovers production strategy candidates, runs repeatable backtests over a recent lookback window, stores `StrategyEvaluation` records, and then lets the existing lifecycle promotion path select promotable evaluations.

## Problem

The current lifecycle module registers definitions and promotes already-created evaluations. It does not discover strategy implementations or run backtests. The current research module can backtest one injected strategy, but it does not know how to enumerate every production strategy candidate.

The missing pipeline is:

1. list active strategy candidates;
2. register or refresh their `StrategyDefinition`;
3. instantiate each strategy from its parameters;
4. load recent market data;
5. run the strategy backtest/evaluation path;
6. persist `StrategyEvaluation(status=BACKTESTED)`;
7. leave promotion to the existing policy-based lifecycle use case.

## Architecture

Add an explicit strategy catalog instead of dynamic class scanning. "All strategies" means all strategies registered in the catalog, not every class found under `src/domain/strategy/implementations`.

This keeps half-finished experiments, test doubles, and parameter-incomplete classes out of scheduled lifecycle runs. It also gives each production candidate a stable id, version, default parameters, lookback setting, and factory.

The pipeline should keep existing module boundaries:

- `src/domain/strategy` owns strategy contracts, specs, catalog entries, and factories.
- `src/application/usecases/research` owns single-strategy backtest execution.
- `src/application/usecases/strategy_lifecycle` owns the orchestration that registers definitions, asks research to run candidates, stores evaluations, and then optionally invokes promotion.
- `src/interfaces/scheduler` owns scheduled entry points and command factories.

## Components

### StrategySpec

`StrategySpec` describes one executable production candidate:

- `strategy_id`: stable id used as lifecycle `target_id`.
- `name`: human-readable strategy name.
- `implementation`: import-style implementation name for persistence and diagnostics.
- `version`: semantic or date-based version.
- `parameters`: default constructor parameters.
- `symbol`: default symbol for scheduled evaluation.
- `timeframe`: default timeframe for scheduled evaluation.
- `lookback_candle_limit`: first-phase lookback control.
- `metadata`: extra diagnostic or scheduling hints.

The first phase uses `lookback_candle_limit` rather than a date range because `MarketDataPort` currently supports limit-based loading only.

### StrategyCatalog

`StrategyCatalog` returns a stable tuple of `StrategySpec` values and instantiates strategies from specs. It is explicit:

- `latest-close-moving-average`
- `session-volume-profile`

The catalog can later be backed by configuration or persistence, but the first version should remain code-native and deterministic.

### RunStrategyBacktestCycleUseCase

This use case coordinates the batch:

1. load strategy specs from the catalog;
2. save each `StrategyDefinition`;
3. instantiate each strategy;
4. call `BacktestStrategyUseCase` with spec symbol, timeframe, lookback, and indicators;
5. compute simple deterministic metrics from the `StrategyResult`;
6. create and save `StrategyEvaluation(status=BACKTESTED)`;
7. return per-strategy results, including failures without stopping the whole batch.

The first metric set should be intentionally small:

- `signal_confidence`: strategy result confidence;
- `direction_score`: `1` for LONG or SHORT, `0` for WAIT;
- `reason_count`: number of signal reasons.

These are not production performance metrics. They are lifecycle plumbing metrics until the backtest engine grows realized PnL, drawdown, win rate, and trade count.

### Promotion Handoff

The backtest cycle should not directly promote by default. It should return saved evaluations. A scheduler or API can then invoke `RunStrategyLifecycleUseCase` for each target using the existing `PromotionPolicy`.

An optional follow-up can add a command flag such as `promote_after_backtest`, but the first implementation should keep backtest and promotion separate.

## Data Flow

1. Scheduler builds `RunStrategyBacktestCycleCommand`.
2. Use case reads specs from `StrategyCatalog`.
3. Use case saves a `StrategyDefinition` for each spec.
4. Use case creates a `BacktestStrategyCommand`.
5. Research backtest returns `StrategyResult` and `StrategyContext`.
6. Use case converts the result into `EvaluateStrategyCommand`.
7. `EvaluateStrategyUseCase` creates `StrategyEvaluation(status=BACKTESTED)`.
8. Use case saves the evaluation through `StrategyRepositoryPort`.
9. Existing promotion use case can later select the latest promotable evaluation.

## Error Handling

Catalog-level invalid specs should raise during construction because that is a developer/configuration error.

Per-strategy runtime failures should be captured in the cycle result with:

- `strategy_id`
- `succeeded=False`
- `error_type`
- `error_message`

One failed strategy must not prevent other catalog strategies from being evaluated.

Repository failures should still raise. If persistence is down, the cycle result would be misleading because evaluations were not saved.

## Testing

Test the pipeline with fakes:

- fake market data returns a known snapshot;
- fake repository records definitions and evaluations;
- catalog contains one long strategy, one wait strategy, and one failing strategy;
- successful strategies save definitions and evaluations;
- failing strategies appear in result failures and do not save evaluations;
- full cycle does not call promotion implicitly.

## Future Work

Replace `lookback_candle_limit` with date-window loading after `MarketDataPort` supports `load_candles_between(symbol, timeframe, start, end)`.

Replace plumbing metrics with real backtest metrics after the research layer has a real execution simulation model.

Allow config-backed catalogs once code-native strategy candidates become too rigid for operations.
