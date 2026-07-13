# Module K Application Trade Design

## Scope

Module K defines application-layer trade orchestration. This session starts with `ExecuteTradeUseCase` and keeps the same DTO/result style available for `ClosePositionUseCase` and `SyncPositionUseCase` in follow-up work.

## Recommended Approach

Build application DTOs plus `ExecuteTradeUseCase` first. The usecase receives all collaborators through its constructor and never creates exchange, persistence, or HTTP concrete implementations. It composes existing domain contracts: market data, signal generation, risk sizing/checking, order execution, and signal logging.

## Data Flow

`ExecuteTradeCommand` carries symbol, timeframe, candle limit, an already calculated `IndicatorSet`, an `ExposureLimit`, sizing config, and client order metadata. The usecase loads a `MarketSnapshot`, builds a `StrategyContext`, generates a signal, records the generated signal, converts entry decisions into a market `OrderRequest`, and submits the order only after position sizing and risk approval.

Non-entry decisions and rejected risk checks return a structured result without submitting an order. Order submission results are returned unchanged from the domain execution contract.

## Error Boundaries

Module K does not translate vendor errors because vendors are outside this layer. Domain validation errors remain visible. Adapter-level retry, timeout, and protocol handling belong in infrastructure modules.

## Testing

Tests use in-memory fakes for ports and generators. They verify orchestration behavior: entry decisions submit orders, HOLD/EXIT decisions skip orders, risk denial skips orders, and generated signals are logged.
