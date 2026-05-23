# Module L Application Research Design

**Goal:** Define research-only application usecases for backtest, dry-run, and evaluation without mixing in live order execution.

**Scope:** This design covers `src/application/usecases/research` and its direct tests. It depends on existing domain contracts from market, indicator, strategy, signal generator, lifecycle, and ports.

## Architecture

Research usecases stay in the application layer and orchestrate domain contracts only. They receive market data through `MarketDataPort`, build `StrategyContext`, run either a `Strategy` or `SignalGenerator`, and return structured DTOs.

No research usecase submits orders, opens positions, writes persistence records, or applies promotion policy. Persistence and promotion are deferred to Module M/O. The handoff to lifecycle is a `StrategyEvaluation` instance.

## Components

- `BacktestStrategyUseCase`
  - Loads a snapshot from `MarketDataPort`.
  - Evaluates a single `Strategy`.
  - Returns the `StrategyResult` and context used for evaluation.
- `DryRunStrategyUseCase`
  - Loads a snapshot from `MarketDataPort`.
  - Runs a `SignalGenerator`.
  - Returns the `GeneratedSignal` and context without order execution.
- `EvaluateStrategyUseCase`
  - Converts metrics and metadata into `StrategyEvaluation`.
  - Chooses lifecycle status from an explicit research mode.

## Data Flow

1. Command DTO validates symbol, timeframe, candle limit, identifiers, and mode.
2. Usecase loads market snapshot.
3. Usecase builds `StrategyContext` with supplied indicators and optional metadata.
4. Strategy or generator executes against the context.
5. Result DTO returns the domain output without side effects.

## Error Handling

Validation remains at DTO/domain boundaries. Invalid candle limits or blank identifiers raise `ValueError`. Market/indicator mismatches are delegated to `StrategyContext`.

## Testing

Tests should use simple fakes for `MarketDataPort`, `Strategy`, and `SignalGenerator`. They should prove that research flows load market data, preserve context metadata, return domain results, produce lifecycle evaluations, and never require order execution or persistence ports.
