# Deferred Strategy Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record failed strategy research and make those candidate groups opt-in so future agents prioritize new alpha.

**Architecture:** A JSON evidence registry is loaded by one small Python policy module. Both scheduler-driven research entry points call that policy before constructing candidates; strategy factories and domain implementations remain unchanged.

**Tech Stack:** Python 3, argparse, JSON, pytest, Markdown research artifacts.

---

### Task 1: Add the failing policy tests

**Files:**
- Modify: `tests/test_incremental_walk_forward_runner.py`
- Modify: `tests/test_scheduler_driven_scalping_backtest.py`

- [ ] Add tests asserting `_select_candidates("alpha", ())` raises a deferred-group error without opt-in.
- [ ] Add tests asserting `_select_candidates("alpha", (), include_deferred=True)` still constructs the archived candidates.
- [ ] Add registry tests asserting every entry has a status, evidence, reason, and revisit condition.
- [ ] Run `pytest tests/test_incremental_walk_forward_runner.py tests/test_scheduler_driven_scalping_backtest.py -q` and confirm the new tests fail because the gate does not exist.

### Task 2: Implement the registry and selection gate

**Files:**
- Create: `docs/backtests/deferred-strategy-registry.json`
- Create: `scripts/deferred_strategy_registry.py`
- Modify: `scripts/incremental_walk_forward_runner.py`
- Modify: `scripts/scheduler_driven_scalping_backtest.py`

- [ ] Record `exact`, `multi`, `alpha`, `microstructure`, `counter`, `metrics`, `discovered`, and the legacy `all` aggregate with the appropriate `failed`, `superseded`, or `deferred` status.
- [ ] Implement `load_deferred_strategy_registry()` and `ensure_candidate_group_allowed(group, include_deferred=False)`.
- [ ] Add the keyword-only `include_deferred` argument to `_select_candidates` and enforce the policy before candidate construction.
- [ ] Add `--include-deferred` to both CLIs and pass it into the common policy.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Remove redundant research artifacts

**Files:**
- Keep: `docs/backtests/new-entry-alpha-strict-wfv-2026h1-summary.md`
- Keep: `docs/backtests/phase1-phase2-oos-research-summary.md`
- Keep: `docs/backtests/binance-metrics-alpha-research-summary.md`
- Keep: final strict WFV summaries and `discovered-metrics-v2-all.rows.jsonl`
- Delete: obsolete A/B shards, pre-fix discovery outputs, and duplicate family payloads listed by the cleanup audit.

- [ ] Generate the exact deletion list and verify every resolved path is under `docs/backtests`.
- [ ] Delete only untracked intermediate artifacts; do not remove shared code or unrelated user files.
- [ ] Verify that every evidence path in the registry still exists.

### Task 4: Regression verification

**Files:**
- No additional files.

- [ ] Run focused tests for the two backtest entry points.
- [ ] Run the complete pytest suite.
- [ ] Inspect `git diff --check`, `git status --short`, and the retained artifact list.
- [ ] Report any pre-existing unrelated failure separately from this change.
