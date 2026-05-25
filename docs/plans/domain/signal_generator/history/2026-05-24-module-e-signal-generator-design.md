# Module E Signal Generator Design

## Goal

Define the domain rules that turn one or more strategy results into one final signal.

## Design

Module E owns `src/domain/signal_generator`. It does not know about persistence, backtesting, order execution, exchange adapters, or application orchestration.

The module exposes a common `SignalGenerator` protocol with `generate(context) -> GeneratedSignal`. A generated signal contains the final `Signal`, the underlying `StrategyResult` values that contributed to it, and immutable metadata for downstream lifecycle or application layers.

`CompositeSignalGenerator` evaluates a non-empty sequence of `Strategy` implementations against the same `StrategyContext`. It aggregates directional strategy signals by confidence. `WAIT` results do not vote for entry. If there is no directional signal or the top directional scores tie, the final signal is `WAIT`. Otherwise, the winning direction becomes the final signal and its confidence is the average confidence of the winning strategy results.

`RegimeSignalGenerator` selects another `SignalGenerator` from a regime key in `StrategyContext.metadata`. It is a domain-level router only. Missing regime metadata, unknown regime values, or invalid regime values return a `WAIT` signal instead of raising, so application layers can call it without knowing the internal routing rules.

## Exclusions

- No strategy repository lookup.
- No strategy lifecycle state.
- No backtest or live-trade orchestration.
- No risk sizing or execution decision.

## Testing

Tests should prove:

- Single and composite generators share the same protocol.
- Composite generation evaluates every strategy and returns a deterministic final signal.
- Tie or no-entry cases return `WAIT`.
- Regime generation delegates to the configured generator and falls back to `WAIT`.
