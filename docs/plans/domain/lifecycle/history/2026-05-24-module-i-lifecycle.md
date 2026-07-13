# Module I Lifecycle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define domain lifecycle models for strategy definitions, signal generator definitions, evaluations, and promotion policy decisions.

**Architecture:** Keep all behavior inside `src/domain/lifecycle` with immutable dataclasses and no persistence, scheduler, backtest engine, or infrastructure dependency. The module depends only on Python standard library value types so later ports and application use cases can persist and orchestrate these models without changing the domain contract.

**Tech Stack:** Python dataclasses, Enum, Decimal, MappingProxyType, pytest.

---

### Task 1: Strategy Definition Model

**Files:**
- Create: `src/domain/lifecycle/strategy_definition.py`
- Create: `src/domain/lifecycle/__init__.py`
- Test: `tests/domain/lifecycle/test_strategy_definition.py`

**Step 1: Write the failing test**

Add tests for:
- storing normalized strategy id, name, implementation reference, version, parameters, and metadata
- rejecting blank required text fields
- defensively copying parameters and metadata

**Step 2: Run test to verify it fails**

Run: `pytest tests/domain/lifecycle/test_strategy_definition.py -q`

Expected: FAIL because `src.domain.lifecycle` does not exist yet.

**Step 3: Write minimal implementation**

Implement `StrategyDefinition` as a frozen dataclass.

Validation:
- `strategy_id`, `name`, `implementation`, and `version` must be non-blank after trimming
- `parameters` and `metadata` are immutable defensive copies

**Step 4: Run test to verify it passes**

Run: `pytest tests/domain/lifecycle/test_strategy_definition.py -q`

Expected: PASS.

### Task 2: Signal Generator Definition Model

**Files:**
- Create: `src/domain/lifecycle/signal_generator_definition.py`
- Modify: `src/domain/lifecycle/__init__.py`
- Test: `tests/domain/lifecycle/test_signal_generator_definition.py`

**Step 1: Write the failing test**

Add tests for:
- storing generator id, name, ordered strategy ids, regime routes, and metadata
- rejecting an empty strategy id list
- rejecting regime routes that reference unknown strategy ids
- defensively copying route and metadata mappings

**Step 2: Run test to verify it fails**

Run: `pytest tests/domain/lifecycle/test_signal_generator_definition.py -q`

Expected: FAIL because `SignalGeneratorDefinition` is not implemented yet.

**Step 3: Write minimal implementation**

Implement `SignalGeneratorDefinition` as a frozen dataclass.

Validation:
- `generator_id` and `name` must be non-blank after trimming
- `strategy_ids` must contain at least one non-blank id
- `regime_routes` keys and values must be non-blank after trimming
- every route target must exist in `strategy_ids`
- mappings are immutable defensive copies

**Step 4: Run test to verify it passes**

Run: `pytest tests/domain/lifecycle/test_signal_generator_definition.py -q`

Expected: PASS.

### Task 3: Strategy Evaluation Model

**Files:**
- Create: `src/domain/lifecycle/strategy_evaluation.py`
- Modify: `src/domain/lifecycle/__init__.py`
- Test: `tests/domain/lifecycle/test_strategy_evaluation.py`

**Step 1: Write the failing test**

Add tests for:
- storing evaluation id, target id, status, metrics, and metadata
- looking up a metric by normalized name
- rejecting blank ids and blank metric names
- defensively copying metrics and metadata

**Step 2: Run test to verify it fails**

Run: `pytest tests/domain/lifecycle/test_strategy_evaluation.py -q`

Expected: FAIL because `StrategyEvaluation` is not implemented yet.

**Step 3: Write minimal implementation**

Implement:
- `StrategyLifecycleStatus` enum with `DRAFT`, `BACKTESTED`, `DRY_RUN`, `PROMOTED`, `ARCHIVED`
- `StrategyEvaluation` frozen dataclass
- `metric(name: str) -> Decimal | None`

Validation:
- `evaluation_id` and `target_id` are required
- metric names are trimmed and cannot be blank
- metrics and metadata are immutable defensive copies

**Step 4: Run test to verify it passes**

Run: `pytest tests/domain/lifecycle/test_strategy_evaluation.py -q`

Expected: PASS.

### Task 4: Promotion Policy

**Files:**
- Create: `src/domain/lifecycle/promotion_policy.py`
- Modify: `src/domain/lifecycle/__init__.py`
- Test: `tests/domain/lifecycle/test_promotion_policy.py`

**Step 1: Write the failing test**

Add tests for:
- approving an evaluation when status is allowed and all thresholds pass
- rejecting evaluations with disallowed status
- rejecting missing required metrics
- rejecting metrics below threshold

**Step 2: Run test to verify it fails**

Run: `pytest tests/domain/lifecycle/test_promotion_policy.py -q`

Expected: FAIL because `PromotionPolicy` is not implemented yet.

**Step 3: Write minimal implementation**

Implement `PromotionPolicy` as a frozen dataclass with:
- `minimum_metrics: Mapping[str, Decimal]`
- `allowed_statuses: Sequence[StrategyLifecycleStatus]`
- `can_promote(evaluation: StrategyEvaluation) -> bool`

Validation:
- at least one minimum metric is required
- allowed statuses cannot be empty
- threshold metric names are trimmed and cannot be blank
- threshold values are stored as immutable defensive copies

**Step 4: Run test to verify it passes**

Run: `pytest tests/domain/lifecycle/test_promotion_policy.py -q`

Expected: PASS.

### Task 5: Module Verification And Progress Update

**Files:**
- Modify: `docs/progress.md`

**Step 1: Run focused tests**

Run: `pytest tests/domain/lifecycle -q`

Expected: PASS.

**Step 2: Run domain test suite**

Run: `pytest tests/domain -q`

Expected: PASS.

**Step 3: Update progress log**

Update Module I status from `in progress` to `done` and append a `2026-05-24 Module I` work log that references this plan.
