# Module E Signal Generator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `src/domain/signal_generator` so single, composite, and regime-based signal generation share one domain contract.

**Architecture:** Add a `SignalGenerator` protocol and immutable `GeneratedSignal` output model. Implement composite aggregation by strategy confidence and regime routing by `StrategyContext.metadata`, keeping all behavior inside the domain layer.

**Tech Stack:** Python dataclasses, typing protocols, pytest.

---

### Task 1: Signal Generator Contract

**Files:**
- Create: `src/domain/signal_generator/__init__.py`
- Create: `src/domain/signal_generator/signal_generator.py`
- Test: `tests/domain/signal_generator/test_signal_generator.py`

**Steps:**

1. Write a failing test proving `SignalGenerator` is a runtime protocol and accepts implementations with `generate(context)`.
2. Run `uv run pytest tests/domain/signal_generator/test_signal_generator.py -v` and confirm it fails because the module does not exist.
3. Add `GeneratedSignal` and `SignalGenerator`.
4. Run the same test and confirm it passes.

### Task 2: Composite Signal Generator

**Files:**
- Create: `src/domain/signal_generator/composite_signal_generator.py`
- Test: `tests/domain/signal_generator/test_composite_signal_generator.py`

**Steps:**

1. Write failing tests for non-empty strategy validation, winning directional aggregation, tie-to-wait, and all-wait behavior.
2. Run `uv run pytest tests/domain/signal_generator/test_composite_signal_generator.py -v` and confirm failure.
3. Implement `CompositeSignalGenerator`.
4. Run the same test and confirm it passes.

### Task 3: Regime Signal Generator

**Files:**
- Create: `src/domain/signal_generator/regime_signal_generator.py`
- Test: `tests/domain/signal_generator/test_regime_signal_generator.py`

**Steps:**

1. Write failing tests for regime delegation and fallback-to-wait cases.
2. Run `uv run pytest tests/domain/signal_generator/test_regime_signal_generator.py -v` and confirm failure.
3. Implement `RegimeSignalGenerator`.
4. Run the same test and confirm it passes.

### Task 4: Documentation And Progress

**Files:**
- Modify: `docs/progress.md`
- Verify: all Module E tests and full domain tests.

**Steps:**

1. Mark Module E `done` and append a work log with this plan path.
2. Run `uv run pytest tests/domain -v`.
3. Confirm all domain tests pass before reporting completion.
