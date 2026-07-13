# Chart-Regime Strategy Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate the BTCUSDT pipeline that clusters the preceding seven-day chart independently of strategy outcomes, maps statistically eligible existing/deferred strategy profiles from the following non-overlapping week, and dynamically selects profiles through the scheduler-driven backtest with four-hour/two-confirmation transitions.

**Architecture:** Add a focused `src/domain/regime` model, application use cases for fitting/mapping/selecting, scikit-learn infrastructure adapters, and atomic SQLite selection-state persistence. Reuse the existing scheduler backtest candidates and trade path; research orchestration prepares frozen JSON artifacts, while the final replay switches complete candidate profiles only for new entries and leaves open-position exits unchanged.

**Tech Stack:** Python 3.14, pandas 2.3.3, scikit-learn 1.9.0, NumPy/SciPy transitively supplied by scikit-learn, SQLite, pytest 9.0.2.

---

## File and Responsibility Map

- `src/domain/regime/chart_features.py`: versioned feature registry and immutable seven-day feature vectors.
- `src/domain/regime/temporal.py`: UTC four-hour boundaries, non-overlapping Monday episodes, and four-interval fold validation.
- `src/domain/regime/model.py`: cluster configuration, fitted artifact, assignment, and stability result contracts.
- `src/domain/regime/mapping.py`: weekly candidate evidence, cash-aware mapping entries, and mapping artifacts.
- `src/domain/regime/selection.py`: persisted selector state, decision/event types, and transition results.
- `src/domain/ports/regime_model_port.py`: inference boundary for a frozen model artifact.
- `src/domain/ports/regime_selection_state_repository_port.py`: atomic/idempotent selector-state persistence boundary.
- `src/application/services/chart_feature_extractor.py`: deterministic 15-minute/one-hour OHLCV aggregation and feature calculation.
- `src/application/usecases/regime/fit_regime_model_usecase.py`: fold-local scaling, correlation pruning, K-Means/GMM fitting, and assignment.
- `src/application/usecases/regime/select_regime_model_usecase.py`: evidence and stability gates independent of strategy results.
- `src/application/usecases/regime/build_strategy_mapping_usecase.py`: weekly statistics, 14-day moving-block bootstrap, candidate-count correction, and cash mapping.
- `src/application/usecases/regime/select_strategy_usecase.py`: high-confidence, two-confirmation, low-confidence, artifact replacement, and cash state machine.
- `src/infrastructure/regime/sklearn_regime_model.py`: scikit-learn training plus deterministic JSON-parameter inference.
- `src/infrastructure/regime/json_regime_artifact_repository.py`: deterministic model/mapping artifact serialization and compatibility checks.
- `src/infrastructure/persistence/repositories/sqlite_regime_selection_state_repository.py`: transactional selector state/event persistence.
- `scripts/chart_regime_strategy_mapping.py`: weekly candidate episode evaluation, fold orchestration, final dynamic replay, and reports.
- `scripts/scheduler_driven_scalping_backtest.py`: expose trade details and add a dynamic candidate-profile replay while retaining current static behavior.
- `tests/domain/regime/*`, `tests/application/usecases/regime/*`, `tests/infrastructure/regime/*`: focused unit tests.
- `tests/test_chart_regime_strategy_mapping.py`: scheduler-driven orchestration and report tests.

## Task 0: Restore a Green Baseline and Add the ML Dependency

**Files:**
- Modify: `requirements.txt`
- Modify: `tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py:349`

- [ ] **Step 1: Update the stale catalog expectation exposed by the baseline run**

Replace the repeated five-item literals with one explicit six-ID set:

```python
expected_ids = {
    "latest-close-moving-average",
    "session-volume-profile",
    "chart-pattern",
    "tv-range-seed-s1-t1-p2-fixed",
    "live-compression-s2-sl0030-rr045-balanced",
    "live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2",
}
assert result.succeeded_count == len(expected_ids)
assert result.failed_count == 0
assert {item.strategy_id for item in result.items} == expected_ids
assert len(repository.saved_evaluations) == len(expected_ids)
assert {evaluation.target_id for evaluation in repository.saved_evaluations} == expected_ids
```

Keep the evaluation-ID assertion and add the sixth `cycle-default:live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2:backtest` value.

- [ ] **Step 2: Run the previously failing test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py::test_default_strategy_catalog_backtest_cycle_succeeds_and_saves_evaluations -q`

Expected: `1 passed`.

- [ ] **Step 3: Pin scikit-learn**

Append this exact requirement:

```text
scikit-learn==1.9.0
```

Run: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`

Expected: scikit-learn 1.9.0 installs for CPython 3.14 and the command exits 0.

- [ ] **Step 4: Verify the baseline**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: `721 passed` or a higher count with zero failures.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/application/usecases/strategy_lifecycle/test_run_strategy_backtest_cycle_usecase.py
git commit -m "test: restore strategy catalog baseline"
```

## Task 1: Define UTC Windows, Weekly Episodes, and Fold Boundaries

**Files:**
- Create: `src/domain/regime/__init__.py`
- Create: `src/domain/regime/temporal.py`
- Create: `tests/domain/regime/__init__.py`
- Create: `tests/domain/regime/test_temporal.py`

- [ ] **Step 1: Write failing tests for boundaries and purges**

```python
def test_four_hour_boundary_is_utc_and_excludes_boundary_observation():
    boundary = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)
    assert is_regime_boundary(boundary)
    assert not is_regime_boundary(boundary + timedelta(minutes=1))
    assert feature_window(boundary) == (
        datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
        boundary,
    )


def test_weekly_mapping_episodes_are_non_overlapping_monday_utc():
    episodes = build_weekly_episodes(
        datetime(2026, 1, 5, tzinfo=timezone.utc),
        datetime(2026, 1, 26, tzinfo=timezone.utc),
    )
    assert [(item.start_at, item.end_at) for item in episodes] == [
        (datetime(2026, 1, 5, tzinfo=timezone.utc), datetime(2026, 1, 12, tzinfo=timezone.utc)),
        (datetime(2026, 1, 12, tzinfo=timezone.utc), datetime(2026, 1, 19, tzinfo=timezone.utc)),
        (datetime(2026, 1, 19, tzinfo=timezone.utc), datetime(2026, 1, 26, tzinfo=timezone.utc)),
    ]


def test_fold_rejects_less_than_seven_day_purge():
    with pytest.raises(ValueError, match="seven-day purge"):
        RegimeWalkForwardFold(
            cluster_fit=UtcInterval(dt("2021-01-01"), dt("2025-07-01")),
            mapping_fit=UtcInterval(dt("2025-07-05"), dt("2026-01-05")),
            validation=UtcInterval(dt("2026-01-12"), dt("2026-03-30")),
            test=UtcInterval(dt("2026-04-06"), dt("2026-07-01")),
        )
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_temporal.py -q`

Expected: FAIL because `src.domain.regime.temporal` does not exist.

- [ ] **Step 3: Implement the temporal contracts**

```python
@dataclass(frozen=True)
class UtcInterval:
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        if self.start_at.utcoffset() != timedelta(0) or self.end_at.utcoffset() != timedelta(0):
            raise ValueError("interval timestamps must be UTC")
        if self.end_at <= self.start_at:
            raise ValueError("interval end must be after start")


@dataclass(frozen=True)
class WeeklyEpisode:
    anchor_at: datetime
    feature_start_at: datetime
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class RegimeWalkForwardFold:
    cluster_fit: UtcInterval
    mapping_fit: UtcInterval
    validation: UtcInterval
    test: UtcInterval

    def __post_init__(self) -> None:
        intervals = (self.cluster_fit, self.mapping_fit, self.validation, self.test)
        for earlier, later in zip(intervals, intervals[1:]):
            if later.start_at - earlier.end_at < timedelta(days=7):
                raise ValueError("every fold boundary requires a seven-day purge")


def is_regime_boundary(value: datetime) -> bool:
    return value.utcoffset() == timedelta(0) and value.minute == 0 and value.second == 0 and value.microsecond == 0 and value.hour % 4 == 0


def feature_window(anchor_at: datetime) -> tuple[datetime, datetime]:
    if not is_regime_boundary(anchor_at):
        raise ValueError("anchor must be a four-hour UTC boundary")
    return anchor_at - timedelta(days=7), anchor_at
```

Implement `build_weekly_episodes` so it requires Monday 00:00 UTC endpoints and returns consecutive, non-overlapping seven-day episodes with `feature_start_at = anchor_at - seven days`.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_temporal.py -q`

Expected: all tests pass.

```bash
git add src/domain/regime tests/domain/regime
git commit -m "feat: define regime temporal contracts"
```

## Task 2: Build the Versioned OHLCV Feature Registry and Extractor

**Files:**
- Create: `src/domain/regime/chart_features.py`
- Create: `src/application/services/__init__.py`
- Create: `src/application/services/chart_feature_extractor.py`
- Create: `tests/domain/regime/test_chart_features.py`
- Create: `tests/application/services/__init__.py`
- Create: `tests/application/services/test_chart_feature_extractor.py`
- Modify: `src/domain/regime/__init__.py`

- [ ] **Step 1: Write failing contract and leakage tests**

```python
def test_feature_registry_has_the_frozen_v1_names():
    assert tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1) == (
        "return_4h", "return_12h", "return_1d", "return_3d", "return_7d",
        "rv_4h", "rv_1d", "rv_7d", "rv_ratio_1d_7d",
        "atr_ratio_1d", "atr_ratio_7d", "range_ratio_7d", "close_location_7d",
        "directional_efficiency_1d", "directional_efficiency_7d",
        "sign_change_rate_1d", "sign_change_rate_7d",
        "return_autocorr_1d", "return_autocorr_7d",
        "max_drawdown_7d", "max_runup_7d", "breakout_rate_7d",
        "mean_body_ratio_7d", "mean_upper_wick_ratio_7d", "mean_lower_wick_ratio_7d",
        "volume_cv_7d", "top_decile_volume_share_7d", "volume_ratio_1d_7d",
    )


def test_extractor_ignores_candle_at_anchor():
    before = make_candles(end_at=ANCHOR, include_anchor=False)
    with_anchor = before + (make_candle(opened_at=ANCHOR, close="999999"),)
    assert extractor.extract(before, ANCHOR) == extractor.extract(with_anchor, ANCHOR)


def test_price_scaling_does_not_change_features():
    original = extractor.extract(make_candles(), ANCHOR)
    scaled = extractor.extract(scale_prices(make_candles(), Decimal("10")), ANCHOR)
    assert original.values == scaled.values
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_chart_features.py tests/application/services/test_chart_feature_extractor.py -q`

Expected: FAIL because registry and extractor are missing.

- [ ] **Step 3: Implement immutable registry types**

```python
@dataclass(frozen=True)
class ChartFeatureSpec:
    name: str
    family: str
    aggregation_minutes: int
    lookback_minutes: int
    formula: str
    null_policy: str = "reject_window"
    clipping_policy: str = "train_quantile_0.005_0.995"
    scale_invariant: bool = True


@dataclass(frozen=True)
class ChartFeatureVector:
    symbol: str
    anchor_at: datetime
    window_start_at: datetime
    schema_version: str
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        if tuple(self.values) != tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1):
            raise ValueError("feature vector does not match registry order")
```

Define all 28 registry entries with schema version `btc-chart-regime-ohclv-v1`. Returns are `close_end / close_start - 1`; realized volatility is the population standard deviation of 15-minute log returns; ATR ratios divide mean true range by close; directional efficiency is absolute net close movement divided by summed absolute close movement; sign-change rate is the fraction of adjacent non-zero returns with opposite signs; autocorrelation is lag-one population correlation; drawdown/runup use the running peak/trough; breakout rate is the fraction of one-hour closes outside the preceding 24-hour high/low; candle ratios divide body/wicks by range; volume features use one-hour base volume.

- [ ] **Step 4: Implement deterministic aggregation and extraction**

`ChartFeatureExtractor.extract(candles, anchor_at)` must:

```python
window = tuple(
    candle for candle in candles
    if anchor_at - timedelta(days=7) <= candle.closed_at < anchor_at
)
if len(window) < 7 * 24 * 60:
    raise ValueError("complete seven-day one-minute history is required")
bars_15m = aggregate_closed_candles(window, minutes=15)
bars_1h = aggregate_closed_candles(window, minutes=60)
return ChartFeatureVector(
    symbol=window[0].symbol.pair,
    anchor_at=anchor_at,
    window_start_at=anchor_at - timedelta(days=7),
    schema_version="btc-chart-regime-ohclv-v1",
    values=calculate_registry_values(bars_15m, bars_1h),
)
```

Reject zero denominators, incomplete aggregation buckets, non-finite results, and candles available at or after the anchor.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_chart_features.py tests/application/services/test_chart_feature_extractor.py -q`

Expected: all tests pass.

```bash
git add src/domain/regime/chart_features.py src/application/services/chart_feature_extractor.py tests/domain/regime/test_chart_features.py tests/application/services/test_chart_feature_extractor.py src/domain/regime/__init__.py
git commit -m "feat: extract seven-day chart regime features"
```

## Task 3: Define Model Artifacts and Fit K-Means/GMM Fold-Locally

**Files:**
- Create: `src/domain/regime/model.py`
- Create: `src/domain/ports/regime_model_port.py`
- Create: `src/infrastructure/regime/__init__.py`
- Create: `src/infrastructure/regime/sklearn_regime_model.py`
- Create: `src/application/usecases/regime/__init__.py`
- Create: `src/application/usecases/regime/fit_regime_model_usecase.py`
- Create: `tests/infrastructure/regime/test_sklearn_regime_model.py`
- Create: `tests/application/usecases/regime/test_fit_regime_model_usecase.py`
- Modify: `src/domain/ports/__init__.py`

- [ ] **Step 1: Write failing tests for fold-local fitting and deterministic assignments**

```python
def test_fit_uses_only_cluster_fit_vectors():
    engine = RecordingClusterEngine()
    result = FitRegimeModelUseCase(engine).execute(
        FitRegimeModelCommand(config=KMEANS_3, cluster_fit_vectors=TRAIN, validation_vectors=VALIDATION)
    )
    assert engine.fitted_anchors == tuple(vector.anchor_at for vector in TRAIN)
    assert result.artifact.training_end_at == TRAIN[-1].anchor_at


def test_gmm_supports_only_diag_and_tied():
    with pytest.raises(ValueError, match="diag or tied"):
        RegimeModelConfig(model_type="gmm", cluster_count=3, covariance_type="full")


def test_correlation_pruning_keeps_registry_priority():
    retained = prune_correlated_features(MATRIX, FEATURE_NAMES, threshold=0.95)
    assert retained == ("return_4h", "rv_1d")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_sklearn_regime_model.py tests/application/usecases/regime/test_fit_regime_model_usecase.py -q`

Expected: FAIL because model contracts are absent.

- [ ] **Step 3: Implement model contracts**

```python
@dataclass(frozen=True)
class RegimeModelConfig:
    model_type: Literal["kmeans", "gmm"]
    cluster_count: int
    random_seed: int = 20260714
    covariance_type: Literal["diag", "tied"] | None = None
    regularization: float = 1e-6


@dataclass(frozen=True)
class ClusterAssignment:
    fingerprint: str
    dominant_probability: float
    second_probability: float
    distance: float | None


@dataclass(frozen=True)
class RegimeModelArtifact:
    artifact_version: str
    symbol: str
    feature_schema_version: str
    config: RegimeModelConfig
    feature_names: tuple[str, ...]
    medians: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    means: tuple[tuple[float, ...], ...]
    covariances: tuple[tuple[float, ...], ...]
    fingerprints: tuple[str, ...]
    training_start_at: datetime
    training_end_at: datetime
```

- [ ] **Step 4: Implement scikit-learn fitting and JSON-parameter inference**

Use `RobustScaler`, `KMeans(n_init=20)`, and `GaussianMixture(n_init=20, covariance_type in {diag,tied})`. Persist scaler/model numeric parameters into `RegimeModelArtifact`; do not pickle estimators. Implement K-Means Euclidean-distance rejection and GMM log-density/posterior inference from artifact arrays with NumPy so artifact loading is version-auditable.

Reject non-convergence, singular covariance, non-finite parameters, duplicate fingerprints, and feature-family dominance above half the retained inputs.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_sklearn_regime_model.py tests/application/usecases/regime/test_fit_regime_model_usecase.py -q`

Expected: all tests pass.

```bash
git add src/domain/regime/model.py src/domain/ports/regime_model_port.py src/domain/ports/__init__.py src/infrastructure/regime src/application/usecases/regime tests/infrastructure/regime tests/application/usecases/regime
git commit -m "feat: fit auditable chart regime models"
```

## Task 4: Gate Cluster Models by Evidence and Stability

**Files:**
- Create: `src/application/usecases/regime/select_regime_model_usecase.py`
- Create: `tests/application/usecases/regime/test_select_regime_model_usecase.py`

- [ ] **Step 1: Write failing model-gate tests**

```python
def test_model_is_rejected_when_one_cluster_has_fewer_than_eight_weekly_episodes():
    result = select_model(CANDIDATE_WITH_COUNTS_20_7_15)
    assert not result.eligible
    assert "minimum_weekly_episodes" in result.rejection_reasons


def test_strategy_results_cannot_enter_model_selection():
    signature = inspect.signature(SelectRegimeModelCommand)
    assert "strategy_results" not in signature.parameters


def test_ordered_gates_precede_information_criterion():
    result = select_model(UNSTABLE_LOW_BIC_CANDIDATE)
    assert not result.eligible
    assert result.rejection_reasons[0] == "seed_stability"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/regime/test_select_regime_model_usecase.py -q`

Expected: FAIL because the selector does not exist.

- [ ] **Step 3: Implement ordered, strategy-independent gates**

Define `RegimeModelEvidence` with weekly episode counts, distinct months, seed ARI/NMI, matched-centroid distance, prevalence drift, low-confidence rate, silhouette, and BIC. Apply gates in this order: minimum eight episodes and three months per cluster; ARI/NMI; centroid distance and prevalence drift; low-confidence rate; then within-family silhouette/BIC ordering. Return every rejection reason and the deterministic winning artifact ID.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/regime/test_select_regime_model_usecase.py -q`

Expected: all tests pass.

```bash
git add src/application/usecases/regime/select_regime_model_usecase.py tests/application/usecases/regime/test_select_regime_model_usecase.py
git commit -m "feat: gate regime models by stability"
```

## Task 5: Expose Weekly Scheduler-Driven Candidate Evidence

**Files:**
- Modify: `scripts/scheduler_driven_scalping_backtest.py:668`
- Modify: `tests/test_scheduler_driven_scalping_backtest.py`
- Create: `scripts/chart_regime_strategy_mapping.py`
- Create: `tests/test_chart_regime_strategy_mapping.py`

- [ ] **Step 1: Write failing tests for trade evidence and weekly isolation**

```python
def test_static_backtest_can_return_trade_details_and_forced_close_cost():
    result = run_scheduler_driven_backtest(
        MARKET, start_at=START, end_at=END, candidate=CANDIDATE, include_trade_details=True
    )
    assert result["trades"][-1]["exit_reason"] == "end_of_data"
    assert Decimal(result["trades"][-1]["fee_paid"]) > 0


def test_mapping_episodes_are_flat_and_non_overlapping(monkeypatch):
    calls = record_episode_backtests(monkeypatch)
    rows = run_mapping_episodes(EPISODES, CANDIDATES, ASSIGNMENTS)
    assert [row["episode_start_at"] for row in rows] == ["2025-07-07T00:00:00+00:00", "2025-07-14T00:00:00+00:00"]
    assert all(call["initial_equity"] == INITIAL_EQUITY for call in calls)
    assert all(call["force_close_at_end"] for call in calls)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scheduler_driven_scalping_backtest.py tests/test_chart_regime_strategy_mapping.py -q`

Expected: FAIL on the new keyword arguments and missing script.

- [ ] **Step 3: Extend static backtest without changing default payloads**

Add keyword-only parameters:

```python
initial_equity: Decimal = INITIAL_EQUITY,
include_trade_details: bool = False,
force_close_at_end: bool = True,
```

Replace internal `INITIAL_EQUITY` calculations with `initial_equity`. When requested, serialize each trade's entry/exit price, direction, quantity, margin, gross/net PnL, fee, exit reason, and holding bars. Keep current callers byte-compatible when `include_trade_details=False`.

- [ ] **Step 4: Implement weekly episode orchestration**

`run_mapping_episodes` must resolve explicitly opted-in deferred candidate groups through the existing candidate factories, start every candidate with identical account/risk inputs, run the real `TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute` path, and emit one row per `(episode, cluster_fingerprint, candidate_id)` including data/candidate hashes.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scheduler_driven_scalping_backtest.py tests/test_chart_regime_strategy_mapping.py -q`

Expected: all tests pass.

```bash
git add scripts/scheduler_driven_scalping_backtest.py scripts/chart_regime_strategy_mapping.py tests/test_scheduler_driven_scalping_backtest.py tests/test_chart_regime_strategy_mapping.py
git commit -m "feat: collect weekly regime strategy evidence"
```

## Task 6: Build Cash-Aware Mappings with Corrected Bootstrap Evidence

**Files:**
- Create: `src/domain/regime/mapping.py`
- Create: `src/application/usecases/regime/build_strategy_mapping_usecase.py`
- Create: `tests/application/usecases/regime/test_build_strategy_mapping_usecase.py`
- Modify: `src/domain/regime/__init__.py`

- [ ] **Step 1: Write failing cash, trade-count, and multiple-comparison tests**

```python
def test_cluster_maps_to_cash_when_no_candidate_has_positive_corrected_lcb():
    artifact = build_mapping(ALL_NEGATIVE_ROWS)
    assert artifact.entries["cluster-a"].strategy_profile_id is None
    assert artifact.entries["cluster-a"].decision == "cash"


def test_candidate_with_fewer_than_thirty_closed_trades_is_ineligible():
    artifact = build_mapping(POSITIVE_BUT_29_TRADES)
    assert artifact.entries["cluster-a"].strategy_profile_id is None
    assert "minimum_trade_count" in artifact.entries["cluster-a"].rejection_reasons


def test_fourteen_day_moving_block_bootstrap_is_deterministic():
    first = corrected_lower_bound(ROWS, random_seed=20260714, resamples=2000)
    second = corrected_lower_bound(ROWS, random_seed=20260714, resamples=2000)
    assert first == second
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/regime/test_build_strategy_mapping_usecase.py -q`

Expected: FAIL because mapping types/use case are absent.

- [ ] **Step 3: Implement mapping contracts and metrics**

```python
@dataclass(frozen=True)
class StrategyMappingEntry:
    cluster_fingerprint: str
    strategy_profile_id: str | None
    decision: Literal["strategy", "cash"]
    weekly_episode_count: int
    distinct_month_count: int
    closed_trade_count: int
    corrected_lower_bound: Decimal
    metrics: Mapping[str, Decimal]
    rejection_reasons: tuple[str, ...] = ()
```

Compute median/10th-percentile/worst-block return, downside deviation, expected shortfall, profit factor, exposure-adjusted return, time in market, `top_5_trade_pnl_share`, `top_1_episode_pnl_share`, and return without the best episode.

- [ ] **Step 4: Implement eligibility and max-statistic correction**

Require eight weekly episodes, three distinct months, thirty closed trades, positive corrected LCB, and non-domination by cash. Resample consecutive pairs of weekly episode rows with a fixed seed. On every resample compute every candidate mean and use the maximum centered statistic across candidates to form the family-wise corrected lower bound. Never select the least-negative candidate.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/regime/test_build_strategy_mapping_usecase.py -q`

Expected: all tests pass.

```bash
git add src/domain/regime/mapping.py src/domain/regime/__init__.py src/application/usecases/regime/build_strategy_mapping_usecase.py tests/application/usecases/regime/test_build_strategy_mapping_usecase.py
git commit -m "feat: map regimes to statistically eligible strategies"
```

## Task 7: Serialize and Validate Frozen Artifacts

**Files:**
- Create: `src/infrastructure/regime/json_regime_artifact_repository.py`
- Create: `tests/infrastructure/regime/test_json_regime_artifact_repository.py`

- [ ] **Step 1: Write failing deterministic round-trip tests**

```python
def test_model_and_mapping_json_round_trip_is_deterministic(tmp_path):
    repository = JsonRegimeArtifactRepository(tmp_path)
    repository.save_model(MODEL)
    repository.save_mapping(MAPPING)
    first = (tmp_path / "model.json").read_bytes()
    repository.save_model(MODEL)
    assert (tmp_path / "model.json").read_bytes() == first
    assert repository.load_model(expected_symbol="BTCUSDT", expected_schema="btc-chart-regime-ohclv-v1") == MODEL


def test_mapping_rejects_candidate_definition_hash_mismatch(tmp_path):
    with pytest.raises(ValueError, match="candidate definition hash"):
        repository.load_mapping(expected_candidate_definition_hash="different")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_json_regime_artifact_repository.py -q`

Expected: FAIL because repository is missing.

- [ ] **Step 3: Implement canonical JSON and compatibility gates**

Serialize with `sort_keys=True`, `separators=(",", ":")`, UTF-8, decimal values as strings, UTC datetimes as ISO 8601, and a SHA-256 over the canonical payload excluding the hash field. Validate symbol, feature schema, model fingerprint, mapping model hash, candidate universe hash, and data provenance hash on load.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_json_regime_artifact_repository.py -q`

Expected: all tests pass.

```bash
git add src/infrastructure/regime/json_regime_artifact_repository.py tests/infrastructure/regime/test_json_regime_artifact_repository.py
git commit -m "feat: persist frozen regime artifacts"
```

## Task 8: Implement the Dynamic Selection State Machine

**Files:**
- Create: `src/domain/regime/selection.py`
- Create: `src/application/usecases/regime/select_strategy_usecase.py`
- Create: `tests/application/usecases/regime/test_select_strategy_usecase.py`
- Modify: `src/domain/regime/__init__.py`

- [ ] **Step 1: Write failing transition tests**

```python
def test_initial_high_confidence_selects_mapped_strategy_immediately():
    result = select(previous=None, assignment=HIGH_A, mapping={"a": "strategy-x"})
    assert result.state.active_strategy_profile_id == "strategy-x"
    assert result.state.new_entries_enabled


def test_new_cluster_requires_two_consecutive_observations():
    first = select(previous=ACTIVE_A, assignment=HIGH_B, mapping=MAPPING)
    assert first.state.active_strategy_profile_id == "strategy-x"
    assert first.state.pending_cluster_fingerprint == "b"
    second = select(previous=first.state, assignment=HIGH_B, mapping=MAPPING)
    assert second.state.active_strategy_profile_id == "strategy-y"


def test_first_low_confidence_disables_entries_and_second_commits_cash():
    first = select(previous=ACTIVE_A, assignment=LOW_CONFIDENCE, mapping=MAPPING)
    assert not first.state.new_entries_enabled
    assert first.state.active_strategy_profile_id == "strategy-x"
    second = select(previous=first.state, assignment=LOW_CONFIDENCE, mapping=MAPPING)
    assert second.state.active_strategy_profile_id is None


def test_cluster_change_to_same_strategy_is_not_strategy_switch():
    result = confirm_transition(A_TO_B_SAME_STRATEGY)
    assert result.events == (SelectionEventType.CLUSTER_TRANSITION,)


def test_artifact_change_requires_two_new_confirmations():
    result = select(previous=OLD_ARTIFACT_STATE, assignment=NEW_ARTIFACT_HIGH_A, mapping=NEW_MAPPING)
    assert not result.state.new_entries_enabled
    assert result.state.pending_confirmation_count == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/regime/test_select_strategy_usecase.py -q`

Expected: FAIL because selection contracts are absent.

- [ ] **Step 3: Implement immutable state and decision types**

```python
@dataclass(frozen=True)
class RegimeSelectionState:
    symbol: str
    artifact_version: str
    current_cluster_fingerprint: str | None
    active_strategy_profile_id: str | None
    pending_cluster_fingerprint: str | None
    pending_confirmation_count: int
    consecutive_low_confidence_count: int
    new_entries_enabled: bool
    last_boundary_at: datetime
    state_version: int


@dataclass(frozen=True)
class SelectStrategyResult:
    expected_state_version: int
    state: RegimeSelectionState
    events: tuple[SelectionEventType, ...]
```

Define `SelectionEventType` values `CLASSIFICATION`, `ENTRY_SUSPENDED`, `CLUSTER_TRANSITION`, `STRATEGY_TRANSITION`, `CASH_TRANSITION`, and `ARTIFACT_REPLACED`.

- [ ] **Step 4: Implement exact confidence and transition rules**

GMM is high-confidence when `dominant >= p_min` and `dominant - second >= margin_min`; K-Means uses the frozen maximum standardized centroid distance. Reject non-boundary/stale timestamps. Apply initial immediate selection, two confirmations for changes, first-low entry suspension, second-low cash, pending reset on candidate change, separate cluster/strategy events, and artifact replacement confirmation exactly as specified.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/usecases/regime/test_select_strategy_usecase.py -q`

Expected: all tests pass.

```bash
git add src/domain/regime/selection.py src/domain/regime/__init__.py src/application/usecases/regime/select_strategy_usecase.py tests/application/usecases/regime/test_select_strategy_usecase.py
git commit -m "feat: select strategies from regime state"
```

## Task 9: Persist Selection State Atomically and Idempotently

**Files:**
- Create: `src/domain/ports/regime_selection_state_repository_port.py`
- Create: `src/infrastructure/persistence/repositories/sqlite_regime_selection_state_repository.py`
- Create: `tests/infrastructure/persistence/test_sqlite_regime_selection_state_repository.py`
- Modify: `src/domain/ports/__init__.py`
- Modify: `src/infrastructure/persistence/repositories/__init__.py`
- Modify: `src/infrastructure/persistence/__init__.py`

- [ ] **Step 1: Write failing retry, stale, and concurrency tests**

```python
def test_same_boundary_retry_returns_original_commit(tmp_path):
    repository = make_repository(tmp_path)
    first = repository.commit(EXPECTED_VERSION_0, DECISION_1)
    retry = repository.commit(EXPECTED_VERSION_0, DECISION_1)
    assert retry == first
    assert repository.list_events("BTCUSDT") == first.events


def test_conflicting_duplicate_boundary_is_rejected(tmp_path):
    repository = make_repository(tmp_path)
    repository.commit(EXPECTED_VERSION_0, DECISION_1)
    with pytest.raises(ValueError, match="conflicting boundary commit"):
        repository.commit(EXPECTED_VERSION_0, DIFFERENT_DECISION_SAME_BOUNDARY)


def test_stale_state_version_cannot_increment_confirmation_twice(tmp_path):
    repository = make_repository(tmp_path)
    repository.commit(0, DECISION_1)
    with pytest.raises(ConcurrentSelectionStateError):
        repository.commit(0, DECISION_2)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/persistence/test_sqlite_regime_selection_state_repository.py -q`

Expected: FAIL because the repository is missing.

- [ ] **Step 3: Implement the port and transactional SQLite tables**

Create `regime_selection_states` keyed by symbol with `state_version`, and `regime_selection_events` with a unique `(symbol, boundary_at, artifact_version)` key plus canonical decision hash. In one `BEGIN IMMEDIATE` transaction: load current version, return the prior identical event on retry, reject conflicting/stale commits, insert events, and update state with `state_version + 1`.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/persistence/test_sqlite_regime_selection_state_repository.py -q`

Expected: all tests pass.

```bash
git add src/domain/ports src/infrastructure/persistence tests/infrastructure/persistence/test_sqlite_regime_selection_state_repository.py
git commit -m "feat: persist regime selection state atomically"
```

## Task 10: Add the Selection Scheduler and Disabled-by-Default Runtime Composition

**Files:**
- Create: `src/interfaces/scheduler/regime_selection_scheduler.py`
- Create: `tests/interfaces/scheduler/test_regime_selection_scheduler.py`
- Modify: `src/interfaces/scheduler/__init__.py`
- Modify: `src/runtime/config.py`
- Modify: `src/runtime/local_composition.py`
- Modify: `tests/runtime/test_runtime_config.py`
- Modify: `tests/runtime/test_local_composition.py`

- [ ] **Step 1: Write failing scheduler and disabled-default tests**

```python
def test_selection_scheduler_commits_usecase_result_once():
    scheduler = RegimeSelectionScheduler(USECASE, REPOSITORY, now=lambda: BOUNDARY)
    first = scheduler.run_selection("btc-regime", lambda: COMMAND)
    retry = scheduler.run_selection("btc-regime", lambda: COMMAND)
    assert first.result == retry.result
    assert REPOSITORY.event_count == 1


def test_runtime_regime_selection_is_disabled_by_default():
    settings = RuntimeSettings()
    composition = LocalRuntimeComposition(settings=settings)
    assert composition.regime_selection_scheduler is None


def test_enabled_runtime_requires_both_artifact_paths():
    with pytest.raises(ValueError, match="regime artifact paths"):
        RuntimeSettings(regime_selection_enabled=True)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/interfaces/scheduler/test_regime_selection_scheduler.py tests/runtime/test_runtime_config.py tests/runtime/test_local_composition.py -q`

Expected: FAIL because scheduler/config fields are absent.

- [ ] **Step 3: Implement the scheduler adapter**

```python
@dataclass(frozen=True)
class ScheduledRegimeSelection:
    schedule_name: str
    started_at: datetime
    finished_at: datetime
    result: SelectStrategyResult | None = None
    error: Exception | None = None


class RegimeSelectionScheduler:
    def __init__(self, usecase, repository, now=_utc_now) -> None:
        self._usecase = usecase
        self._repository = repository
        self._now = now

    def run_selection(self, schedule_name, command_factory) -> ScheduledRegimeSelection:
        started_at = self._now()
        try:
            result = self._usecase.execute(command_factory())
            committed = self._repository.commit(result.expected_state_version, result)
            return ScheduledRegimeSelection(schedule_name, started_at, self._now(), result=committed)
        except Exception as exc:
            return ScheduledRegimeSelection(schedule_name, started_at, self._now(), error=exc)
```

Use structured runtime logging consistent with `TradeScheduler` and surface errors rather than silently selecting a default profile.

- [ ] **Step 4: Wire optional runtime composition without enabling live trading**

Add settings `regime_selection_enabled: bool = False`, `regime_model_artifact_path: str | None`, and `regime_mapping_artifact_path: str | None`. When enabled, load compatible frozen artifacts and construct the use case, SQLite repository, and selection scheduler. Do not alter the configured live trade strategy or automatically enable the selector after a research result.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/interfaces/scheduler/test_regime_selection_scheduler.py tests/runtime/test_runtime_config.py tests/runtime/test_local_composition.py -q`

Expected: all tests pass.

```bash
git add src/interfaces/scheduler src/runtime/config.py src/runtime/local_composition.py tests/interfaces/scheduler/test_regime_selection_scheduler.py tests/runtime/test_runtime_config.py tests/runtime/test_local_composition.py
git commit -m "feat: schedule persisted regime selection"
```

## Task 11: Add Scheduler-Driven Dynamic Candidate Replay

**Files:**
- Modify: `scripts/scheduler_driven_scalping_backtest.py`
- Modify: `tests/test_scheduler_driven_scalping_backtest.py`
- Modify: `scripts/chart_regime_strategy_mapping.py`
- Modify: `tests/test_chart_regime_strategy_mapping.py`

- [ ] **Step 1: Write failing dynamic replay tests**

```python
def test_dynamic_replay_changes_profiles_only_after_two_confirmations():
    result = run_scheduler_driven_regime_backtest(
        MARKET,
        start_at=START,
        end_at=END,
        model=SCRIPTED_ASSIGNMENTS_A_B_B,
        mapping=MAPPING_A_X_B_Y,
        candidates=(PROFILE_X, PROFILE_Y),
    )
    assert [event["type"] for event in result["selection_events"]] == [
        "classification", "classification", "cluster_transition", "strategy_transition"
    ]


def test_cash_mapping_blocks_new_entries_but_keeps_open_position_exit():
    result = run_cash_transition_fixture()
    assert result["trades"][0]["owner_strategy_profile_id"] == "strategy-x"
    assert result["trades"][0]["exit_reason"] == "take_profit"
    assert result["entries_while_cash"] == 0


def test_same_strategy_cluster_transition_does_not_rebuild_scheduler():
    result = run_same_strategy_mapping_fixture()
    assert result["cluster_transition_count"] == 1
    assert result["strategy_transition_count"] == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scheduler_driven_scalping_backtest.py tests/test_chart_regime_strategy_mapping.py -q`

Expected: FAIL because dynamic replay is missing.

- [ ] **Step 3: Implement per-profile scheduler bundles**

Build one reusable bundle per candidate ID containing its guarded signal generator, defensive guard, sizing strategy, TP/SL strategy, and `TradeScheduler`, all sharing the same cursor market data, order execution, signal log, and feature provider. At each four-hour boundary call `RegimeSelectionScheduler.run_selection`; when flat and entries are enabled, invoke only the active bundle. Store `owner_strategy_profile_id`, TP, SL, leverage, and guard attribution on `BacktestPosition`, so later switches cannot alter its exit.

- [ ] **Step 4: Add dynamic replay result fields**

Return continuous equity and portfolio-level maximum drawdown, all trade details, time in cluster/cash, confidence diagnostics, separate cluster/strategy/cash transitions, entry-suspension time, candidate and artifact hashes, and actual turnover/cash/signal-discontinuity effects. Do not add an artificial direct switch fee.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scheduler_driven_scalping_backtest.py tests/test_chart_regime_strategy_mapping.py -q`

Expected: all tests pass.

```bash
git add scripts/scheduler_driven_scalping_backtest.py scripts/chart_regime_strategy_mapping.py tests/test_scheduler_driven_scalping_backtest.py tests/test_chart_regime_strategy_mapping.py
git commit -m "feat: replay dynamic regime strategy selection"
```

## Task 12: Orchestrate the Four-Interval Walk-Forward Pipeline and Reports

**Files:**
- Modify: `scripts/chart_regime_strategy_mapping.py`
- Modify: `tests/test_chart_regime_strategy_mapping.py`
- Create: `docs/backtests/chart-regime-strategy-mapping-btcusdt.json`
- Create: `docs/backtests/chart-regime-strategy-mapping-btcusdt.md`

- [ ] **Step 1: Write failing orchestration and provenance tests**

```python
def test_walk_forward_freezes_artifacts_before_test(monkeypatch):
    events = record_pipeline_events(monkeypatch)
    run_chart_regime_walk_forward(FOLD, candidate_groups=ALL_GROUPS, include_deferred=True)
    assert events.index("mapping_frozen") < events.index("first_test_classification")
    assert "test_result" not in events[:events.index("mapping_frozen")]


def test_report_contains_all_required_baselines():
    payload = run_fixture_pipeline()
    assert set(payload["comparisons"]) == {
        "cash", "adopted_fixed", "train_selected_fixed", "manual_regime_router",
        "kmeans_dynamic", "gmm_dynamic",
    }


def test_result_records_provenance_and_rejected_models():
    payload = run_fixture_pipeline()
    assert payload["feature_schema_version"] == "btc-chart-regime-ohclv-v1"
    assert payload["candidate_universe_hash"]
    assert payload["data_provenance"]
    assert payload["rejected_model_configurations"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_chart_regime_strategy_mapping.py -q`

Expected: FAIL on missing walk-forward orchestration/report keys.

- [ ] **Step 3: Implement the explicit BTC fold and configuration table**

Use this first untouched fold:

```text
Cluster Fit:  2021-01-01T00:00Z .. 2025-06-30T00:00Z
purge:       2025-06-30T00:00Z .. 2025-07-07T00:00Z
Mapping Fit: 2025-07-07T00:00Z .. 2026-01-05T00:00Z
purge:       2026-01-05T00:00Z .. 2026-01-12T00:00Z
Validation:  2026-01-12T00:00Z .. 2026-03-30T00:00Z
purge:       2026-03-30T00:00Z .. 2026-04-06T00:00Z
Test:        2026-04-06T00:00Z .. 2026-07-01T00:00Z
```

Predeclare K-Means/GMM cluster counts 3 through 8, GMM covariance `diag`/`tied`, seeds `(20260714, 20260715, 20260716)`, correlation threshold `0.95`, bootstrap resamples `(2000, 5000)`, confidence levels `(0.90, 0.95)`, and validation candidate grids for `P_MIN`, `MARGIN_MIN`, and K-Means distance rejection. Freeze the selected artifacts before Test.

The CLI accepts repeated `--candidate-group` values, expands them through the existing public candidate factories, canonicalizes by `candidate_id`, accepts exact duplicate definitions once, and rejects conflicting definitions with the same ID before any backtest starts.

- [ ] **Step 4: Implement JSON/Markdown reporting**

Report mapping and continuous-replay metrics separately, every rejected model/mapping reason, cash contribution, fold and strategy concentration, confidence, transitions, provenance, candidate definitions, costs, and all six baselines. Write atomically through a temporary sibling file then `Path.replace`.

- [ ] **Step 5: Run focused and regression tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_chart_regime_strategy_mapping.py tests/test_scheduler_driven_scalping_backtest.py tests/test_incremental_walk_forward_runner.py tests/application/usecases/regime tests/domain/regime tests/infrastructure/regime tests/infrastructure/persistence/test_sqlite_regime_selection_state_repository.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/chart_regime_strategy_mapping.py tests/test_chart_regime_strategy_mapping.py
git commit -m "feat: orchestrate regime mapping walk forward"
```

Do not commit generated BTC reports until Task 13 verifies the real run.

## Task 13: Run the Real BTCUSDT Pipeline and Complete the Evidence Audit

**Files:**
- Generate: `docs/backtests/chart-regime-strategy-mapping-btcusdt.json`
- Generate: `docs/backtests/chart-regime-strategy-mapping-btcusdt.md`
- Generate: `docs/backtests/chart-regime-strategy-mapping-btcusdt-model.json`
- Generate: `docs/backtests/chart-regime-strategy-mapping-btcusdt-mapping.json`
- Modify only if evidence finds a defect: files introduced by Tasks 1-12 and their focused tests

- [ ] **Step 1: Run the real pipeline with all deferred groups explicitly enabled**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\chart_regime_strategy_mapping.py `
  --symbol BTCUSDT `
  --cluster-fit-start 2021-01-01 --cluster-fit-end 2025-06-30 `
  --mapping-fit-start 2025-07-07 --mapping-fit-end 2026-01-05 `
  --validation-start 2026-01-12 --validation-end 2026-03-30 `
  --test-start 2026-04-06 --test-end 2026-07-01 `
  --candidate-group all --candidate-group exact --candidate-group alpha `
  --candidate-group multi --candidate-group microstructure --candidate-group counter `
  --candidate-group metrics --candidate-group discovered `
  --include-deferred `
  --feature-cache-root .research-data\binance-usdm\features\BTCUSDT\1m `
  --output-json docs\backtests\chart-regime-strategy-mapping-btcusdt.json `
  --output-markdown docs\backtests\chart-regime-strategy-mapping-btcusdt.md
```

Expected: exit 0; JSON, Markdown, model, and mapping artifacts exist; the report may conclude failure or cash-only, but no threshold is changed after viewing Test.

- [ ] **Step 2: Audit every explicit goal requirement against generated evidence**

Confirm in the JSON:

```text
BTCUSDT only
strategy-independent seven-day clusters
non-overlapping following-week mapping evidence
existing and explicitly enabled deferred candidates evaluated
cash for every cluster without eligible evidence
initial selection plus four-hour/two-confirmation transitions
scheduler-driven trade path
continuous untouched Test comparison against all baselines
feature/model/mapping/candidate/data provenance
```

- [ ] **Step 3: Run the full verification suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass.

Run: `git diff --check`

Expected: no output and exit 0.

- [ ] **Step 4: Commit the verified evidence**

```bash
git add docs/backtests/chart-regime-strategy-mapping-btcusdt.json docs/backtests/chart-regime-strategy-mapping-btcusdt.md docs/backtests/chart-regime-strategy-mapping-btcusdt-model.json docs/backtests/chart-regime-strategy-mapping-btcusdt-mapping.json
git commit -m "research: evaluate BTC chart regime strategy mapping"
```

- [ ] **Step 5: Record the final outcome without promotion side effects**

Summarize whether K-Means or GMM survived, which clusters mapped to strategy profiles or cash, the untouched OOS return/MDD/turnover evidence, and whether the dynamic system cleared the adoption gate. Do not alter live configuration or remove candidates from the deferred registry.
