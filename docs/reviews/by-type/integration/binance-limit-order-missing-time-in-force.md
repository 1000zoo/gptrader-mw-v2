# Binance LIMIT Orders Omit Required TimeInForce

- Severity: `important`
- Status: `resolved`
- Found: `2026-05-26`

## Summary

`map_order_request_to_binance_params` maps domain limit orders to Binance USD-M `LIMIT` orders with `quantity` and `price`, but does not include `timeInForce`.

## Evidence

- `src/infrastructure/exchange/binance/order_execution/binance_order_execution_mapper.py:10` builds the Binance order parameter dictionary.
- `src/infrastructure/exchange/binance/order_execution/binance_order_execution_mapper.py:19` adds `price` when `limit_price` exists.
- The local Binance API reference documents `timeInForce`, `quantity`, and `price` as additional mandatory parameters for `LIMIT` orders in `docs/plans/infrastructure/exchange/binance-usdm-futures-api-spec-2026.md:195`.
- Binance official USD-M Futures New Order documentation also lists `timeInForce`, `quantity`, and `price` as mandatory for `LIMIT`.

## Impact

Live limit order submissions can be rejected by Binance even though the domain `OrderRequest.limit` is valid. This makes the adapter contract appear usable for limit orders while failing at the exchange boundary.

## Suggested Fix

Add an explicit time-in-force policy. If the domain does not need user-selectable values yet, map limit orders to `timeInForce=GTC` by default and add tests for both mapper output and adapter submission parameters. If strategy behavior needs IOC/FOK/GTD, extend `OrderRequest` before mapping.

## Verification

- `uv run pytest tests/infrastructure/exchange -q` -> `18 passed`

## Resolution

`src/infrastructure/exchange/binance/order_execution/binance_order_execution_mapper.py` now maps domain LIMIT orders to Binance parameters with `timeInForce=GTC`. `tests/infrastructure/exchange/test_binance_order_execution_adapter.py` covers the generated LIMIT order payload.
