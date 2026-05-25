# Module H Execution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define vendor-neutral domain models for order requests, order results, and execution reports.

**Architecture:** Keep all behavior inside `src/domain/execution` with no exchange SDK, HTTP, persistence, or retry concerns. The module depends only on existing domain language from `market`, `signal`, and `position`, so Module J can later define execution ports on top of these models.

**Tech Stack:** Python dataclasses, Enum, Decimal, pytest.

---

### Task 1: Order Request Model

**Files:**
- Create: `src/domain/execution/order_request.py`
- Create: `src/domain/execution/__init__.py`
- Test: `tests/domain/execution/test_order_request.py`

**Step 1: Write the failing test**

Add tests for:
- an entry market order stores symbol, side, quantity, and reduce-only flag
- a limit order requires a positive limit price
- order requests reject `WAIT` side
- order requests reject non-positive quantity

**Step 2: Run test to verify it fails**

Run: `pytest tests/domain/execution/test_order_request.py -q`

Expected: FAIL because `src.domain.execution` does not exist yet.

**Step 3: Write minimal implementation**

Implement:
- `OrderType` enum with `MARKET` and `LIMIT`
- `OrderRequest` frozen dataclass
- `OrderRequest.market(...)`
- `OrderRequest.limit(...)`

Validation:
- side must be `LONG` or `SHORT`
- quantity must be positive
- limit orders require positive `limit_price`
- market orders must not carry `limit_price`

**Step 4: Run test to verify it passes**

Run: `pytest tests/domain/execution/test_order_request.py -q`

Expected: PASS.

### Task 2: Order Result Model

**Files:**
- Create: `src/domain/execution/order_result.py`
- Modify: `src/domain/execution/__init__.py`
- Test: `tests/domain/execution/test_order_result.py`

**Step 1: Write the failing test**

Add tests for:
- accepted result stores client order id and optional exchange order id
- rejected result stores a failure reason
- filled result stores executed quantity and average price
- successful fill rejects non-positive executed quantity or average price

**Step 2: Run test to verify it fails**

Run: `pytest tests/domain/execution/test_order_result.py -q`

Expected: FAIL because `OrderResult` is not implemented yet.

**Step 3: Write minimal implementation**

Implement:
- `OrderStatus` enum with `ACCEPTED`, `REJECTED`, `FILLED`, `PARTIALLY_FILLED`, `CANCELED`
- `OrderResult` frozen dataclass
- class constructors `accepted(...)`, `rejected(...)`, `filled(...)`, `partially_filled(...)`, `canceled(...)`

Validation:
- `client_order_id` is required
- rejected results require `failure_reason`
- filled and partially filled results require positive `executed_quantity` and `average_price`
- accepted, rejected, and canceled results cannot carry execution quantity or average price

**Step 4: Run test to verify it passes**

Run: `pytest tests/domain/execution/test_order_result.py -q`

Expected: PASS.

### Task 3: Execution Report Model

**Files:**
- Create: `src/domain/execution/execution_report.py`
- Modify: `src/domain/execution/__init__.py`
- Test: `tests/domain/execution/test_execution_report.py`

**Step 1: Write the failing test**

Add tests for:
- an execution report combines the original order request and order result
- filled reports can be converted into a position increase event
- non-filled reports cannot be converted into a position event
- mismatched client order ids are rejected when creating a report

**Step 2: Run test to verify it fails**

Run: `pytest tests/domain/execution/test_execution_report.py -q`

Expected: FAIL because `ExecutionReport` is not implemented yet.

**Step 3: Write minimal implementation**

Implement:
- `ExecutionReport` frozen dataclass with `request` and `result`
- `ExecutionReport.to_position_event()` returning `PositionEvent.increase(...)` for filled and partially filled entry orders

Validation:
- report client order ids must match
- conversion requires filled or partially filled status
- conversion requires a non-reduce-only request
- conversion requires result execution quantity and average price

**Step 4: Run test to verify it passes**

Run: `pytest tests/domain/execution/test_execution_report.py -q`

Expected: PASS.

### Task 4: Module Verification And Progress Update

**Files:**
- Modify: `docs/progress.md`

**Step 1: Run focused tests**

Run: `pytest tests/domain/execution -q`

Expected: PASS.

**Step 2: Run domain test suite**

Run: `pytest tests/domain -q`

Expected: PASS.

**Step 3: Update progress log**

Update Module H status from `in progress` to `done` and append a `2026-05-24 Module H` work log that references this plan.
