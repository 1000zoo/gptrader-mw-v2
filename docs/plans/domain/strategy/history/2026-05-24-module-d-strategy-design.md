# Module D Strategy Design

## Goal

Define the pure domain contract for individual trading strategies.

## Scope

Module D owns only `src/domain/strategy` and `tests/domain/strategy`.
It does not combine strategies, orchestrate use cases, call LLM adapters, access exchange APIs, or persist strategy state.

## Recommended Approach

Use a minimal immutable domain model:

- `StrategyContext` represents one strategy evaluation input.
- `StrategyResult` represents one strategy evaluation output.
- `Strategy` is a protocol implemented by concrete strategy classes.
- `implementations/` exists as the extension point for later concrete strategies, but this module does not add a production strategy.

This keeps individual strategy contracts stable for Module E signal generation, Module I lifecycle modeling, and Module L research flows.

## Data Model

`StrategyContext` uses:

- `MarketSnapshot` from Module A for candle history
- `IndicatorSet` from Module B for calculated indicators at the decision point
- immutable metadata for optional strategy parameters or upstream labels

`StrategyResult` uses:

- `name` to identify the strategy that produced the result
- `Signal` from Module C as the strategy judgment
- immutable metadata for diagnostics that do not belong in the core signal model

## Rules

- Context market and indicator symbol must match.
- Context market and indicator timeframe must match.
- Context latest candle close time must match indicator measurement time.
- Context metadata is defensively copied and exposed read-only.
- Result strategy name is required.
- Result metadata is defensively copied and exposed read-only.
- A strategy implementation only needs to expose `evaluate(context) -> StrategyResult`.

## Testing

Use TDD with focused tests for:

- valid context construction from market and indicator data
- rejecting context symbol, timeframe, and measurement mismatches
- defensive metadata copying
- valid strategy result construction
- rejecting blank strategy result names
- protocol shape for strategy implementations
