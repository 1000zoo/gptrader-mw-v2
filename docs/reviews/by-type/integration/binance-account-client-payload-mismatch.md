# Binance Account Adapter Method And Payload Mismatch

- Severity: `medium`
- Status: `resolved`
- Found: `2026-05-25`

## Summary

`BinanceAccountAdapter` calls `client.get_account()`, while `map_binance_account_to_snapshot` expects a futures-style payload with `totalWalletBalance`, `assets`, `walletBalance`, and `maintMargin`.

## Evidence

- `src/infrastructure/exchange/binance/account/binance_account_adapter.py:14` calls `self._client.get_account()`.
- `src/infrastructure/exchange/binance/account/binance_account_mapper.py:14` iterates `payload.get("assets", ())`.
- `src/infrastructure/exchange/binance/account/binance_account_mapper.py:19` requires `payload["totalWalletBalance"]`.
- `src/infrastructure/exchange/binance/account/binance_account_mapper.py:24` requires per-asset `walletBalance`.

## Impact

For common Binance clients, spot account calls often return `balances` with `free` and `locked`, while futures account calls expose fields closer to the mapper expectation but are typically reached through a futures-specific method. A real client can therefore fail at runtime with missing keys or produce empty balances even though account data exists.

## Suggested Fix

Make the adapter explicit about the Binance account API it supports. For example, use a futures-account client method and name the adapter accordingly, or support both spot and futures payload shapes in separate mappers with tests for each real response shape.

## Resolution

`BinanceAccountAdapter` now prefers a futures account method when present and falls back to `get_account`. The mapper supports futures `assets` payloads and spot `balances` payloads, including total equity calculation for spot balances.

## Verification

- `uv run pytest tests/application/usecases/trade/test_execute_trade_usecase.py tests/application/usecases/strategy_lifecycle/test_run_strategy_lifecycle_usecase.py tests/infrastructure/exchange/test_binance_order_execution_adapter.py tests/infrastructure/exchange/test_binance_account_adapter.py tests/infrastructure/llm/test_llm_client.py`
