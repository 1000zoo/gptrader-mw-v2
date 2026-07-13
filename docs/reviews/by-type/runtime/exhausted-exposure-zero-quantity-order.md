# Exhausted Exposure Can Build Zero-Quantity Orders

- Severity: `important`
- Status: `resolved`
- Found: `2026-05-25`

## Summary

`ExecuteTradeUseCase` sizes the position before calling the default `RiskPolicy`. `PositionSizer` caps the requested notional to the remaining exposure. If the account has no remaining total or symbol exposure, the capped notional becomes `0`, the risk check allows it, and order construction then raises because `OrderRequest` requires a positive quantity.

## Evidence

- `src/application/usecases/trade/execute_trade_usecase.py:61` creates `PositionSizer`.
- `src/application/usecases/trade/execute_trade_usecase.py:65` computes the capped `position_size`.
- `src/application/usecases/trade/execute_trade_usecase.py:70` checks risk against `position_size.notional`, not the uncapped requested notional.
- `src/domain/risk/position_sizer.py:51` caps notional with `min(... remaining_total_exposure, remaining_symbol_exposure)`.
- `src/application/usecases/trade/execute_trade_usecase.py:83` creates the order after the zero-notional check path.

## Impact

The default production path cannot reliably return `TradeExecutionStatus.RISK_REJECTED` for exhausted exposure. Instead, it may raise `ValueError("quantity must be positive")` after the signal has already been logged. This can turn an expected risk decision into a scheduler-level failure and leave a logged signal without a corresponding trade result.

The current test for risk rejection uses an injected rejecting policy, so it does not cover the default policy and sizer interaction.

## Suggested Fix

Separate requested notional from capped order notional. Run `RiskPolicy.check_entry` against the uncapped requested notional, or explicitly reject zero-sized `PositionSize` before constructing an `OrderRequest`. Add a test where both remaining exposure values are zero and assert `RISK_REJECTED` with no order submission.

## Resolution

`ExecuteTradeUseCase` now computes the uncapped requested notional before sizing and passes that amount into `RiskPolicy.check_entry`. Exhausted total or symbol exposure is rejected before `OrderRequest` construction, so the path returns `TradeExecutionStatus.RISK_REJECTED` without submitting an order.

## Verification

- `uv run pytest tests/application/usecases/trade/test_execute_trade_usecase.py tests/application/usecases/strategy_lifecycle/test_run_strategy_lifecycle_usecase.py tests/infrastructure/exchange/test_binance_order_execution_adapter.py tests/infrastructure/exchange/test_binance_account_adapter.py tests/infrastructure/llm/test_llm_client.py`
