# Module S Interfaces Scheduler Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add framework-neutral scheduler entry points for trade and strategy lifecycle use cases.

**Architecture:** Scheduler classes receive command factories and already-constructed use cases from the composition root. They call one use case per scheduled method and return immutable execution records with timing, command, result, and error state.

**Tech Stack:** Python dataclasses, typing protocols/callables, pytest.

---

### Task 1: Trade Scheduler Tests

**Files:**
- Create: `tests/interfaces/scheduler/test_trade_scheduler.py`
- Create later: `src/interfaces/scheduler/trade_scheduler.py`
- Create later: `src/interfaces/scheduler/__init__.py`
- Create later: `src/interfaces/__init__.py`

**Step 1: Write the failing tests**

Add tests for:

- `run_trade_execution` calls `ExecuteTradeUseCase.execute` with the command from the factory and returns a successful record.
- `close_position` calls `ClosePositionUseCase.close`.
- `sync_position` calls `SyncPositionUseCase.sync`.
- use-case exceptions are captured in a failed record.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/interfaces/scheduler/test_trade_scheduler.py -v`

Expected: FAIL because `src.interfaces.scheduler.trade_scheduler` does not exist.

**Step 3: Write minimal implementation**

Create `TradeScheduler` and immutable execution record dataclasses.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/interfaces/scheduler/test_trade_scheduler.py -v`

Expected: PASS.

### Task 2: Strategy Lifecycle Scheduler Tests

**Files:**
- Create: `tests/interfaces/scheduler/test_strategy_lifecycle_scheduler.py`
- Create later: `src/interfaces/scheduler/strategy_lifecycle_scheduler.py`

**Step 1: Write the failing tests**

Add tests for:

- `run_lifecycle` calls `RunStrategyLifecycleUseCase.execute` with the command from the factory and returns a successful record.
- factory exceptions are captured before invoking the use case.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/interfaces/scheduler/test_strategy_lifecycle_scheduler.py -v`

Expected: FAIL because `src.interfaces.scheduler.strategy_lifecycle_scheduler` does not exist.

**Step 3: Write minimal implementation**

Create `StrategyLifecycleScheduler` and immutable execution record dataclasses.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/interfaces/scheduler/test_strategy_lifecycle_scheduler.py -v`

Expected: PASS.

### Task 3: Package Exports and Documentation State

**Files:**
- Modify: `src/interfaces/scheduler/__init__.py`
- Modify: `docs/progress.md`

**Step 1: Add package exports**

Export scheduler classes and execution record dataclasses from `src/interfaces/scheduler/__init__.py`.

**Step 2: Run targeted scheduler tests**

Run: `pytest tests/interfaces/scheduler -v`

Expected: PASS.

**Step 3: Run full verification**

Run: `pytest`

Expected: PASS.

**Step 4: Update progress log**

Set Module S to `done` and add a `2026-05-25 Module S` work log that references this plan and design document.

