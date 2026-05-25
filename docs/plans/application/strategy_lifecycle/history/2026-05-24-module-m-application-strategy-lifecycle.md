# Module M Application Strategy Lifecycle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build application usecases for strategy registration and promotion lifecycle orchestration.

**Architecture:** Add `src/application/usecases/strategy_lifecycle` with command/result DTOs and three usecases. The usecases depend on `StrategyRepositoryPort`, `StrategyDefinition`, `SignalGeneratorDefinition`, `StrategyEvaluation`, and `PromotionPolicy`; they do not create infrastructure adapters or run research jobs.

**Tech Stack:** Python dataclasses, Protocol-based ports, pytest.

---

### Task 1: Registration DTOs and Usecase

**Files:**
- Create: `src/application/usecases/strategy_lifecycle/dto.py`
- Create: `src/application/usecases/strategy_lifecycle/register_strategy_usecase.py`
- Create: `src/application/usecases/strategy_lifecycle/__init__.py`
- Test: `tests/application/usecases/strategy_lifecycle/test_register_strategy_usecase.py`

**Step 1: Write the failing tests**

Cover saving a `StrategyDefinition`, saving a `SignalGeneratorDefinition`, and rejecting a command with neither definition.

**Step 2: Run tests to verify failure**

Run: `pytest tests/application/usecases/strategy_lifecycle/test_register_strategy_usecase.py -q`

Expected: FAIL because the package does not exist.

**Step 3: Implement minimal DTOs and usecase**

Add:

- `RegisterStrategyCommand`
- `RegisterStrategyResult`
- `RegisterStrategyUseCase`

The usecase saves the provided strategy definition and/or signal generator definition through `StrategyRepositoryPort`.

**Step 4: Verify**

Run: `pytest tests/application/usecases/strategy_lifecycle/test_register_strategy_usecase.py -q`

Expected: PASS.

### Task 2: Promotion Usecase

**Files:**
- Modify: `src/application/usecases/strategy_lifecycle/dto.py`
- Create: `src/application/usecases/strategy_lifecycle/promote_strategy_usecase.py`
- Modify: `src/application/usecases/strategy_lifecycle/__init__.py`
- Test: `tests/application/usecases/strategy_lifecycle/test_promote_strategy_usecase.py`

**Step 1: Write the failing tests**

Cover successful promotion, policy rejection, and missing evaluation.

**Step 2: Run tests to verify failure**

Run: `pytest tests/application/usecases/strategy_lifecycle/test_promote_strategy_usecase.py -q`

Expected: FAIL because promotion types do not exist.

**Step 3: Implement minimal DTOs and usecase**

Add:

- `PromoteStrategyCommand`
- `PromoteStrategyResult`
- `PromoteStrategyUseCase`

The usecase lists evaluations for `target_id`, finds `evaluation_id`, applies `PromotionPolicy`, and saves a new promoted `StrategyEvaluation` when allowed.

**Step 4: Verify**

Run: `pytest tests/application/usecases/strategy_lifecycle/test_promote_strategy_usecase.py -q`

Expected: PASS.

### Task 3: Lifecycle Runner Usecase

**Files:**
- Modify: `src/application/usecases/strategy_lifecycle/dto.py`
- Create: `src/application/usecases/strategy_lifecycle/run_strategy_lifecycle_usecase.py`
- Modify: `src/application/usecases/strategy_lifecycle/__init__.py`
- Test: `tests/application/usecases/strategy_lifecycle/test_run_strategy_lifecycle_usecase.py`

**Step 1: Write the failing tests**

Cover selecting the latest evaluation for a target and honoring an explicit evaluation id.

**Step 2: Run tests to verify failure**

Run: `pytest tests/application/usecases/strategy_lifecycle/test_run_strategy_lifecycle_usecase.py -q`

Expected: FAIL because lifecycle runner types do not exist.

**Step 3: Implement minimal DTOs and usecase**

Add:

- `RunStrategyLifecycleCommand`
- `RunStrategyLifecycleResult`
- `RunStrategyLifecycleUseCase`

The usecase selects an evaluation id, delegates to `PromoteStrategyUseCase`, and returns its result.

**Step 4: Verify**

Run: `pytest tests/application/usecases/strategy_lifecycle/test_run_strategy_lifecycle_usecase.py -q`

Expected: PASS.

### Task 4: Module Verification and Progress Update

**Files:**
- Modify: `docs/progress.md`

**Step 1: Run focused tests**

Run: `pytest tests/application/usecases/strategy_lifecycle -q`

Expected: PASS.

**Step 2: Run related regression tests**

Run: `pytest tests/domain/lifecycle tests/domain/ports tests/application/usecases/research tests/application/usecases/strategy_lifecycle -q`

Expected: PASS.

**Step 3: Update progress**

Set Module M to `done` and append a work log with:

- Plan: `docs/plans/2026-05-24-module-m-application-strategy-lifecycle.md`
- Design: `docs/plans/2026-05-24-module-m-application-strategy-lifecycle-design.md`
- Summary and follow-up for Modules R/S/O.
