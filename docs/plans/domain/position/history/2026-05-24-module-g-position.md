# Module G Position Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the pure position domain model for current position state and event-driven updates.

**Architecture:** Add immutable dataclasses and enums under `src/domain/position`. Keep all exchange, websocket, persistence, and execution concerns outside this module. Use existing `Symbol` and `SignalDirection` domain language instead of introducing duplicate concepts.

**Tech Stack:** Python dataclasses, enum, Decimal, pytest.

---

### Task 1: Position Status

**Files:**
- Create: `src/domain/position/position_status.py`
- Create: `src/domain/position/__init__.py`
- Test: `tests/domain/position/test_position_status.py`

**Step 1: Write the failing test**

```python
from src.domain.position import PositionStatus


def test_position_status_names_open_and_closed_states():
    assert PositionStatus.OPEN.value == "open"
    assert PositionStatus.CLOSED.value == "closed"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/domain/position/test_position_status.py -v`
Expected: FAIL because `src.domain.position` does not exist.

**Step 3: Write minimal implementation**

```python
from enum import Enum


class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
```

Export it from `src/domain/position/__init__.py`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/domain/position/test_position_status.py -v`
Expected: PASS.

### Task 2: Position Creation

**Files:**
- Create: `src/domain/position/position.py`
- Test: `tests/domain/position/test_position.py`

**Step 1: Write failing tests**

Add tests for opening a long position, rejecting `WAIT`, rejecting non-positive quantity, and exposing closed position state.

**Step 2: Run tests to verify failure**

Run: `pytest tests/domain/position/test_position.py -v`
Expected: FAIL because `Position` is not implemented.

**Step 3: Write minimal implementation**

Create frozen `Position` with `symbol`, `direction`, `quantity`, `average_entry_price`, and `status`.
Add `Position.open(...)` and `Position.closed(...)`.

**Step 4: Run tests to verify pass**

Run: `pytest tests/domain/position/test_position.py -v`
Expected: PASS.

### Task 3: Position Events

**Files:**
- Create: `src/domain/position/position_event.py`
- Modify: `src/domain/position/__init__.py`
- Test: `tests/domain/position/test_position_event.py`

**Step 1: Write failing tests**

Add tests for increase, decrease, and close event factory methods.

**Step 2: Run tests to verify failure**

Run: `pytest tests/domain/position/test_position_event.py -v`
Expected: FAIL because `PositionEvent` is not implemented.

**Step 3: Write minimal implementation**

Create `PositionEventType` enum and frozen `PositionEvent` dataclass with factory methods.

**Step 4: Run tests to verify pass**

Run: `pytest tests/domain/position/test_position_event.py -v`
Expected: PASS.

### Task 4: Event Application

**Files:**
- Modify: `src/domain/position/position.py`
- Test: `tests/domain/position/test_position.py`

**Step 1: Write failing tests**

Add tests for weighted average increase, partial decrease, full close, over-reduction rejection, direction mismatch rejection, and rejecting updates after close.

**Step 2: Run tests to verify failure**

Run: `pytest tests/domain/position/test_position.py -v`
Expected: FAIL because `apply_event` is not implemented.

**Step 3: Write minimal implementation**

Implement `Position.apply_event(event)` with domain validation and immutable return values.

**Step 4: Run all domain tests**

Run: `pytest tests/domain -v`
Expected: PASS.

### Task 5: Progress Update

**Files:**
- Modify: `docs/progress.md`

**Step 1: Mark Module G done**

Change Module G status from `in progress` to `done`.

**Step 2: Add work log**

Add a `2026-05-24 Module G` log entry with summary and follow-up.

**Step 3: Final verification**

Run: `pytest -v`
Expected: PASS.
