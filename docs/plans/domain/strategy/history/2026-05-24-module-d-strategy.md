# Module D Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define the shared contract that individual strategies use to receive market data and return strategy-level signals.

**Architecture:** Add pure domain contracts under `src/domain/strategy` with no exchange, database, LLM, or orchestration dependencies. Strategy evaluation receives a `StrategyContext` made from Module A market snapshots and Module B indicator sets, and returns a `StrategyResult` wrapping Module C `Signal`.

**Tech Stack:** Python dataclasses, typing `Protocol`, standard library `types.MappingProxyType`, and pytest.

---

### Task 1: Strategy Context

**Files:**
- Create: `src/domain/strategy/strategy_context.py`
- Create: `src/domain/strategy/__init__.py`
- Test: `tests/domain/strategy/test_strategy_context.py`

**Step 1: Write the failing test**

Write tests for:
- accepting one `MarketSnapshot` and matching `IndicatorSet`
- rejecting mismatched symbol
- rejecting mismatched timeframe
- rejecting indicators measured at a different latest candle close time
- defensive copying of metadata

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/strategy/test_strategy_context.py -v`

Expected: FAIL because `src.domain.strategy.StrategyContext` does not exist.

**Step 3: Write minimal implementation**

Create a frozen `StrategyContext` dataclass with:
- `market: MarketSnapshot`
- `indicators: IndicatorSet`
- `metadata: Mapping[str, object]`

Validate symbol, timeframe, and latest candle close time against indicator measurement time. Convert metadata to `MappingProxyType(dict(...))`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/strategy/test_strategy_context.py -v`

Expected: PASS.

### Task 2: Strategy Result

**Files:**
- Create: `src/domain/strategy/strategy_result.py`
- Modify: `src/domain/strategy/__init__.py`
- Test: `tests/domain/strategy/test_strategy_result.py`

**Step 1: Write the failing test**

Write tests for:
- storing strategy name and `Signal`
- rejecting blank strategy names
- defensive copying of metadata

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/strategy/test_strategy_result.py -v`

Expected: FAIL because `src.domain.strategy.StrategyResult` does not exist.

**Step 3: Write minimal implementation**

Create a frozen `StrategyResult` dataclass with:
- `name: str`
- `signal: Signal`
- `metadata: Mapping[str, object]`

Normalize name by stripping whitespace and reject empty names. Convert metadata to `MappingProxyType(dict(...))`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/strategy/test_strategy_result.py -v`

Expected: PASS.

### Task 3: Strategy Protocol

**Files:**
- Create: `src/domain/strategy/strategy.py`
- Create: `src/domain/strategy/implementations/__init__.py`
- Modify: `src/domain/strategy/__init__.py`
- Test: `tests/domain/strategy/test_strategy.py`

**Step 1: Write the failing test**

Write a contract test that verifies:
- `Strategy` is a `Protocol`
- an implementation with `evaluate(context: StrategyContext) -> StrategyResult` satisfies the protocol at runtime

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/strategy/test_strategy.py -v`

Expected: FAIL because `Strategy` does not exist.

**Step 3: Write minimal implementation**

Create a `@runtime_checkable` `Strategy` protocol with one method:

```python
def evaluate(self, context: StrategyContext) -> StrategyResult:
    ...
```

Do not implement concrete strategy behavior in this task.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/strategy/test_strategy.py -v`

Expected: PASS.

### Task 4: Module Verification

**Files:**
- Verify: `src/domain/strategy/*.py`
- Verify: `tests/domain/strategy/*.py`

**Step 1: Run focused tests**

Run: `uv run pytest tests/domain/strategy -v`

Expected: PASS.

**Step 2: Run full regression suite**

Run: `uv run pytest`

Expected: PASS.

### Task 5: Progress Update

**Files:**
- Modify: `docs/progress.md`
- Existing: `docs/plans/2026-05-24-module-d-strategy.md`

**Step 1: Mark Module D done**

Change Module D status from `in progress` to `done`.

**Step 2: Add work log**

Add a `2026-05-24 Module D` log entry with summary and follow-up.

**Step 3: Final verification**

Run: `uv run pytest`

Expected: PASS.
