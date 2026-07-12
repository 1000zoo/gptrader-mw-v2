# Binance Microstructure Alpha Research Design

## Objective

Develop structurally new entry alpha combinations using every Binance USD-M Futures market-data source that can be used without fabricating history. Freeze the candidate universe before evaluation, run scheduler-driven strict walk-forward validation, and return measured results rather than parameter-tuned claims.

## Research Boundary

Historical backtests may use only data that can be replayed at the original event time:

- USD-M Futures 1m OHLCV and derived 5m/15m candles
- Aggregate trades (`aggTrades`): taker side, price, quantity, trade count, trade intensity, average trade size, CVD, and buy/sell imbalance
- Mark price, index price, and premium index klines
- Funding history where Binance provides it
- Open interest and long/short statistics only for periods for which Binance provides genuine historical rows

Live/shadow evaluation may additionally use:

- Best bid/ask (`bookTicker`)
- Partial and diff depth streams
- Liquidation/force-order streams
- Real-time mark price and funding updates

Live-only features must never be backfilled from candles or used in historical rankings without an authentic recorded event stream.

## Data Architecture

### Historical Feature Store

Add a Binance research-data loader that downloads and caches public archive/API data by symbol, source, and date. Raw data remains immutable. Deterministic aggregators produce timestamp-aligned 1m feature rows.

Each feature row records source availability. Missing OI, ratio, funding, or premium data remains missing; it is not replaced with zero. Strategies must declare required features and skip when those features are unavailable.

### Runtime Market Features

Expose non-candle features through a typed market-feature object carried in `StrategyContext.metadata`. Production Binance adapters and historical in-memory adapters implement the same feature-provider boundary. This preserves the existing scheduler/use-case path while allowing ORM/live and in-memory/backtest implementations to differ.

### Alignment Rules

- A decision at minute `T` may use only events whose timestamps are at or before the closed candle at `T`.
- Higher-timeframe features use only fully closed 5m/15m candles.
- Funding, OI, ratio, and premium values are forward-filled only after their published timestamp and only within a source-specific staleness limit.
- Feature provenance and coverage are exported with every backtest artifact.

## New Entry Alpha Families

### MTF Trend Pullback

Use a closed 15m trend, closed 5m momentum, and a 1m pullback/reclaim trigger. This targets continuation without reusing the existing one-timeframe impulse definition.

### Flow-Confirmed Breakout

Require a range or Donchian break plus positive taker imbalance, expanding trade intensity, and non-divergent CVD. A mirrored definition handles shorts.

### Flow Exhaustion Reversal

Detect a price extreme accompanied by declining aggressive-flow follow-through, CVD/price divergence, and a 1m reclaim. This differs from candle-only three-push exhaustion.

### Premium/Funding Reversion

Trade extreme premium or basis only after price fails to continue and taker flow reverses. Funding is context, not a standalone direction signal.

### Session Opening Range

Build deterministic Asia, Europe, and US UTC session ranges. Enter only when a session break aligns with MTF context and flow acceleration.

### Microstructure Router

Route among MTF continuation, flow breakout, flow exhaustion, premium reversion, and session breakout using volatility, trend, and feature-availability regimes. A missing feature disables only the dependent leg.

Order-book imbalance and liquidation variants are live-shadow candidates until enough event history has been recorded.

## Candidate Matrix

Freeze approximately 30 candidates before reading OOS rankings:

- Five standalone historical alpha families
- One microstructure router
- Two signal-strength variants per family
- A small fixed exit/guard set reused across families

Parameter neighborhoods must be broad and interpretable. Isolated single-point winners are rejected during robustness review.

## Walk-Forward Evaluation

1. Generate a monthly candidate matrix with the scheduler-driven runner.
2. For each OOS month, rank candidates using only the preceding six calendar months.
3. Require positive compounded train return, at least three positive train months, positive fee-adjusted trade expectancy, and a minimum train-trade threshold.
4. Evaluate train-selected top 1 and equal-weight top 3 on the next month.
5. Apply Binance taker fees, adverse slippage, funding when authentic funding rows are available, and feature-coverage reporting.
6. Promote only candidates with positive OOS expectancy and acceptable drawdown. Only promoted candidates proceed to 2021-2026 long-run WFV and parameter-neighborhood tests.

The candidate universe, source files, hashes, feature coverage, costs, and fold selections are recorded in every strict WFV artifact.

## Operational Safety

- Public historical and market-data endpoints do not require the trading API secret.
- Existing `.env` credentials are loaded only by the established Binance configuration layer and are never written to logs or research artifacts.
- Research downloads use bounded retries, rate-limit handling, checksums, and local caches.
- Live depth synchronization must detect sequence gaps and rebuild from a fresh snapshot.
- New live features initially run in shadow mode and cannot place orders by themselves.

## Verification

- Unit tests for every parser, timestamp alignment rule, feature aggregator, strategy signal, and missing-feature path
- Integration tests proving live and historical providers produce the same feature contract
- Leakage tests for current-minute aggTrades and incomplete higher-timeframe candles
- Feature-coverage and duplicate/conflict checks
- Strict WFV artifact recomputation and source-hash verification
- Final related test suite before reporting results

## Deliverables

- Binance historical/live feature-provider interfaces and adapters
- Cached historical feature data and coverage reports
- New alpha families and microstructure router
- Scheduler-driven monthly candidate matrices
- Strict WFV summaries and fold-level JSON artifacts
- Promotion/rejection decision with explicit limitations
