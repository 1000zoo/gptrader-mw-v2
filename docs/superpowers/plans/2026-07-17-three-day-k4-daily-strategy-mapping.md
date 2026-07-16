# Three-Day K4 Daily Strategy Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a leakage-safe BTCUSDT research pipeline that fits fold-local K4 chart regimes from the preceding three days, maps statistically credible existing/deferred strategies from the following day, and completes an untouched scheduler-driven daily-selection backtest with cash fallback.

**Architecture:** Add parallel three-day/daily research contracts beside the existing seven-day/weekly production contracts, reuse the verified feature extraction, candidate factories, scheduler execution, costs, and accounting, and expose the new behavior only through an explicit `three-day-daily-k4-v1` research profile. Mapping evidence is resumable and hash-bound; the final continuous replay selects at UTC midnight and lets the newly active strategy close an inherited position only with an opposite signal while preserving the entry owner's hard risk ceilings.

**Tech Stack:** Python 3.14, scikit-learn 1.9.0, NumPy/SciPy, Decimal accounting, JSON/JSONL, pytest 9.0.2.

---

## Invariants and Frozen Experiment Values

The implementation must preserve these constants in one profile object and serialize them into every artifact/report:

```python
PROFILE_ID = "three-day-daily-k4-v1"
RANDOM_SEED = 20260714
MODEL_TYPE = "gmm"
COVARIANCE_TYPE = "diag"
CLUSTER_COUNT = 4
REGULARIZATION = 1e-6
BOOTSTRAP_BLOCK_DAYS = 7
BOOTSTRAP_RESAMPLES = 5_000
BOOTSTRAP_CONFIDENCE = 0.95
MIN_EPISODES = 30
MIN_CALENDAR_MONTHS = 3
MIN_CLOSED_TRADES = 30
```

The strict risk policy is fixed before Test:

```python
STRICT_RISK_POLICY = {
    "minimum_worst_seven_day_return_ratio": Decimal("-0.03"),
    "minimum_expected_shortfall_10_ratio": Decimal("-0.01"),
    "maximum_drawdown_ratio": Decimal("0.10"),
    "maximum_top_episode_profit_share": Decimal("0.40"),
    "maximum_top_five_trade_profit_share": Decimal("0.60"),
}
```

Only these two sensitivity policies may be reported on Validation; they may not replace the strict policy used for the untouched Test:

```python
SENSITIVITY_POLICIES = {
    "tighter": {"worst_7d": "-0.02", "es10": "-0.0075", "mdd": "0.075", "top_day": "0.35", "top5": "0.55"},
    "looser": {"worst_7d": "-0.04", "es10": "-0.015", "mdd": "0.125", "top_day": "0.45", "top5": "0.65"},
}
```

The normative UTC intervals are Cluster Fit `[2021-01-01, 2025-06-30)`, Mapping Fit `[2025-07-07, 2026-01-01)`, Validation `[2026-01-04, 2026-04-01)`, and untouched Test `[2026-04-04, 2026-07-01)`. No Test read is allowed before model, candidate universe, policy, mapping, and fixed-strategy baseline identities are frozen.

## File and Responsibility Map

- `src/domain/regime/three_day_daily_profile.py`: research-only chronology, K4 configuration, risk-policy, and artifact contracts.
- `src/domain/regime/daily_mapping.py`: daily evidence, eligibility assessment, cash-aware mapping entry, and mapping artifact.
- `src/application/usecases/regime/build_daily_strategy_mapping_usecase.py`: aligned calendar-day moving-block max-stat correction and deterministic winner selection.
- `src/application/usecases/regime/select_daily_strategy_usecase.py`: midnight-only immediate strategy/cash selection using existing state/result types.
- `src/application/services/daily_strategy_evidence.py`: one-day isolated scheduler runs, feature-availability exclusions, and resumable hash-bound JSONL rows.
- `src/infrastructure/regime/three_day_k4_model_artifact.py`: deterministic K4 diagnostic-fit serialization, fingerprint assignments, compatibility, and hashing.
- `src/interfaces/scheduler/regime_selection_scheduler.py`: widen the selector dependency to a protocol; retain current behavior.
- `scripts/scheduler_driven_scalping_backtest.py`: share candidate bundles and add research-only daily dynamic replay plus exit-only active-strategy signals.
- `scripts/chart_regime_strategy_mapping.py`: explicit profile CLI, data loading, fold-local fitting, freeze barrier, baselines, reporting, and atomic publication.
- `scripts/audit_three_day_k4_daily_mapping.py`: independent evidence and report recomputation.
- Focused tests listed in each task; existing seven-day tests are permanent regression guards.

## Task 1: Freeze the Research-Only Chronology and Artifact Contracts

**Files:**
- Create: `src/domain/regime/three_day_daily_profile.py`
- Create: `src/domain/regime/daily_mapping.py`
- Modify: `src/domain/regime/__init__.py`
- Create: `tests/domain/regime/test_three_day_daily_profile.py`
- Create: `tests/domain/regime/test_daily_mapping.py`

- [ ] **Step 1: Write failing chronology tests**

Test canonical UTC midnight boundaries, exact normative intervals, a seven-day Cluster Fit purge, three-day later purges, and failure for overlap or non-midnight bounds:

```python
def test_default_fold_has_approved_half_open_intervals_and_purges():
    fold = ThreeDayDailyWalkForwardFold.default()
    assert fold.cluster_fit == UtcInterval(dt("2021-01-01"), dt("2025-06-30"))
    assert fold.mapping_fit == UtcInterval(dt("2025-07-07"), dt("2026-01-01"))
    assert fold.validation == UtcInterval(dt("2026-01-04"), dt("2026-04-01"))
    assert fold.test == UtcInterval(dt("2026-04-04"), dt("2026-07-01"))


def test_fold_rejects_less_than_three_day_outcome_purge():
    fold = ThreeDayDailyWalkForwardFold.default()
    with pytest.raises(ValueError, match="three-day purge"):
        replace(
            fold,
            validation=UtcInterval(dt("2026-01-03"), fold.validation.end_at),
        )
```

Add a regression test proving `RegimeWalkForwardFold` still requires its original seven-day semantics.

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_three_day_daily_profile.py -q`

Expected: import failure because the research profile does not exist.

- [ ] **Step 3: Implement immutable profile/fold contracts**

Implement `ThreeDayDailyResearchProfile`, `ThreeDayDailyWalkForwardFold`, and `DailyRiskPolicy`. Validate finite values, `K=4`, diagonal GMM, exact three-day windows, midnight UTC, non-overlap, purges, and the frozen seed/bootstrap constants. Keep these types independent of `RegimeModelArtifact`, `StrategyMappingArtifact`, and `RegimeWalkForwardFold` so no seven-day schema is weakened.

- [ ] **Step 4: Write failing daily mapping contract tests**

Cover exact one-day evidence intervals with a matching cluster anchor, explicit cash entries with rejection reasons, exactly four unique component fingerprints, model/candidate-universe hash compatibility, and rejection of non-finite assessment statistics.

- [ ] **Step 5: Implement daily evidence and mapping types**

Add `DailyStrategyEvidence`, `DailyCandidateAssessment`, `DailyStrategyMappingEntry`, and `DailyStrategyMappingArtifact`. Evidence includes candidate/component IDs, one-day interval, all return/trade/risk/concentration fields, availability status/reason, candidate/model/data/cost/engine hashes, and optional trade PnLs. Artifacts include four entries, frozen policy, fit intervals, universe hash, model hash, schema/profile versions, and canonical payload hashing.

- [ ] **Step 6: Run GREEN and regression tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_three_day_daily_profile.py tests/domain/regime/test_daily_mapping.py tests/domain/regime/test_temporal.py tests/domain/regime/test_daily_temporal.py -q`

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add src/domain/regime/three_day_daily_profile.py src/domain/regime/daily_mapping.py src/domain/regime/__init__.py tests/domain/regime/test_three_day_daily_profile.py tests/domain/regime/test_daily_mapping.py
git commit -m "feat: define three-day daily research contracts"
```

## Task 2: Build Strict Daily Mapping Statistics with Cash Fallback

**Files:**
- Create: `src/application/usecases/regime/build_daily_strategy_mapping_usecase.py`
- Modify: `src/application/usecases/regime/__init__.py`
- Create: `tests/application/usecases/regime/test_build_daily_strategy_mapping_usecase.py`

- [ ] **Step 1: Write RED tests for aligned moving-block inference**

Build deterministic synthetic calendar matrices and assert that bootstrap blocks contain seven consecutive calendar days rather than seven filtered cluster rows; max-stat correction includes every coverage-eligible candidate in a component; an identical seed is byte-deterministic; and a positive naive lower bound can fail after correction.

The bootstrap algorithm is normative: preserve the full ordered Mapping Fit calendar; draw circular starts and concatenate seven-calendar-day blocks until the original length; apply each candidate's availability mask and the frozen component labels; center candidate returns under zero; compute a studentized conditional-mean statistic per candidate; take the maximum statistic across coverage-eligible candidates for each resample; and use its 95th percentile as the shared component critical value. A resample lacking component observations for any tested candidate is redrawn deterministically. Zero-variance positive streams receive an infinite test statistic only when every observed net return is strictly positive; all-zero or mixed zero-variance streams fail.

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/regime/test_build_daily_strategy_mapping_usecase.py -q`

Expected: import failure.

- [ ] **Step 3: Implement deterministic statistics**

Implement private pure functions for aligned block indices, expected shortfall (mean of worst `ceil(10%)` observations), compounded worst seven-calendar-day block, drawdown, positive-profit concentration shares, corrected lower bounds, and lexicographic ordering. Use `Decimal` at domain/report boundaries and finite `float64` arrays only inside bootstrap calculations.

- [ ] **Step 4: Write RED eligibility/ranking tests**

Test every gate separately: 29 episodes, two months, 29 trades, non-positive after costs, corrected LCB `<= 0`, worst block below `-3%`, ES10 below `-1%`, MDD above `10%`, non-positive return without best day, top-day share above `40%`, top-five-trade share above `60%`, and cash domination. Add ties that prove the exact winner order:

```text
corrected LCB desc -> return without best day desc -> ES10 desc -> MDD asc
-> median daily return desc -> candidate_id asc
```

- [ ] **Step 5: Implement `BuildDailyStrategyMappingUseCase`**

The use case accepts a frozen model hash, ordered candidate manifest, ordered calendar, component assignments, and evidence. It returns all assessments plus exactly four strategy/cash entries. Excluded candidate-days remain in audit counts but never become zero returns. It rejects duplicate/conflicting rows, missing calendar labels, post-fit dates, hash drift, or a candidate not in the frozen manifest.

- [ ] **Step 6: Run GREEN plus old weekly mapping regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/regime/test_build_daily_strategy_mapping_usecase.py tests/application/usecases/regime/test_build_strategy_mapping_usecase.py -q`

Expected: all pass and the weekly bootstrap behavior is unchanged.

- [ ] **Step 7: Commit**

```powershell
git add src/application/usecases/regime/build_daily_strategy_mapping_usecase.py src/application/usecases/regime/__init__.py tests/application/usecases/regime/test_build_daily_strategy_mapping_usecase.py
git commit -m "feat: map daily regime evidence with strict correction"
```

## Task 3: Freeze the 282-Candidate Universe and Add Resumable Daily Evidence

**Files:**
- Create: `src/application/services/daily_strategy_evidence.py`
- Modify: `src/application/services/__init__.py`
- Modify: `scripts/incremental_walk_forward_runner.py`
- Modify: `scripts/chart_regime_strategy_mapping.py`
- Create: `tests/application/services/test_daily_strategy_evidence.py`
- Modify: `tests/test_incremental_walk_forward_runner.py`
- Modify: `tests/test_chart_regime_strategy_mapping.py`

- [ ] **Step 1: Write RED candidate-universe tests**

Assert that explicit research opt-in expands all public current/deferred factories, canonicalizes identical duplicates, rejects conflicting IDs, and freezes exactly 282 unique candidates for the current repository snapshot. Assert the manifest contains candidate payload/hash, required feature set, deferred group/status, and a canonical universe hash. The count assertion is a deliberate drift alarm; an intentional catalog change must update the test and create a new experiment identity.

- [ ] **Step 2: Implement `build_three_day_daily_candidate_manifest()`**

Reuse `build_scheduler_candidates()` and deferred registry authorization. Never mutate registry status. Sort by `candidate_id`, compute hashes with `candidate_payload()`/`candidate_definition_hash()`, and fail before reading Validation/Test on any conflict or count drift.

- [ ] **Step 3: Write RED ledger tests**

Cover atomic append, lock recovery, truncated-final-row quarantine, idempotent identical duplicate, conflicting duplicate rejection, and invalidation on candidate/model/market/cache/cost/engine/profile hash changes. The key is:

```python
(run_identity, phase, outcome_start_at, component_fingerprint, candidate_id)
```

- [ ] **Step 4: Extract the generic append-only ledger without changing old rows**

Move/share the lock and JSONL primitives from `scripts/incremental_walk_forward_runner.py` through `daily_strategy_evidence.py`; keep adapter functions and all existing incremental-runner tests green. A row is appended only after a complete one-day result has been canonicalized and fsynced.

- [ ] **Step 5: Write RED one-day evidence tests**

Use a tiny market and fake feature provider to prove every candidate/day starts with fresh equity/guard/position state, warm-up precedes the outcome, entries stop at the half-open end, an open position is closed with normal end-of-data costs, unavailable point-in-time features produce an exclusion row, and no state leaks to the next day/candidate.

- [ ] **Step 6: Implement `run_daily_strategy_evidence()`**

Call the canonical `run_scheduler_driven_backtest` once per eligible candidate/day with `force_close_at_end=True` and `include_trade_details=True`. Derive required warm-up with `required_warmup_candles`; retain trade-level PnLs for concentration; compute exposure/turnover/adverse-excursion only from canonical replay details; and append a hash-bound row. Resume by loading only rows with the exact run identity and fail on mixed identities.

- [ ] **Step 7: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_daily_strategy_evidence.py tests/test_incremental_walk_forward_runner.py tests/test_chart_regime_strategy_mapping.py -q`

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add src/application/services/daily_strategy_evidence.py src/application/services/__init__.py scripts/incremental_walk_forward_runner.py scripts/chart_regime_strategy_mapping.py tests/application/services/test_daily_strategy_evidence.py tests/test_incremental_walk_forward_runner.py tests/test_chart_regime_strategy_mapping.py
git commit -m "feat: add resumable daily strategy evidence"
```

## Task 4: Fit, Serialize, and Validate the Fold-Local K4 Model

**Files:**
- Create: `src/infrastructure/regime/three_day_k4_model_artifact.py`
- Modify: `src/infrastructure/regime/__init__.py`
- Modify: `scripts/chart_regime_strategy_mapping.py`
- Create: `tests/infrastructure/regime/test_three_day_k4_model_artifact.py`
- Modify: `tests/test_chart_regime_strategy_mapping.py`

- [ ] **Step 1: Write RED artifact tests**

Assert deterministic serialization/hash, exact three-day registry compatibility, four unique component fingerprints, finite scaler/GMM values, covariance floor, assignment equivalence after deserialize, and rejection of model/index/feature/provenance drift. A component fingerprint is the SHA-256 of its canonical original-feature-space mean, variance, and weight; numeric sklearn labels are internal only.

- [ ] **Step 2: Implement `ThreeDayK4ModelArtifact`**

Wrap the existing `ClusterDiagnosticFit` without loosening `RegimeModelArtifact`. Store scaler parameters, retained feature order, GMM weights/means/diagonal covariances, convergence metadata, fit interval, source/registry hashes, K4 constants, component fingerprints, assignment-confidence policy, and artifact hash. Provide deterministic `assign(vector)` reconstruction.

- [ ] **Step 3: Write RED fit/data-loader tests**

Use spies to prove the loader supplies only `[2021-01-01, 2025-06-30)` vectors to fitting, three-day classification windows exclude their anchors, Mapping/Validation outcomes cannot influence the fit, and corrupted archives/cache fail before fit. Test that enriched features are never present in the clustering matrix.

- [ ] **Step 4: Implement the research loader and K4 fit**

Reuse `three_day_feature_history` and verified Binance archive/cache contracts. Fit `SklearnClusterDiagnostic` with diagonal GMM K4, seed `20260714`, and regularization `1e-6`. Compute convergence, finite/covariance/weight, chronology representation, seed-refit ARI/NMI, chronological-block centroid/prevalence drift, confidence, and feature-family-cap gates using the already audited historical-replay utilities. If any fixed gate fails, emit failed-model/cash status and never evaluate Test.

- [ ] **Step 5: Run GREEN plus historical K4 regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_three_day_k4_model_artifact.py tests/infrastructure/regime/test_sklearn_cluster_diagnostic.py tests/test_chart_regime_historical_replay.py tests/test_chart_regime_strategy_mapping.py -q`

Expected: all pass and prior K4/K8 historical evidence behavior is unchanged.

- [ ] **Step 6: Commit**

```powershell
git add src/infrastructure/regime/three_day_k4_model_artifact.py src/infrastructure/regime/__init__.py scripts/chart_regime_strategy_mapping.py tests/infrastructure/regime/test_three_day_k4_model_artifact.py tests/test_chart_regime_strategy_mapping.py
git commit -m "feat: fit fold-local three-day K4 artifact"
```

## Task 5: Add Immediate UTC-Midnight Selection Without Changing Production Selection

**Files:**
- Create: `src/application/usecases/regime/select_daily_strategy_usecase.py`
- Modify: `src/application/usecases/regime/__init__.py`
- Modify: `src/interfaces/scheduler/regime_selection_scheduler.py`
- Create: `tests/application/usecases/regime/test_select_daily_strategy_usecase.py`
- Modify: `tests/interfaces/scheduler/test_regime_selection_scheduler.py`

- [ ] **Step 1: Write RED daily selector tests**

Assert midnight-only execution, exactly 4,320 closed candles, immediate mapped strategy activation, immediate cash, low-confidence/unknown-component cash, idempotent same-boundary commits, cluster-only transition when the candidate is unchanged, and fail-closed behavior for stale or incompatible artifacts. Assert no pending/two-confirmation state is created.

- [ ] **Step 2: Implement `SelectDailyStrategyUseCase`**

Reuse `SelectStrategyCommand`, `RegimeSelectionState`, `RegimeSelectionEvent`, `SelectStrategyResult`, and `SelectionArtifactSnapshot`. Require `boundary.hour == boundary.minute == boundary.second == 0`, assign through `ThreeDayK4ModelArtifact`, resolve the daily mapping snapshot, and commit the target immediately. Cash is `None`/the existing cash sentinel consistently with `SelectionArtifactSnapshot`.

- [ ] **Step 3: Widen scheduler dependency structurally**

Introduce a small `RegimeSelectorPort` protocol exposing `execute(command) -> SelectStrategyResult`; type `RegimeSelectionScheduler` against it. Do not alter scheduling, repository transaction, idempotency, or error behavior.

- [ ] **Step 4: Run GREEN plus production selector regressions**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/regime/test_select_daily_strategy_usecase.py tests/application/usecases/regime/test_select_strategy_usecase.py tests/interfaces/scheduler/test_regime_selection_scheduler.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/application/usecases/regime/select_daily_strategy_usecase.py src/application/usecases/regime/__init__.py src/interfaces/scheduler/regime_selection_scheduler.py tests/application/usecases/regime/test_select_daily_strategy_usecase.py tests/interfaces/scheduler/test_regime_selection_scheduler.py
git commit -m "feat: select daily regime strategy immediately"
```

## Task 6: Add Continuous Daily Scheduler Replay and Active-Strategy Exit Ownership

**Files:**
- Modify: `scripts/scheduler_driven_scalping_backtest.py`
- Modify: `tests/test_scheduler_driven_scalping_backtest.py`

- [ ] **Step 1: Write RED position-transition tests**

Script assignments/signals around midnight and assert that a switch never force-closes; entry-owner TP/SL/max holding remain immutable; an active opposite signal closes in exit-only mode; same-direction/WAIT holds; cash emits no discretionary close; and an opposite exit cannot reverse or re-enter on the same candle.

Also assert the exit trade records selection boundary, component fingerprint, previous/active candidate, signal ID/direction, position direction, normal fill/cost/PnL, and reason `active_strategy_opposite_signal`.

- [ ] **Step 2: Extract shared candidate signal evaluation**

Extend `_RegimeCandidateBundle` with its guarded signal generator (or a focused `evaluate_signal` callable) so entry and exit-only evaluation use the same point-in-time candles, candidate warm-up, strategies, feature provider, and guard configuration. Exit-only evaluation must never call position sizing or order placement.

- [ ] **Step 3: Implement `run_scheduler_driven_daily_regime_backtest()`**

Copy no accounting formulas. Extract and reuse the current regime replay's bundle construction, fills, close accounting, drawdown, and report assembly. At each midnight call `RegimeSelectionScheduler` with the three-day vector and daily selector; apply the result to later candle decisions. With an open position, evaluate in this order: immutable owner TP/SL/max-holding; active non-cash exit-only signal; then continue to the next candle. An active opposite close always suppresses entry for the closing candle.

Support an explicit `position_exit_policy` enum with only `entry_owner_only` and `active_strategy_opposite`; the former supplies the required baseline and the latter is the approved dynamic policy. Keep `run_scheduler_driven_regime_backtest()` unchanged.

- [ ] **Step 4: Add report/accounting tests**

Prove transition counts, cash share, signal attempts, guard skips, opposite-exit count/PnL, trade/equity arithmetic, and deterministic event ordering. Assert the production four-hour/two-confirmation replay returns its pre-change golden payload.

- [ ] **Step 5: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scheduler_driven_scalping_backtest.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts/scheduler_driven_scalping_backtest.py tests/test_scheduler_driven_scalping_backtest.py
git commit -m "feat: replay daily regime selection with active exits"
```

## Task 7: Orchestrate Freeze, Validation, Baselines, Reports, and Atomic Publication

**Files:**
- Modify: `scripts/chart_regime_strategy_mapping.py`
- Modify: `tests/test_chart_regime_strategy_mapping.py`
- Modify: `tests/test_scheduler_driven_scalping_backtest.py`

- [ ] **Step 1: Write RED CLI/profile tests**

Add `--profile three-day-daily-k4-v1`, `--evidence-rows-path`, four output-path options, and `--resume`. Assert the default existing invocation still selects the seven-day path and that three-day parameters are rejected without the explicit profile.

- [ ] **Step 2: Implement stage orchestration and freeze barrier**

Run stages in this exact order:

```text
verify sources -> fit/freeze K4 -> freeze 282 candidates -> Mapping Fit evidence
-> strict mapping -> Validation/sensitivity report -> freeze final strict policy/mapping
-> select/freeze global fixed baseline -> load untouched Test -> run comparisons -> publish
```

Create a canonical `pre_test_freeze_hash` from the model, candidate manifest, strict policy, Mapping Fit + Validation evidence identities, final mapping, and global fixed candidate. The Test loader requires this hash and records the first Test read after it exists. No Test-derived object is accepted by any pre-Test function.

- [ ] **Step 3: Define Validation and final-freeze behavior in tests**

Validation reports the frozen strict policy plus tighter/looser sensitivity results, but the untouched Test always uses `STRICT_RISK_POLICY`. Rebuild the final mapping from Mapping Fit plus Validation only under strict policy. Select the global fixed baseline by the same strict coverage/statistical gates without conditioning on component; use the same lexicographic order and cash if none qualifies. Test that changing Test returns cannot change any frozen hash or candidate.

- [ ] **Step 4: Add all Test comparisons**

Run and label:

```text
cash
current_adopted_fixed
pre_test_global_best_fixed
k4_dynamic_entry_owner_exit
k4_dynamic_active_strategy_opposite_exit
existing_manual_regime_router
```

All use identical Test data/costs. Resolve the current adopted profile from the existing repository constant/config and record its canonical hash; do not silently substitute another candidate if unavailable. The manual router uses its existing public backtest path.

- [ ] **Step 5: Write RED deterministic publication tests**

Cover four destinations, exact/normalized/resolved/reserved/symlink/directory/special-file alias rejection before mutation, temp cleanup, rollback after replacement failure, rollback-error annotation, and byte-identical rendering. Model and mapping artifacts are included in the same recoverable publication transaction as JSON/Markdown.

- [ ] **Step 6: Implement canonical JSON/Markdown outputs**

Write:

```text
docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily.json
docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily.md
docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json
docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-mapping.json
```

The JSON includes provenance, intervals, manifests/hashes, assignments, evidence summaries/rejections, validation sensitivity, freeze hash, comparisons, events/trades/equity, safety flags, and output hashes. The Markdown includes K4 component summaries, mapping/cash reasons, untouched comparison, active-exit effect, concentration, and limitations. Normalize UTC/Decimal ordering and never emit NaN/Infinity.

- [ ] **Step 7: Run integration GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_chart_regime_strategy_mapping.py tests/test_scheduler_driven_scalping_backtest.py -q`

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add scripts/chart_regime_strategy_mapping.py tests/test_chart_regime_strategy_mapping.py tests/test_scheduler_driven_scalping_backtest.py
git commit -m "feat: orchestrate three-day K4 mapping experiment"
```

## Task 8: Add an Independent Audit and Preserve Every Existing Default

**Files:**
- Create: `scripts/audit_three_day_k4_daily_mapping.py`
- Create: `tests/test_audit_three_day_k4_daily_mapping.py`
- Modify: `tests/test_chart_regime_strategy_mapping.py`
- Modify: `tests/test_live_strategy_scheduler.py`

- [ ] **Step 1: Write RED independent-audit tests**

The audit must reject one-at-a-time mutations to an archive/cache hash, feature vector, model parameter/fingerprint, candidate hash, evidence return/trade, component assignment, corrected LCB, cash/winner mapping, freeze hash, Test transition, opposite exit, equity/MDD, baseline, and report output hash. Assert Test timestamps never appear in pre-Test evidence lineage.

- [ ] **Step 2: Implement the standalone auditor**

The auditor reads raw verified inputs plus the four outputs, reconstructs rather than imports orchestration conclusions, recomputes all listed values, and prints a canonical audit JSON with `passed`, checked counts, hashes, and failures. It may reuse pure domain math and the canonical scheduler engine but not report summaries or cached assessment fields.

- [ ] **Step 3: Add default-safety tests**

Assert `regime_selection_enabled` remains `False`, local composition still constructs the original seven-day selector only when explicitly enabled, existing four-hour cadence/two-confirmation behavior is unchanged, no three-day artifact is auto-loaded, and the deferred registry remains unchanged after research runs.

- [ ] **Step 4: Run focused and full verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_audit_three_day_k4_daily_mapping.py tests/test_live_strategy_scheduler.py tests/test_chart_regime_strategy_mapping.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: focused tests pass; full suite has zero failures (the existing intentional skip/warnings may remain).

- [ ] **Step 5: Commit**

```powershell
git add scripts/audit_three_day_k4_daily_mapping.py tests/test_audit_three_day_k4_daily_mapping.py tests/test_chart_regime_strategy_mapping.py tests/test_live_strategy_scheduler.py
git commit -m "test: audit daily K4 mapping pipeline"
```

## Task 9: Execute the Real BTCUSDT Experiment Twice and Publish Evidence

**Files:**
- Create: `docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily.json`
- Create: `docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily.md`
- Create: `docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json`
- Create: `docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-mapping.json`
- Create (resumable, normally not committed): `.agents/backtest-cache/three-day-k4-daily-evidence.jsonl`

- [ ] **Step 1: Verify local data coverage before compute**

Run the profile's dry-run/manifest mode and require complete raw OHLCV coverage from `2020-12-29T00:00Z` through `2026-07-01T00:00Z`, point-in-time enriched-cache coverage for each candidate/day, exact source checksums, 282 frozen candidates, and an estimated episode/run count. Missing optional candidate features create audited exclusions; missing clustering/Test OHLCV fails the experiment.

- [ ] **Step 2: Run the complete resumable experiment**

Run:

```powershell
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
.\.venv\Scripts\python.exe scripts/chart_regime_strategy_mapping.py --profile three-day-daily-k4-v1 --symbol BTCUSDT --include-deferred --resume --evidence-rows-path .agents/backtest-cache/three-day-k4-daily-evidence.jsonl
```

Expected: K4 passes or produces an explicit failed-model/cash report; Mapping Fit/Validation finish without hash conflicts; untouched Test comparisons complete; all four outputs are published atomically.

- [ ] **Step 3: Run the independent audit**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/audit_three_day_k4_daily_mapping.py --report docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily.json
```

Expected: `passed: true`, no leakage failures, and all evidence/report counts and hashes match.

- [ ] **Step 4: Prove subprocess determinism under different thread limits**

Copy the first four outputs to a temporary verification directory, then rerun with `OMP_NUM_THREADS=2` and `MKL_NUM_THREADS=2` using the same verified ledger. Compare SHA-256 for JSON, Markdown, model, and mapping files byte-for-byte. Any mismatch is a failure to diagnose; do not publish or claim completion.

- [ ] **Step 5: Run final repository verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
git status --short
```

Expected: zero test failures, no whitespace errors, and only the intended four evidence files (plus any intentional code changes already committed) remain.

- [ ] **Step 6: Commit reproducible evidence**

```powershell
git add docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily.json docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily.md docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-mapping.json
git commit -m "docs: publish BTCUSDT daily K4 mapping evidence"
```

## Final Review Checklist

- [ ] Every production change was preceded by a failing focused test.
- [ ] The old seven-day model/mapping schemas, selector cadence, confirmation state machine, and runtime default remain unchanged.
- [ ] K4 uses Cluster Fit only; strategy outcomes never affect components.
- [ ] All 282 candidate identities are frozen before Validation/Test.
- [ ] Mapping uses non-overlapping daily outcomes and aligned seven-calendar-day max-stat correction.
- [ ] Every cluster may map to cash; no winner is forced.
- [ ] Daily transitions do not force-close positions; hard owner risk remains immutable.
- [ ] Active-strategy opposite exits cannot pyramid, reverse, or re-enter on the same candle.
- [ ] The Test loader is behind a verifiable pre-Test freeze barrier.
- [ ] Six comparisons use identical costs/data and the global fixed winner is pre-Test selected.
- [ ] Four outputs are atomic, byte-deterministic across thread limits, and independently audited.
- [ ] Full pytest and `git diff --check` pass immediately before the completion claim.
