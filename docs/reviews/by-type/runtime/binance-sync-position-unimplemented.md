# Binance Position Sync Uses Unimplemented Execution Reports

- Severity: `important`
- Status: `resolved`
- Found: `2026-05-25`

## Summary

`SyncPositionUseCase` depends on `OrderExecutionPort.load_execution_reports`, but the concrete Binance adapter raises `NotImplementedError` for that method.

## Evidence

- `src/application/usecases/trade/sync_position_usecase.py:12` calls `load_execution_reports`.
- `src/infrastructure/exchange/binance/order_execution/binance_order_execution_adapter.py:21` declares the concrete Binance method.
- `src/infrastructure/exchange/binance/order_execution/binance_order_execution_adapter.py:27` raises `NotImplementedError`.
- `src/interfaces/scheduler/trade_scheduler.py:126` exposes a scheduled sync path that ultimately uses the same use case.

## Impact

Any runtime composition that wires `SyncPositionUseCase` to `BinanceOrderExecutionAdapter` cannot synchronize positions. The scheduler will capture the exception as a failed scheduled run, but the application cannot make progress on position reconciliation through the default Binance infrastructure.

## Suggested Fix

Either implement Binance execution-report loading before exposing this adapter in runnable sync flows, or gate the scheduler/use-case composition so sync is unavailable until a concrete implementation exists. Add an integration-style test that composes the sync use case with the Binance adapter contract and verifies the expected behavior.

## Resolution

`BinanceOrderExecutionAdapter.load_execution_reports` now calls `get_all_orders` with symbol and time bounds, then maps Binance order payloads into `ExecutionReport` objects using the domain `OrderRequest` and `OrderResult` types.

## Verification

- `uv run pytest tests/application/usecases/trade/test_execute_trade_usecase.py tests/application/usecases/strategy_lifecycle/test_run_strategy_lifecycle_usecase.py tests/infrastructure/exchange/test_binance_order_execution_adapter.py tests/infrastructure/exchange/test_binance_account_adapter.py tests/infrastructure/llm/test_llm_client.py`
