# Binance Direct REST Adapter Design

## Context

The Binance infrastructure adapters currently receive raw client objects through their constructors. This leaks Binance-shaped method names into tests and future composition roots, even though the adapters already live under `src/infrastructure/exchange/binance`.

The selected direction is to remove raw client injection and call Binance USD-M Futures REST API directly. The project will not use `binance-futures-connector` for these adapters.

This document is exchange infrastructure history. Keep it under `docs/plans/infrastructure/exchange/history/`; do not move Binance exchange plans to the top-level `docs/plans/` directory.

## Architecture

Each adapter keeps a local API boundary function for the Binance endpoints it needs:

- `market_data/binance_market_data_adapter.py`: `load_klines_api`
- `account/binance_account_adapter.py`: `load_account_api`
- `order_execution/binance_order_execution_adapter.py`: `submit_order_api`, `load_orders_api`

These functions are the only places in each adapter script that know the Binance endpoint path and request/response shape. If Binance changes an API contract, the change should be isolated to the matching API function and mapper when required.

Shared HTTP mechanics live in a small Binance REST utility:

- `binance_config.py`: `BinanceConfig`
- `binance_rest.py`: unsigned and signed request helpers, query signing, timestamp and recv window handling

## Data Flow

Domain callers use existing ports:

- `MarketDataPort.load_candles`
- `AccountPort.load_account_snapshot`
- `OrderExecutionPort.submit_order`
- `OrderExecutionPort.load_execution_reports`

Adapters translate domain input into endpoint function input. Endpoint functions call Binance REST and return raw Binance payloads. Existing mapper functions convert raw payloads into domain output.

## Error Handling

The first pass keeps error handling small and explicit:

- HTTP non-2xx responses raise a Binance REST exception containing status and response body.
- Invalid JSON responses raise through the standard JSON decoder.
- Retry, rate-limit backoff, and exchange-specific error translation remain follow-up work.

## Testing

Tests should no longer pass fake raw clients into adapters. They should monkeypatch the project-owned API functions in the adapter modules. This keeps tests focused on adapter behavior and prevents test doubles from depending on arbitrary Binance SDK method names.

Targeted verification:

```bash
pytest tests/infrastructure/exchange -q
```

Full verification:

```bash
pytest
```
