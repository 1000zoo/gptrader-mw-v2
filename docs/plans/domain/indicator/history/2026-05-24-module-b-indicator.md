# Module B Indicator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define the shared indicator result language for strategies, signal generators, and research flows.

**Architecture:** Add pure domain contracts under `src/domain/indicator` with no TA library, exchange, database, or strategy dependencies. Represent indicator values as normalized keys at one candle timestamp, group them by symbol and timeframe, and expose calculation as a port-style protocol.

**Tech Stack:** Python dataclasses, typing `Protocol`, standard library `datetime`, `decimal`, and pytest.

---

### Task 1: Indicator Value

**Files:**
- Create: `src/domain/indicator/indicator_value.py`
- Create: `src/domain/indicator/__init__.py`
- Test: `tests/domain/indicator/test_indicator_value.py`

**Step 1: Write the failing test**

Write tests for:
- name normalization from human/vendor input such as `" RSI "` to `rsi`
- stable key generation with sorted parameters such as `rsi.source_close.window_14`
- parameterless key generation such as `macd_hist`
- required indicator name validation
- defensive copying of `parameters`

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/indicator/test_indicator_value.py -v`

Expected: FAIL because `src.domain.indicator.IndicatorValue` does not exist.

**Step 3: Write minimal implementation**

Create a frozen `IndicatorValue` dataclass with:
- `name: str`
- `value: Decimal`
- `measured_at: datetime`
- `parameters: dict[str, Any]`
- `key` property
- `normalize_key(...)` helper for lookup consistency

Keep the model vendor-neutral and avoid indicator calculation logic.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/indicator/test_indicator_value.py -v`

Expected: PASS.

### Task 2: Indicator Set

**Files:**
- Create: `src/domain/indicator/indicator_set.py`
- Modify: `src/domain/indicator/__init__.py`
- Test: `tests/domain/indicator/test_indicator_set.py`

**Step 1: Write the failing test**

Write tests for:
- grouping values by one `Symbol`, `Timeframe`, and `measured_at`
- `get(...)` returning an optional indicator value
- `require(...)` raising `KeyError` for missing indicators
- duplicate normalized key rejection
- rejection of values measured at a different candle timestamp

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/indicator/test_indicator_set.py -v`

Expected: FAIL because `src.domain.indicator.IndicatorSet` does not exist.

**Step 3: Write minimal implementation**

Create a frozen `IndicatorSet` dataclass with:
- `symbol: Symbol`
- `timeframe: Timeframe`
- `measured_at: datetime`
- `values: tuple[IndicatorValue, ...]`
- `keys` property
- `get(key)`
- `require(key)`

Use Module A market models directly. Do not introduce exchange-specific identifiers.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/indicator/test_indicator_set.py -v`

Expected: PASS.

### Task 3: Indicator Calculator Contract

**Files:**
- Create: `src/domain/indicator/indicator_calculator.py`
- Modify: `src/domain/indicator/__init__.py`
- Test: `tests/domain/indicator/test_indicator_calculator.py`

**Step 1: Write the failing test**

Write a contract test that verifies:
- `IndicatorCalculator` is a `Protocol`
- `calculate(snapshot: MarketSnapshot) -> IndicatorSet` is the domain boundary

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/indicator/test_indicator_calculator.py -v`

Expected: FAIL because `IndicatorCalculator` does not exist.

**Step 3: Write minimal implementation**

Create an `IndicatorCalculator` protocol with a single `calculate(...)` method.

Do not call pandas, TA libraries, exchange APIs, or persistence here. Concrete calculation belongs outside this pure contract.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/indicator/test_indicator_calculator.py -v`

Expected: PASS.

### Task 4: Module Verification

**Files:**
- Verify: `src/domain/indicator/*.py`
- Verify: `tests/domain/indicator/*.py`

**Step 1: Run focused tests**

Run: `uv run pytest tests/domain/indicator -v`

Expected: PASS.

**Step 2: Run full regression suite**

Run: `uv run pytest`

Expected: PASS.

### Task 5: Progress Update

**Files:**
- Modify: `docs/progress.md`
- Create: `docs/plans/2026-05-24-module-b-indicator.md`

**Step 1: Mark Module B done**

Change Module B status from `in progress` to `done`.

**Step 2: Add work log**

Add a `2026-05-24 Module B` log entry with summary and follow-up.

**Step 3: Final verification**

Run: `uv run pytest`

Expected: PASS.
