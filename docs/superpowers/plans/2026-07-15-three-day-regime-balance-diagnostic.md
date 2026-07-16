# BTCUSDT 3-Day Regime Balance Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run an isolated BTCUSDT diagnostic that clusters 727 overlapping three-day chart windows, reports overlap-aware balance and stability statistics, and does not evaluate strategies.

**Architecture:** Add a separate three-day feature domain and extractor, a schema-neutral clustering core shared with the existing seven-day model adapter, an overlap-aware diagnostic service, and a dedicated research CLI. Reuse the existing verified Binance archive downloader and atomic reporting patterns while leaving seven-day runtime artifacts and live composition unchanged.

**Tech Stack:** Python 3.14, dataclasses, Decimal, NumPy, SciPy, scikit-learn KMeans/GaussianMixture, pytest, Binance Vision monthly archives.

---

## File Structure

- Create `src/domain/regime/three_day_chart_features.py`: immutable `3d-v1` registry and daily feature-vector contract.
- Create `src/domain/regime/daily_temporal.py`: exact three-day lookback and one-day outcome anchors.
- Create `src/application/services/three_day_chart_feature_extractor.py`: closed-candle 15-minute/one-hour aggregation and 28 formulas.
- Create `src/domain/regime/cluster_diagnostic.py`: schema-neutral diagnostic fit and balance result types; never loadable by runtime.
- Create `src/infrastructure/regime/sklearn_cluster_core.py`: shared array-level KMeans/GMM fitting and assignment.
- Modify `src/infrastructure/regime/sklearn_regime_model.py`: delegate numerical fitting to the shared core without changing seven-day behavior.
- Create `src/application/services/regime_balance_diagnostics.py`: balance, quarterly, bootstrap, effective-sample-size, seed, and chronological metrics.
- Create `scripts/chart_regime_balance_diagnostic.py`: verified archive streaming, 727-vector construction, model grid, CLI, and atomic reports.
- Create the corresponding focused tests listed below.
- Generate `docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json` and `.md` only after the real run succeeds.

### Task 1: Define Daily Temporal and Three-Day Feature Contracts

**Files:**
- Create: `src/domain/regime/daily_temporal.py`
- Create: `src/domain/regime/three_day_chart_features.py`
- Modify: `src/domain/regime/__init__.py`
- Test: `tests/domain/regime/test_daily_temporal.py`
- Test: `tests/domain/regime/test_three_day_chart_features.py`

- [ ] **Step 1: Write failing temporal tests**

```python
START = datetime(2024, 7, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_build_daily_regime_episodes_reserves_first_three_days_and_727_outcomes():
    episodes = build_daily_regime_episodes(START, END)
    assert len(episodes) == 727
    assert episodes[0] == DailyRegimeEpisode(
        anchor_at=datetime(2024, 7, 4, tzinfo=timezone.utc),
        feature_start_at=START,
        outcome_start_at=datetime(2024, 7, 4, tzinfo=timezone.utc),
        outcome_end_at=datetime(2024, 7, 5, tzinfo=timezone.utc),
    )
    assert episodes[-1].anchor_at == datetime(2026, 6, 30, tzinfo=timezone.utc)
    assert all(
        later.outcome_start_at == earlier.outcome_end_at
        for earlier, later in zip(episodes, episodes[1:])
    )
```

- [ ] **Step 2: Run temporal tests and verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_daily_temporal.py -q`

Expected: import failure for the missing daily temporal module.

- [ ] **Step 3: Implement the exact daily episode contract**

```python
@dataclass(frozen=True)
class DailyRegimeEpisode:
    anchor_at: datetime
    feature_start_at: datetime
    outcome_start_at: datetime
    outcome_end_at: datetime

    def __post_init__(self) -> None:
        values = (self.anchor_at, self.feature_start_at, self.outcome_start_at, self.outcome_end_at)
        if any(value.tzinfo is not timezone.utc for value in values):
            raise ValueError("daily episode timestamps must use canonical UTC")
        if self.anchor_at.time() != time.min:
            raise ValueError("daily anchor must be 00:00 UTC")
        if self.feature_start_at != self.anchor_at - timedelta(days=3):
            raise ValueError("daily feature window must be exactly three days")
        if self.outcome_start_at != self.anchor_at:
            raise ValueError("daily outcome must start at the anchor")
        if self.outcome_end_at != self.anchor_at + timedelta(days=1):
            raise ValueError("daily outcome must be exactly one day")


def build_daily_regime_episodes(start_at: datetime, end_at: datetime) -> tuple[DailyRegimeEpisode, ...]:
    # Require canonical midnight UTC bounds and exact ordered coverage.
    # Anchors begin start_at + 3d and stop before end_at.
```

- [ ] **Step 4: Write failing feature-registry tests**

```python
def test_three_day_registry_is_versioned_and_contains_exact_28_features():
    assert THREE_DAY_CHART_FEATURE_SCHEMA_VERSION == "btc-chart-regime-ohlcv-3d-v1"
    assert tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1) == (
        "return_4h", "return_12h", "return_1d", "return_2d", "return_3d",
        "rv_4h", "rv_1d", "rv_3d", "rv_ratio_1d_3d",
        "atr_ratio_1d", "atr_ratio_3d", "range_ratio_3d", "close_location_3d",
        "directional_efficiency_1d", "directional_efficiency_3d",
        "sign_change_rate_1d", "sign_change_rate_3d",
        "return_autocorr_1d", "return_autocorr_3d",
        "max_drawdown_3d", "max_runup_3d", "breakout_rate_3d",
        "mean_body_ratio_3d", "mean_upper_wick_ratio_3d", "mean_lower_wick_ratio_3d",
        "volume_cv_3d", "top_decile_volume_share_3d", "volume_ratio_1d_3d",
    )


def test_three_day_vector_requires_midnight_anchor_and_three_day_window():
    vector = ThreeDayChartFeatureVector(
        symbol="BTCUSDT", anchor_at=ANCHOR,
        window_start_at=ANCHOR - timedelta(days=3), values=VALUES,
    )
    assert vector.schema_version == THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
```

- [ ] **Step 5: Implement the registry and vector**

Use the existing `ChartFeatureSpec` type, but define a separate ordered registry and `ThreeDayChartFeatureVector`. Validate canonical UTC midnight anchors, exactly three days of lookback, exact registry order, copied immutable values, and finite numbers. Do not relax `ChartFeatureVector` or `CHART_FEATURE_SCHEMA_VERSION`.

- [ ] **Step 6: Run focused and seven-day regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/domain/regime/test_daily_temporal.py `
  tests/domain/regime/test_three_day_chart_features.py `
  tests/domain/regime/test_chart_features.py -q
```

Expected: all pass and the seven-day schema remains `btc-chart-regime-ohclv-v1`.

- [ ] **Step 7: Commit**

```powershell
git add src/domain/regime/daily_temporal.py src/domain/regime/three_day_chart_features.py src/domain/regime/__init__.py tests/domain/regime/test_daily_temporal.py tests/domain/regime/test_three_day_chart_features.py
git commit -m "feat: define three-day regime samples"
```

### Task 2: Extract Exact Three-Day OHLCV Features

**Files:**
- Create: `src/application/services/three_day_chart_feature_extractor.py`
- Test: `tests/application/services/test_three_day_chart_feature_extractor.py`
- Modify: `src/application/services/__init__.py`

- [ ] **Step 1: Write failing closed-window and formula tests**

```python
def test_extracts_exact_three_day_closed_window_without_outcome_candle():
    source = one_minute_candles(ANCHOR - timedelta(days=3), minutes=4321)
    vector = extract_three_day_chart_feature_vector(source, ANCHOR)
    assert vector.window_start_at == ANCHOR - timedelta(days=3)
    assert source[4320].opened_at == ANCHOR
    assert vector == extract_three_day_chart_feature_vector(source[:4320], ANCHOR)


def test_three_day_formulas_match_independent_reference():
    bars_15m, bars_1h = deterministic_three_day_bars()
    actual = calculate_three_day_registry_values(bars_15m, bars_1h)
    expected = independent_three_day_reference(bars_15m, bars_1h)
    assert actual == pytest.approx(expected, rel=1e-12, abs=1e-15)
```

- [ ] **Step 2: Run extractor tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_three_day_chart_feature_extractor.py -q`

Expected: import failure for the missing extractor.

- [ ] **Step 3: Implement closed-candle aggregation and formulas**

Reuse the validated pure helpers from `chart_feature_extractor.py` only where their semantics are window-neutral. The new extractor must require 4,320 contiguous one-minute candles, aggregate to exactly 288 fifteen-minute bars and 72 one-hour bars, and calculate the registry in order. It must slice `[anchor-3d, anchor)` before validation so an outcome candle cannot enter the vector.

```python
def extract_three_day_chart_feature_vector(candles, anchor_at):
    start_at = anchor_at - timedelta(days=3)
    window = tuple(c for c in candles if start_at <= c.opened_at < anchor_at)
    _validate_three_day_window(window, start_at, anchor_at)
    bars_15m = aggregate_closed_candles(window, minutes=15)
    bars_1h = aggregate_closed_candles(window, minutes=60)
    return ThreeDayChartFeatureVector(
        symbol=window[0].symbol.pair,
        anchor_at=anchor_at,
        window_start_at=start_at,
        values=calculate_three_day_registry_values(bars_15m, bars_1h),
    )
```

- [ ] **Step 4: Add failure tests for gaps and degeneracy**

Test a missing minute, duplicate minute, non-UTC timestamp, non-midnight anchor, non-finite OHLCV, zero-range maintenance hour, and wholly flat three-day window. The maintenance hour must contribute zero body/wick ratios; the wholly flat window must still fail a meaningful zero-denominator gate.

- [ ] **Step 5: Run focused plus seven-day extractor tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/application/services/test_three_day_chart_feature_extractor.py `
  tests/application/services/test_chart_feature_extractor.py -q
```

Expected: all pass with no changed seven-day values.

- [ ] **Step 6: Commit**

```powershell
git add src/application/services/three_day_chart_feature_extractor.py src/application/services/__init__.py tests/application/services/test_three_day_chart_feature_extractor.py
git commit -m "feat: extract three-day chart features"
```

### Task 3: Add a Schema-Neutral Diagnostic Clustering Core

**Files:**
- Create: `src/domain/regime/cluster_diagnostic.py`
- Create: `src/infrastructure/regime/sklearn_cluster_core.py`
- Create: `src/infrastructure/regime/sklearn_cluster_diagnostic.py`
- Modify: `src/infrastructure/regime/sklearn_regime_model.py`
- Test: `tests/infrastructure/regime/test_sklearn_cluster_core.py`
- Test: `tests/infrastructure/regime/test_sklearn_cluster_diagnostic.py`
- Modify: `tests/infrastructure/regime/test_sklearn_regime_model.py`

- [ ] **Step 1: Write failing shared-core parity tests**

```python
@pytest.mark.parametrize("config", KMEANS_AND_GMM_CONFIGS)
def test_shared_core_reproduces_existing_seven_day_fit(config):
    vectors = seven_day_vectors()
    before = legacy_reference_fit(config, vectors)
    after = SklearnRegimeModel().fit(config, vectors)
    assert after == before


def test_diagnostic_fit_accepts_three_day_schema_without_runtime_artifact():
    fit = SklearnClusterDiagnostic().fit(CONFIG, THREE_DAY_VECTORS, THREE_DAY_REGISTRY)
    assert fit.schema_version == "btc-chart-regime-ohlcv-3d-v1"
    assert fit.feature_names
    assert not isinstance(fit, RegimeModelArtifact)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_sklearn_cluster_core.py tests/infrastructure/regime/test_sklearn_cluster_diagnostic.py -q`

Expected: imports fail for the missing shared core and diagnostic adapter.

- [ ] **Step 3: Define diagnostic-only immutable types**

```python
@dataclass(frozen=True)
class ClusterDiagnosticFit:
    schema_version: str
    symbol: str
    config: RegimeModelConfig
    feature_names: tuple[str, ...]
    lower_bounds: tuple[float, ...]
    upper_bounds: tuple[float, ...]
    medians: tuple[float, ...]
    scales: tuple[float, ...]
    fingerprints: tuple[str, ...]
    means: tuple[tuple[float, ...], ...]
    weights: tuple[float, ...]
    covariances: tuple[tuple[float, ...], ...]
    distance_thresholds: tuple[float, ...]
```

Validate shapes, finite values, canonical configuration, and fingerprint recomputation. Deliberately omit runtime mapping fields and runtime repository serialization.

- [ ] **Step 4: Extract and use the shared numerical core**

Move only array-level KMeans/GMM fitting, covariance validation, probability/distance assignment, and deterministic component ordering to `sklearn_cluster_core.py`. `SklearnRegimeModel` must continue to own seven-day registry validation and construct the unchanged `RegimeModelArtifact`. `SklearnClusterDiagnostic` accepts an explicit registry and constructs `ClusterDiagnosticFit`.

The generic correlation pruner must validate priority against the supplied registry rather than the seven-day module global:

```python
retained = prune_correlated_features(
    matrix,
    feature_names,
    registry_names=tuple(spec.name for spec in registry),
    threshold=0.95,
)
```

- [ ] **Step 5: Test fixed-feature refits and assignments**

Verify three seeds, explicit retained feature names, block-local clipping/scaling, array-only assignment parity, KMeans distances, GMM probabilities, diag/tied covariance floors, and deterministic fingerprints.

- [ ] **Step 6: Run the full regime-model regression set**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/infrastructure/regime `
  tests/application/usecases/regime `
  tests/domain/regime -q
```

Expected: all pass, including persisted seven-day artifact hashes in existing fixtures.

- [ ] **Step 7: Commit**

```powershell
git add src/domain/regime/cluster_diagnostic.py src/infrastructure/regime/sklearn_cluster_core.py src/infrastructure/regime/sklearn_cluster_diagnostic.py src/infrastructure/regime/sklearn_regime_model.py tests/infrastructure/regime/test_sklearn_cluster_core.py tests/infrastructure/regime/test_sklearn_cluster_diagnostic.py tests/infrastructure/regime/test_sklearn_regime_model.py
git commit -m "refactor: share regime clustering core"
```

### Task 4: Compute Overlap-Aware Balance and Stability Statistics

**Files:**
- Create: `src/application/services/regime_balance_diagnostics.py`
- Test: `tests/application/services/test_regime_balance_diagnostics.py`

- [ ] **Step 1: Write failing balance-metric tests**

```python
def test_balance_metrics_count_assignments_and_normalize_entropy():
    labels = ("a", "a", "b", "c")
    result = summarize_cluster_balance(labels, fingerprints=("a", "b", "c"))
    assert result.counts == {"a": 2, "b": 1, "c": 1}
    assert result.shares == {"a": 0.5, "b": 0.25, "c": 0.25}
    assert result.normalized_entropy == pytest.approx(
        -(0.5 * log(0.5) + 2 * 0.25 * log(0.25)) / log(3)
    )


def test_quarterly_counts_cover_all_727_anchors_once():
    table = quarterly_cluster_counts(EPISODES, LABELS)
    assert tuple(table) == (
        "2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2",
        "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2",
    )
    assert sum(sum(row.values()) for row in table.values()) == 727
```

- [ ] **Step 2: Write failing dependence tests**

```python
def test_moving_block_bootstrap_resamples_contiguous_three_day_blocks():
    result = bootstrap_cluster_share_intervals(
        LABELS, FINGERPRINTS, block_length=3, resamples=5000,
        confidence=0.95, seed=20260714,
    )
    assert result.resamples == 5000
    assert result.block_length == 3
    assert all(interval.lower <= interval.point <= interval.upper for interval in result.intervals.values())


def test_effective_sample_size_penalizes_persistent_assignments():
    alternating = effective_sample_sizes(("a", "b") * 100, ("a", "b"), max_lag=30)
    persistent = effective_sample_sizes(("a",) * 100 + ("b",) * 100, ("a", "b"), max_lag=30)
    assert min(persistent.values()) < min(alternating.values())
```

- [ ] **Step 3: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_regime_balance_diagnostics.py -q`

Expected: import failure for the missing service.

- [ ] **Step 4: Implement pure deterministic statistics**

Implement:

```python
summarize_cluster_balance(labels, fingerprints)
quarterly_cluster_counts(episodes, labels)
bootstrap_cluster_share_intervals(labels, fingerprints, block_length=3, resamples=5000, confidence=0.95, seed=20260714)
effective_sample_sizes(labels, fingerprints, max_lag=30)
rank_balance_candidates(candidates)
```

Moving blocks wrap circularly only within a bootstrap draw and are trimmed to 727 observations. Effective sample size uses cluster one-hot series, paired initial-positive autocorrelation sums, clamps the result to `[1, N]`, and reports the minimum cluster value. Reject missing fingerprints, label-length mismatches, non-finite results, or intervals that do not contain their point estimate.

- [ ] **Step 5: Add seed and chronological stability tests**

Use fixed retained feature names for first-half and second-half refits. Match centroids by projecting block-local means into primary coordinates and applying `linear_sum_assignment`. Report raw seed ARI/NMI, matched distance, and first-half/second-half prevalence drift; do not apply the old weekly episode eligibility gates.

- [ ] **Step 6: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_regime_balance_diagnostics.py -q`

Expected: all pass deterministically on repeated runs.

- [ ] **Step 7: Commit**

```powershell
git add src/application/services/regime_balance_diagnostics.py tests/application/services/test_regime_balance_diagnostics.py
git commit -m "feat: measure overlap-aware cluster balance"
```

### Task 5: Build the Dedicated Diagnostic CLI and Reports

**Files:**
- Create: `scripts/chart_regime_balance_diagnostic.py`
- Create: `tests/test_chart_regime_balance_diagnostic.py`

- [ ] **Step 1: Write failing CLI and orchestration tests**

```python
def test_cli_defaults_to_exact_two_year_btc_interval():
    args = parse_args([])
    assert args.symbol == "BTCUSDT"
    assert args.start == datetime(2024, 7, 1, tzinfo=timezone.utc)
    assert args.end == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_fixture_run_reports_727_anchors_and_all_18_configurations():
    report = run_fixture_diagnostic()
    assert report["sample_count"] == 727
    assert len(report["model_candidates"]) == 18
    assert {candidate["seed"] for candidate in report["model_candidates"]} == {20260714}
    assert sum(candidate["family"] == "kmeans" for candidate in report["model_candidates"]) == 6
    assert sum(candidate["family"] == "gmm" for candidate in report["model_candidates"]) == 12
    assert report["outcome_evaluation"] == "reserved_not_evaluated"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_chart_regime_balance_diagnostic.py -q`

Expected: import failure for the missing script.

- [ ] **Step 3: Implement verified archive streaming**

Use `iter_archive_requests("klines", ...)`, `ArchiveDownloader.download(..., source="klines")`, and `iter_zip_csv_rows`. Convert rows to one-minute `Candle` objects, verify exact UTC continuity, maintain a 4,320-candle deque, and extract only midnight anchors from `build_daily_regime_episodes`.

Record for every archive: URL, checksum-verified SHA-256, byte count, period, and cached/downloaded status. Reject an anchor set other than the exact expected 727.

- [ ] **Step 4: Implement the full model grid and report payload**

Construct exactly 18 primary configurations with seed `20260714`: KMeans for `k=3..8` (6 candidates), plus GMM for `k=3..8` with each of `diag` and regularized `tied` covariance (12 candidates). For stability, refit every configuration with seeds `20260715` and `20260716`; these refits are supporting measurements and must not appear as additional primary candidates. Also perform the two chronological refits specified in Task 4 for every configuration. Assign all 727 vectors, calculate Task 4 statistics, preserve technical rejections, and sort descriptive balance by entropy/min-share/max-share/k without selecting a production model.

The JSON must include a canonical hash for input archives, feature schema/registry, retained-feature decisions, each model and metric payload, and explicit booleans:

```json
{
  "strategy_outcomes_read": false,
  "strategy_outcomes_evaluated": false,
  "production_model_selected": false
}
```

- [ ] **Step 5: Implement atomic JSON and Markdown output**

Write a temporary sibling, flush and `fsync`, then `Path.replace`. Markdown must show each candidate's counts, shares, entropy, minimum effective sample size, quarterly warnings, seed stability, and chronological stability. It must state that 727 overlapping windows are not independent and that no strategy was evaluated.

- [ ] **Step 6: Add fail-closed and direct-entrypoint tests**

Test checksum failure, missing minute, duplicate minute, wrong symbol, non-midnight bounds, wrong anchor count, non-finite metric, exact repeated-run JSON hash, output replacement after success only, and:

```python
subprocess.run(
    [sys.executable, "scripts/chart_regime_balance_diagnostic.py", "--help"],
    cwd=REPOSITORY_ROOT,
    check=True,
)
```

- [ ] **Step 7: Run focused and affected regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_chart_regime_balance_diagnostic.py `
  tests/application/services/test_three_day_chart_feature_extractor.py `
  tests/application/services/test_regime_balance_diagnostics.py `
  tests/infrastructure/regime `
  tests/domain/regime -q
```

Expected: all pass.

- [ ] **Step 8: Commit without generated reports**

```powershell
git add scripts/chart_regime_balance_diagnostic.py tests/test_chart_regime_balance_diagnostic.py
git commit -m "feat: add three-day regime balance diagnostic"
```

### Task 6: Run the Real Two-Year BTC Diagnostic and Audit Evidence

**Files:**
- Generate: `docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json`
- Generate: `docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.md`
- Modify only if a real-data defect is found: files introduced in Tasks 1-5 and their tests.

- [ ] **Step 1: Run the exact real command**

```powershell
.\.venv\Scripts\python.exe scripts\chart_regime_balance_diagnostic.py `
  --symbol BTCUSDT `
  --start 2024-07-01 `
  --end 2026-07-01 `
  --raw-kline-root .research-data\binance-usdm\raw\klines `
  --output-json docs\backtests\chart-regime-balance-btcusdt-3d-1d-2024-2026.json `
  --output-markdown docs\backtests\chart-regime-balance-btcusdt-3d-1d-2024-2026.md
```

Expected: exit 0, exactly 727 anchors, 18 model records, no strategy result fields, and both reports written atomically.

- [ ] **Step 2: Audit the generated evidence**

Independently recompute:

- archive and report hashes;
- 727 anchor boundaries;
- cluster counts summing to 727;
- shares summing to one;
- normalized entropy;
- all eight quarterly totals;
- three-day moving-block interval inputs;
- per-cluster effective sample sizes;
- seed ARI/NMI and chronological matching evidence;
- descriptive ranking order.

Confirm the report does not claim independence, strategy performance, model adoption, or untouched OOS trading evidence.

- [ ] **Step 3: Run the full repository suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass; record known environment warnings separately.

- [ ] **Step 4: Commit the ignored evidence files explicitly**

```powershell
git add -f docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.md
git commit -m "docs: record three-day BTC regime balance evidence"
```

- [ ] **Step 5: Request final whole-branch review**

Review from commit `40bf4ba` through the evidence commit. Require no P0-P2 findings, a clean `git diff --check`, a clean worktree, and explicit confirmation that the seven-day runtime remains disabled by default and unchanged by this diagnostic.
