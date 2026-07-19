# Daily Evidence Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make daily evidence locking crash-safe, ledger appends linear, provenance immutable and complete, feature requirements exhaustive, MAE semantically correct, and the application service independent of executable scripts.

**Architecture:** The application service owns pure manifest/evidence/ledger primitives and accepts a frozen dependency contract supplied by orchestration. A dedicated advisory-lock file remains on disk but ownership is exclusively the operating-system lock; each ledger instance incrementally validates file tails into an in-memory index. Canonical scheduler factories and replay wiring remain in `scripts/chart_regime_strategy_mapping.py`.

**Tech Stack:** Python 3 standard library (`fcntl`/`msvcrt`, JSONL, dataclasses), pytest, existing scheduler/domain types.

---

### Task 1: OS-managed evidence lock

**Files:**
- Modify: `src/application/services/daily_strategy_evidence.py`
- Test: `tests/application/services/test_daily_strategy_evidence.py`

- [ ] Add tests showing a leftover lock file is immediately acquirable, a live holder times out, concurrent processes never overlap, and a killed holder releases automatically.
- [ ] Run focused lock tests and record the expected failures caused by the create/delete lockfile protocol.
- [ ] Implement nonblocking `fcntl.flock`/`msvcrt.locking` retry, metadata-after-lock, and unlock/close without unlinking.
- [ ] Re-run focused lock tests.

### Task 2: Incremental ledger index

**Files:**
- Modify: `src/application/services/daily_strategy_evidence.py`
- Test: `tests/application/services/test_daily_strategy_evidence.py`

- [ ] Add instrumentation tests for one full parse across a large seed plus append tail, external-tail incorporation, and replacement/truncation rebuild.
- [ ] Run focused tests and record quadratic/full-rescan failures.
- [ ] Cache validated rows by key, file identity, verified byte offset, parsed bytes, and full-parse count; validate only a grown tail under lock.
- [ ] Update own append state after fsync and sort only the public `load()` result.
- [ ] Re-run ledger tests.

### Task 3: Complete immutable provenance binding

**Files:**
- Modify: `src/application/services/daily_strategy_evidence.py`
- Test: `tests/application/services/test_daily_strategy_evidence.py`

- [ ] Add manifest requirement/provenance drift and mutating-provider tests.
- [ ] Run tests and record missing manifest binding/mutable-provider failures.
- [ ] Add `candidate_manifest_hash` to identity payload/digest and validate it before resume or availability.
- [ ] Snapshot provider identity once, compare identity and replay to that snapshot, then re-snapshot after replay to reject mutation.
- [ ] Re-run provenance tests.

### Task 4: Exhaustive kind-based feature requirements

**Files:**
- Modify: `src/application/services/daily_strategy_evidence.py`
- Modify: `scripts/chart_regime_strategy_mapping.py`
- Test: `tests/application/services/test_daily_strategy_evidence.py`

- [ ] Add a test covering every canonical candidate strategy kind and an unknown-kind rejection test.
- [ ] Run tests and record permissive class-name fallback failures.
- [ ] Replace built-strategy/class-name inference with a typed, exhaustive `StrategyCandidateSpec.kind` requirement registry, including router/composite recursion from spec params.
- [ ] Re-run exhaustive requirement tests.

### Task 5: MAE entry-close semantics

**Files:**
- Modify: `scripts/scheduler_driven_scalping_backtest.py`
- Test: `tests/test_scheduler_driven_scalping_backtest.py`

- [ ] Add a giant entry-candle wick test that must not affect MAE.
- [ ] Run it and record the entry-candle inclusion failure.
- [ ] Slice candles from `opened_index + 1` through the exit candle and document the conservative whole-exit-candle convention.
- [ ] Re-run long, short, exit-candle, and execution tests.

### Task 6: Dependency inversion and canonical wrapper

**Files:**
- Modify: `src/application/services/daily_strategy_evidence.py`
- Modify: `src/application/services/__init__.py`
- Modify: `scripts/chart_regime_strategy_mapping.py`
- Test: `tests/application/services/test_daily_strategy_evidence.py`
- Test: `tests/test_chart_regime_strategy_mapping.py`

- [ ] Add import-isolation and canonical-wrapper contract tests.
- [ ] Run tests and record the current `scripts.*` import/cycle failure.
- [ ] Define pure candidate/replay dependency dataclasses or protocols in the application service and require factories, registry provenance, hashes, engine/cost/timeframe, warmup, and replay explicitly.
- [ ] Move no-argument canonical construction/wiring to the chart orchestration script and remove lazy application-service exports.
- [ ] Re-run service and chart tests.

### Task 7: Final verification and commit

**Files:**
- Verify all modified files.

- [ ] Run all Task 3, incremental, chart, scheduler, domain, and Task 2 regression suites.
- [ ] Run `py_compile`, `git diff --check`, inspect status/diff, and report parse instrumentation.
- [ ] Commit as `fix: scale and harden daily evidence ledger`.
