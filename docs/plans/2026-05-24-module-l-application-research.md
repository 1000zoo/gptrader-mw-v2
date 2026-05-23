# Module L Application Research Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build research application usecases for backtest, dry-run, and evaluation while keeping them separate from live trading.

**Architecture:** Add a new `src/application/usecases/research` package with DTOs and three usecases. The usecases inject market data, strategies, and signal generators through existing domain protocols, produce immutable result DTOs, and hand evaluation output to the lifecycle model via `StrategyEvaluation`.

**Tech Stack:** Python dataclasses, enums, Decimal metrics, typing Protocol-compatible fakes in pytest.

---

### Task 1: Add Research DTOs

**Files:**
- Create: `src/application/usecases/research/dto.py`
- Create: `src/application/usecases/research/__init__.py`
- Test: `tests/application/usecases/research/test_backtest_strategy_usecase.py`

**Step 1: Write the failing test**

Create a test importing `BacktestStrategyCommand` and verifying it stores symbol, timeframe, candle limit, indicators, target id, and metadata.

**Step 2: Run test to verify it fails**

Run: `pytest tests/application/usecases/research/test_backtest_strategy_usecase.py -v`
Expected: FAIL because the research package does not exist.

**Step 3: Write minimal implementation**

Add frozen dataclasses for `BacktestStrategyCommand`, `BacktestStrategyResult`, `DryRunStrategyCommand`, `DryRunStrategyResult`, `EvaluateStrategyCommand`, and `EvaluateStrategyResult`. Add `ResearchRunMode` with `BACKTEST` and `DRY_RUN`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/application/usecases/research/test_backtest_strategy_usecase.py -v`
Expected: PASS.

### Task 2: Add Backtest Strategy Usecase

**Files:**
- Create: `src/application/usecases/research/backtest_strategy_usecase.py`
- Modify: `src/application/usecases/research/__init__.py`
- Test: `tests/application/usecases/research/test_backtest_strategy_usecase.py`

**Step 1: Write the failing test**

Add a test where fake market data returns a snapshot and a fake strategy returns a `StrategyResult`. Assert the result contains the strategy result and the `StrategyContext` used.

**Step 2: Run test to verify it fails**

Run: `pytest tests/application/usecases/research/test_backtest_strategy_usecase.py -v`
Expected: FAIL because `BacktestStrategyUseCase` is missing.

**Step 3: Write minimal implementation**

Implement `BacktestStrategyUseCase.execute(command)` by loading the snapshot, creating `StrategyContext`, evaluating the strategy, and returning `BacktestStrategyResult`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/application/usecases/research/test_backtest_strategy_usecase.py -v`
Expected: PASS.

### Task 3: Add Dry Run Strategy Usecase

**Files:**
- Create: `src/application/usecases/research/dry_run_strategy_usecase.py`
- Modify: `src/application/usecases/research/__init__.py`
- Test: `tests/application/usecases/research/test_dry_run_strategy_usecase.py`

**Step 1: Write the failing test**

Add a test where fake market data and fake signal generator produce a `GeneratedSignal`. Assert no order execution dependency is required and the generated signal is returned.

**Step 2: Run test to verify it fails**

Run: `pytest tests/application/usecases/research/test_dry_run_strategy_usecase.py -v`
Expected: FAIL because `DryRunStrategyUseCase` is missing.

**Step 3: Write minimal implementation**

Implement `DryRunStrategyUseCase.execute(command)` with snapshot loading, `StrategyContext` creation, and signal generation.

**Step 4: Run test to verify it passes**

Run: `pytest tests/application/usecases/research/test_dry_run_strategy_usecase.py -v`
Expected: PASS.

### Task 4: Add Evaluation Usecase

**Files:**
- Create: `src/application/usecases/research/evaluate_strategy_usecase.py`
- Modify: `src/application/usecases/research/__init__.py`
- Test: `tests/application/usecases/research/test_evaluate_strategy_usecase.py`

**Step 1: Write failing tests**

Add tests proving backtest mode produces `StrategyLifecycleStatus.BACKTESTED` and dry-run mode produces `StrategyLifecycleStatus.DRY_RUN`.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/application/usecases/research/test_evaluate_strategy_usecase.py -v`
Expected: FAIL because `EvaluateStrategyUseCase` is missing.

**Step 3: Write minimal implementation**

Implement `EvaluateStrategyUseCase.execute(command)` by creating a `StrategyEvaluation` with status derived from `ResearchRunMode`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/application/usecases/research/test_evaluate_strategy_usecase.py -v`
Expected: PASS.

### Task 5: Final Verification and Progress

**Files:**
- Modify: `docs/progress.md`

**Step 1: Run focused tests**

Run: `pytest tests/application/usecases/research tests/domain -v`
Expected: PASS.

**Step 2: Update progress**

Mark Module L as `done` only after implementation and tests pass, then append a work log referencing this plan and design.
