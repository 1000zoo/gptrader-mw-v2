# Binance ReduceOnly Parameter Encoding Is Unsafe

- Severity: `important`
- Status: `resolved`
- Found: `2026-05-26`

## Summary

`map_order_request_to_binance_params` always includes `reduceOnly` as a Python boolean. `urlencode` serializes that value as `True` or `False`, while Binance USD-M Futures documents the parameter as the lowercase strings `true` or `false` and disallows it in Hedge Mode.

## Evidence

- `src/infrastructure/exchange/binance/order_execution/binance_order_execution_mapper.py:17` sets `reduceOnly` directly from `request.reduce_only`.
- `src/infrastructure/exchange/binance/binance_rest.py:50` serializes request parameters through `urlencode`.
- The local Binance API reference documents `reduceOnly` as `STRING` in `docs/plans/infrastructure/exchange/binance-usdm-futures-api-spec-2026.md:205`.
- Binance official USD-M Futures New Order documentation describes `reduceOnly` as `"true"` or `"false"` and states it cannot be sent in Hedge Mode.

## Impact

Order submission can fail with invalid parameter errors, and accounts using Hedge Mode may reject every order because `reduceOnly=false` is still sent. This is a live trading integration risk because it depends on account position mode and only appears at the Binance boundary.

## Suggested Fix

Encode `reduceOnly` as lowercase strings when sent. Prefer omitting it when `False` unless one-way mode requires explicit behavior. If Hedge Mode is supported, add position-mode awareness and tests that assert `reduceOnly` is omitted or included according to the selected mode.

## Verification

- `uv run pytest tests/infrastructure/exchange -q` -> `18 passed`

## Resolution

`src/infrastructure/exchange/binance/order_execution/binance_order_execution_mapper.py` now omits `reduceOnly` for normal orders and sends the lowercase string `true` only when the domain request is reduce-only. `tests/infrastructure/exchange/test_binance_order_execution_adapter.py` covers the true case and the default omission.
