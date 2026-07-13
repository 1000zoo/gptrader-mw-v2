# Module C Signal Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define the shared domain language for strategy signals and final trade decisions.

**Architecture:** Add immutable domain value objects under `src/domain/signal`. Keep the module vendor-neutral and free of application, infrastructure, or orchestration concerns.

**Tech Stack:** Python dataclasses, enums, pytest.

---

### Task 1: Signal Domain Tests

**Files:**
- Create: `tests/domain/signal/test_signal.py`
- Create: `tests/domain/signal/test_signal_reason.py`
- Create: `tests/domain/signal/test_trade_decision.py`

**Steps:**
1. Write failing tests for signal direction, confidence bounds, reasons, metadata copying, and wait-state helper construction.
2. Run `pytest tests/domain/signal -q` and verify failures are caused by missing `src.domain.signal`.

### Task 2: Signal Domain Models

**Files:**
- Create: `src/domain/signal/__init__.py`
- Create: `src/domain/signal/signal.py`
- Create: `src/domain/signal/signal_reason.py`
- Create: `src/domain/signal/trade_decision.py`

**Steps:**
1. Implement `SignalDirection`, `Signal`, and confidence validation.
2. Implement `SignalReason` with stable `code`, human-readable `message`, and immutable metadata.
3. Implement `TradeDecisionAction` and `TradeDecision` with validation that entry decisions align with signal direction.
4. Run `pytest tests/domain/signal -q` and verify it passes.

### Task 3: Progress Update

**Files:**
- Modify: `docs/progress.md`

**Steps:**
1. Mark Module C as `done`.
2. Add a Module C work log with summary and follow-up modules.
3. Run `pytest -q` for the project.
