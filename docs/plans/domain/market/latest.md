# Market Latest Plan

- Source path: `src/domain/market`
- Module: A
- Status: `done`
- Governs: symbols, timeframes, candles, and market snapshots.

## Current Plan

The market domain is the base market-data language used by strategies, indicators, exchange adapters, and research/trade use cases. It owns validation for symbol pairs, timeframe labels, candle intervals, chronological snapshots, and latest-candle access.

## History

- 2026-05-12: Initial market model plan. See `history/2026-05-12-module-a-market.md`.

## Follow-Up

Future work should extend this module only for exchange-neutral market concepts. Exchange payload parsing belongs under `src/infrastructure/exchange`.

