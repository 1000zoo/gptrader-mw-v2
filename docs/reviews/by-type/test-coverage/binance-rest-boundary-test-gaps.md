# Binance REST Boundary Tests Do Not Cover Request Construction And Error Paths

- Severity: `medium`
- Status: `resolved`
- Found: `2026-05-26`

## Summary

The Binance adapter tests monkeypatch adapter-local API functions, and `test_binance_rest.py` only verifies config defaults, environment credentials, and signing. The live REST boundary request construction and error paths are not directly tested.

## Evidence

- `tests/infrastructure/exchange/test_binance_rest.py:25` tests `sign_params`.
- `tests/infrastructure/exchange/test_binance_account_adapter.py:29` monkeypatches `load_account_api`.
- `tests/infrastructure/exchange/test_binance_market_data_adapter.py:48` monkeypatches `load_klines_api`.
- `tests/infrastructure/exchange/test_binance_order_execution_adapter.py:31` monkeypatches `submit_order_api`.
- `src/infrastructure/exchange/binance/binance_rest.py:50` handles query/body encoding, headers, and method-specific request construction with little direct coverage.

## Impact

The tests can pass while live requests are malformed. Missing coverage is especially relevant for signed POST body encoding, API key headers, timestamp/recvWindow placement, boolean parameter encoding, HTTP error body parsing, and non-HTTP network failures.

## Suggested Fix

Patch `urlopen` in focused `request_json` tests and capture the generated `Request`. Cover unsigned GET query strings, signed GET query strings, signed POST form bodies, API key headers, timestamp/recvWindow defaults, HTTP error body wrapping, and timeout/URL error behavior. Add a mapper or adapter test for lowercase boolean encoding after the order parameter mapping is fixed.

## Verification

- `uv run pytest tests/infrastructure/exchange -q` -> `18 passed`

## Resolution

`tests/infrastructure/exchange/test_binance_rest.py` now patches the module-local `urlopen` boundary and verifies generated unsigned GET URLs, signed POST form bodies, API key headers, timestamp/recvWindow defaults, HTTP error classification, network errors, and invalid JSON. Order mapper tests also cover Binance boolean parameter encoding.
