# Lifecycle Default Can Select Promoted Evaluations

- Severity: `medium`
- Status: `resolved`
- Found: `2026-05-25`

## Summary

`RunStrategyLifecycleUseCase` promotes the latest evaluation by taking the last result returned from the repository. It does not filter by lifecycle status or promotion eligibility before choosing the default source evaluation.

## Evidence

- `src/application/usecases/strategy_lifecycle/run_strategy_lifecycle_usecase.py:22` falls back to `_latest_evaluation_id`.
- `src/application/usecases/strategy_lifecycle/run_strategy_lifecycle_usecase.py:45` loads all evaluations for the target.
- `src/application/usecases/strategy_lifecycle/run_strategy_lifecycle_usecase.py:49` returns `evaluations[-1].evaluation_id`.
- `src/application/usecases/strategy_lifecycle/promote_strategy_usecase.py:25` delegates eligibility to the policy only after the source evaluation has already been chosen.

## Impact

After a successful promotion, the newest evaluation for the target can be the generated `PROMOTED` record. A later lifecycle run without an explicit `evaluation_id` can select that promoted record instead of the latest backtest or dry-run evaluation. Depending on policy configuration, this either causes a confusing rejection or allows promotion of a promotion record.

## Suggested Fix

Choose the latest evaluation from statuses that are eligible for promotion, or pass the candidate list through the policy before selecting the default. Add a test where a `DRY_RUN` evaluation is followed by a `PROMOTED` evaluation and the default lifecycle run still selects the latest eligible source evaluation.

## Resolution

`RunStrategyLifecycleUseCase` now selects the latest evaluation that satisfies the supplied promotion policy when no explicit `evaluation_id` is provided. A generated `PROMOTED` record is skipped unless the caller's policy explicitly allows that status.

## Verification

- `uv run pytest tests/application/usecases/trade/test_execute_trade_usecase.py tests/application/usecases/strategy_lifecycle/test_run_strategy_lifecycle_usecase.py tests/infrastructure/exchange/test_binance_order_execution_adapter.py tests/infrastructure/exchange/test_binance_account_adapter.py tests/infrastructure/llm/test_llm_client.py`
