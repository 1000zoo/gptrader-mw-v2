# Binance REST Trade Errors Are Not Classified For Safe Order Reconciliation

- Severity: `important`
- Status: `resolved`
- Found: `2026-05-26`

## Summary

`request_json` wraps only `HTTPError` as a generic `BinanceRestError`. It does not classify Binance error codes, rate-limit responses, network failures, invalid JSON, or the USD-M 503 variants where order execution status can be unknown.

## Evidence

- `src/infrastructure/exchange/binance/binance_rest.py:61` performs the HTTP request.
- `src/infrastructure/exchange/binance/binance_rest.py:64` catches only `HTTPError`.
- `src/infrastructure/exchange/binance/binance_rest.py:66` raises a generic `BinanceRestError` with status and raw body.
- `src/infrastructure/exchange/binance/order_execution/binance_order_execution_adapter.py:48` uses this helper for live order submission.
- Binance official USD-M Futures General Info documents 429/418 rate-limit handling and 503 message variants, including an execution-status-unknown case that must not be treated as an immediate failed operation.

## Impact

For `POST /fapi/v1/order`, treating every HTTP failure as a simple exception can lead to unsafe retry behavior. A 503 unknown-status response may mean the order was accepted but no response arrived before timeout; blindly retrying can duplicate orders. Conversely, 429/418 responses require backoff and should not be handled like ordinary request failures.

## Suggested Fix

Introduce typed Binance REST exceptions with parsed `code`, `msg`, response headers, and status classification. For order submission, represent unknown execution status separately and reconcile by `clientOrderId` through order query or user-data stream before retrying. Add explicit handling for 429, 418, known 503 variants, `URLError`/timeout, and invalid JSON.

## Verification

- `uv run pytest tests/infrastructure/exchange -q` -> `18 passed`

## Resolution

`src/infrastructure/exchange/binance/binance_rest.py` now parses Binance error payloads into typed exceptions with `status_code`, `code`, `message`, body, and headers. It classifies 429/418 rate-limit responses, USD-M 503 unknown execution status responses, network errors, and invalid JSON separately. `tests/infrastructure/exchange/test_binance_rest.py` covers each classification path.
