# Module K Application Trade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first application trade usecase, `ExecuteTradeUseCase`, while leaving the DTO/result pattern ready for close and sync trade usecases.

**Architecture:** Keep orchestration in `src/application/usecases/trade` and inject all external collaborators through constructor arguments. The usecase composes domain models and ports, logs generated signals, checks risk before order submission, and returns structured application results.

**Tech Stack:** Python dataclasses, typing Protocol-compatible fakes in tests, pytest.

---

### Task 1: Add Trade DTOs

**Files:**
- Create: `src/application/usecases/trade/dto.py`
- Create: `src/application/usecases/trade/__init__.py`
- Test: `tests/application/usecases/trade/test_execute_trade_usecase.py`

**Step 1: Write the failing test**

Create a test that imports `ExecuteTradeCommand` and verifies it stores symbol, timeframe, indicator set, exposure limit, sizing config, and client order id prefix.

**Step 2: Run test to verify it fails**

Run: `pytest tests/application/usecases/trade/test_execute_trade_usecase.py -v`
Expected: FAIL because the application trade package does not exist.

**Step 3: Write minimal implementation**

Add frozen dataclasses for `ExecuteTradeCommand`, `TradeExecutionStatus`, and `ExecuteTradeResult`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/application/usecases/trade/test_execute_trade_usecase.py -v`
Expected: PASS.

### Task 2: Submit Entry Orders

**Files:**
- Create: `src/application/usecases/trade/execute_trade_usecase.py`
- Modify: `src/application/usecases/trade/__init__.py`
- Test: `tests/application/usecases/trade/test_execute_trade_usecase.py`

**Step 1: Write the failing test**

Add a test where a fake signal generator returns `ENTER_LONG`; expect one market order to be submitted with the sized quantity and an `ORDER_SUBMITTED` result.

**Step 2: Run test to verify it fails**

Run: `pytest tests/application/usecases/trade/test_execute_trade_usecase.py -v`
Expected: FAIL because `ExecuteTradeUseCase` is missing.

**Step 3: Write minimal implementation**

Implement `ExecuteTradeUseCase.execute(command)` with snapshot loading, `StrategyContext` creation, signal generation, signal logging, sizing, risk check, order request creation, and order submission.

**Step 4: Run test to verify it passes**

Run: `pytest tests/application/usecases/trade/test_execute_trade_usecase.py -v`
Expected: PASS.

### Task 3: Skip Non-Entry and Risk-Denied Decisions

**Files:**
- Modify: `src/application/usecases/trade/execute_trade_usecase.py`
- Test: `tests/application/usecases/trade/test_execute_trade_usecase.py`

**Step 1: Write failing tests**

Add one test for HOLD/EXIT behavior and one test for risk denial. Both should assert that no order is submitted and the result explains why.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/application/usecases/trade/test_execute_trade_usecase.py -v`
Expected: FAIL for missing branch handling.

**Step 3: Write minimal implementation**

Return `SKIPPED` for non-entry decisions and `RISK_REJECTED` for denied risk checks.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/application/usecases/trade/test_execute_trade_usecase.py -v`
Expected: PASS.

### Task 4: Add Close Position Usecase

**Files:**
- Create: `src/application/usecases/trade/close_position_usecase.py`
- Modify: `src/application/usecases/trade/dto.py`
- Modify: `src/application/usecases/trade/__init__.py`
- Test: `tests/application/usecases/trade/test_close_position_usecase.py`

**Step 1: Write failing tests**

Add tests proving open positions submit a reduce-only market order in the opposite direction, and closed positions skip order submission.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/application/usecases/trade/test_close_position_usecase.py -v`
Expected: FAIL because close position DTOs and usecase are missing.

**Step 3: Write minimal implementation**

Add `ClosePositionCommand`, `ClosePositionResult`, and `ClosePositionUseCase`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/application/usecases/trade/test_close_position_usecase.py -v`
Expected: PASS.

### Task 5: Add Sync Position Usecase

**Files:**
- Create: `src/application/usecases/trade/sync_position_usecase.py`
- Modify: `src/application/usecases/trade/dto.py`
- Modify: `src/application/usecases/trade/__init__.py`
- Test: `tests/application/usecases/trade/test_sync_position_usecase.py`

**Step 1: Write failing tests**

Add tests proving execution reports are loaded through the order execution port and applied to a supplied position.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/application/usecases/trade/test_sync_position_usecase.py -v`
Expected: FAIL because sync position DTOs and usecase are missing.

**Step 3: Write minimal implementation**

Add `SyncPositionCommand`, `SyncPositionResult`, and `SyncPositionUseCase`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/application/usecases/trade/test_sync_position_usecase.py -v`
Expected: PASS.

### Task 6: Final Verification and Progress

**Files:**
- Modify: `docs/progress.md`

**Step 1: Run focused tests**

Run: `pytest tests/application/usecases/trade tests/domain -v`
Expected: PASS.

**Step 2: Update progress**

Mark Module K as `done` only after implementation and tests pass, then append a work log referencing this plan.
