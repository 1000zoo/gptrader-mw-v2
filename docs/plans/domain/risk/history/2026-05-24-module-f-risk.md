# Module F Risk Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `src/domain/risk` domain contracts for exposure limits, risk checks, and confidence-based position sizing.

**Architecture:** Keep Module F as pure domain code. Split exposure capacity, policy decisions, and sizing into separate files so Module K can compose them without depending on infrastructure.

**Tech Stack:** Python dataclasses, `Decimal`, pytest.

---

### Task 1: Exposure Limit

**Files:**
- Create: `tests/domain/risk/test_exposure_limit.py`
- Create: `src/domain/risk/exposure_limit.py`
- Create or update: `src/domain/risk/__init__.py`

**Step 1: Write failing tests**

Test that `ExposureLimit` rejects invalid account and ratio values, computes remaining total exposure, computes remaining symbol exposure, and allows a new notional only when both limits have room.

**Step 2: Run tests to verify RED**

Run: `uv run pytest tests/domain/risk/test_exposure_limit.py -v`

Expected: fail because `src.domain.risk` does not exist yet.

**Step 3: Implement minimal model**

Create frozen dataclass `ExposureLimit` with validation and methods:

- `max_total_exposure`
- `max_symbol_exposure`
- `remaining_total_exposure`
- `remaining_symbol_exposure`
- `allows(new_notional: Decimal) -> bool`

**Step 4: Run tests to verify GREEN**

Run: `uv run pytest tests/domain/risk/test_exposure_limit.py -v`

Expected: pass.

### Task 2: Risk Policy

**Files:**
- Create: `tests/domain/risk/test_risk_policy.py`
- Create: `src/domain/risk/risk_policy.py`
- Update: `src/domain/risk/__init__.py`

**Step 1: Write failing tests**

Test that entry decisions are allowed within limits, blocked when total exposure is exceeded, blocked when symbol exposure is exceeded, and non-entry decisions are blocked for sizing.

**Step 2: Run tests to verify RED**

Run: `uv run pytest tests/domain/risk/test_risk_policy.py -v`

Expected: fail because `RiskPolicy` is missing.

**Step 3: Implement minimal policy**

Create:

- `RiskDecisionReason`
- `RiskCheck`
- `RiskPolicy.check_entry(decision, exposure_limit, requested_notional)`

**Step 4: Run tests to verify GREEN**

Run: `uv run pytest tests/domain/risk/test_risk_policy.py -v`

Expected: pass.

### Task 3: Position Sizer

**Files:**
- Create: `tests/domain/risk/test_position_sizer.py`
- Create: `src/domain/risk/position_sizer.py`
- Update: `src/domain/risk/__init__.py`

**Step 1: Write failing tests**

Test that a long or short entry uses confidence-based sizing, caps by remaining exposure, rejects non-entry decisions, and rejects invalid price/leverage/risk ratio inputs.

**Step 2: Run tests to verify RED**

Run: `uv run pytest tests/domain/risk/test_position_sizer.py -v`

Expected: fail because `PositionSizer` is missing.

**Step 3: Implement minimal sizer**

Create:

- `PositionSize`
- `PositionSizer.size(decision, exposure_limit, entry_price)`

Use `equity * base_risk_ratio * confidence * leverage` and cap by the smaller remaining exposure.

**Step 4: Run tests to verify GREEN**

Run: `uv run pytest tests/domain/risk/test_position_sizer.py -v`

Expected: pass.

### Task 4: Module Verification and Progress

**Files:**
- Update: `docs/progress.md`

**Step 1: Run focused tests**

Run: `uv run pytest tests/domain/risk -v`

Expected: all risk tests pass.

**Step 2: Run domain tests**

Run: `uv run pytest tests/domain -v`

Expected: all domain tests pass.

**Step 3: Update progress**

Mark Module F as `done`, add a work log with this plan path, summary, and follow-up.
