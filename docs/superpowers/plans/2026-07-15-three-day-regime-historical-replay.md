# BTCUSDT Three-Day Regime Historical Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay the fixed GMM-diag K=4 and K=8 three-day BTCUSDT cluster fits over 1,274 older daily windows and produce deterministic, independently audited coverage and stability evidence.

**Architecture:** Extract the already verified three-day archive-to-vector path into a generic history loader while preserving the existing 727-window diagnostic byte-for-byte. Add a pure replay-diagnostics service for training-reference confidence, clipping, distribution, and preference metrics, then orchestrate strict source-fit loading and paired reports from a dedicated research CLI. Keep all runtime, strategy, scheduler, and seven-day artifact paths untouched.

**Tech Stack:** Python 3.14, dataclasses, Decimal, NumPy, SciPy, scikit-learn, threadpoolctl, pytest, Binance Vision verified archives.

---

## File Structure

- Create `src/infrastructure/exchange/binance/research_data/three_day_feature_history.py`: generic verified archive streaming and exact daily three-day vector construction.
- Modify `scripts/chart_regime_balance_diagnostic.py`: delegate archive/vector acquisition to the generic loader without changing canonical evidence bytes.
- Create `tests/infrastructure/exchange/binance/research_data/test_three_day_feature_history.py`: generic 727/1,274 history and fail-closed archive tests.
- Create `src/infrastructure/regime/historical_replay_source.py`: strict committed-report hash, schema, candidate, and diagnostic-fit reconstruction.
- Create `tests/infrastructure/regime/test_historical_replay_source.py`: source tampering and K=4/K=8 reconstruction tests.
- Create `src/application/services/regime_historical_replay.py`: immutable confidence, clipping, divergence, and comparison diagnostics.
- Create `tests/application/services/test_regime_historical_replay.py`: independent numerical references and invalid-result tests.
- Create `scripts/chart_regime_historical_replay.py`: CLI, fixed-model replay orchestration, canonical JSON, compact Markdown, and paired atomic publication.
- Create `tests/test_chart_regime_historical_replay.py`: CLI, orchestration, determinism, failure, and direct-entrypoint tests.
- Generate `docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.json` and `.md` only after two real runs match byte-for-byte.

### Task 1: Generalize Verified Three-Day Feature History Loading

**Files:**
- Create: `src/infrastructure/exchange/binance/research_data/three_day_feature_history.py`
- Create: `tests/infrastructure/exchange/binance/research_data/test_three_day_feature_history.py`
- Modify: `scripts/chart_regime_balance_diagnostic.py`
- Modify: `tests/test_chart_regime_balance_diagnostic.py`

- [ ] **Step 1: Write failing generic-history tests**

```python
def test_daily_history_contract_counts_727_and_1274_anchors():
    two_year = build_three_day_history_contract(
        datetime(2024, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    older = build_three_day_history_contract(
        datetime(2021, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 7, 1, tzinfo=timezone.utc),
    )
    assert (len(two_year.episodes), two_year.episodes[0].anchor_at, two_year.episodes[-1].anchor_at) == (
        727, datetime(2024, 7, 4, tzinfo=timezone.utc), datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    assert (len(older.episodes), older.episodes[0].anchor_at, older.episodes[-1].anchor_at) == (
        1274, datetime(2021, 1, 4, tzinfo=timezone.utc), datetime(2024, 6, 30, tzinfo=timezone.utc),
    )


def test_loader_streams_exact_window_and_stable_provenance():
    vectors, provenance = load_three_day_feature_history(
        symbol="BTCUSDT", start=START, end=END, raw_root=RAW,
        expected_anchor_count=EXPECTED, downloader=FIXTURE_DOWNLOADER,
        request_factory=FIXTURE_REQUESTS, row_reader=FIXTURE_ROWS,
    )
    assert len(vectors) == EXPECTED
    assert all(vector.window_start_at == vector.anchor_at - timedelta(days=3) for vector in vectors)
    assert tuple(provenance[0]) == ("period", "url", "sha256", "bytes", "member_identity")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/exchange/binance/research_data/test_three_day_feature_history.py -q`

Expected: collection fails because `three_day_feature_history` does not exist.

- [ ] **Step 3: Implement immutable history contract and generic loader**

```python
@dataclass(frozen=True)
class ThreeDayFeatureHistoryContract:
    start_at: datetime
    end_at: datetime
    episodes: tuple[DailyRegimeEpisode, ...]

    def __post_init__(self) -> None:
        if self.start_at.tzinfo is not timezone.utc or self.end_at.tzinfo is not timezone.utc:
            raise ValueError("history bounds must use canonical UTC")
        if self.start_at.time() != time.min or self.end_at.time() != time.min:
            raise ValueError("history bounds must be midnight UTC")
        if self.episodes != build_daily_regime_episodes(self.start_at, self.end_at):
            raise ValueError("history episodes do not match exact daily bounds")


def load_three_day_feature_history(
    *, symbol: str, start: datetime, end: datetime, raw_root: Path,
    expected_anchor_count: int, downloader: ArchiveDownloader | None = None,
    request_factory=iter_archive_requests, row_reader=iter_zip_csv_rows,
) -> tuple[tuple[ThreeDayChartFeatureVector, ...], tuple[Mapping[str, object], ...]]:
    # Stream verified rows in exact UTC order through one 4,320-candle deque.
    # Extract only contract anchors and reject any count other than expected_anchor_count.
```

Move the window-neutral candle parsing, request identity, checksum/archive validation, continuity, provenance, and vector-boundary behavior from the existing script into this module. Preserve stable provenance field order and reject boolean/noncanonical byte counts, hashes, URLs, members, symbols, duplicate minutes, gaps, and non-finite rows.

- [ ] **Step 4: Add archive and boundary failure tests**

Test checksum mismatch propagation, missing minute, duplicate/reversed minute, wrong request symbol/URL/member, non-midnight bounds, incorrect expected count, out-of-window rows, and a candle at the anchor. The anchor candle must not affect its feature vector.

- [ ] **Step 5: Delegate the existing 727 diagnostic without changing evidence**

Replace `acquire_feature_vectors` internals with a wrapper around `load_three_day_feature_history(..., expected_anchor_count=727)`. Retain its public signature and output shapes so existing tests and callers remain compatible.

- [ ] **Step 6: Verify existing report determinism and regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/infrastructure/exchange/binance/research_data/test_three_day_feature_history.py `
  tests/test_chart_regime_balance_diagnostic.py `
  tests/application/services/test_three_day_chart_feature_extractor.py -q
```

Expected: all pass. Also run the existing cached 727 diagnostic once to temporary outputs and require JSON SHA-256 `2e656b11b89baf412d1f6af3217c8900165d45c14531c28f64795695baaa8f4c` and Markdown SHA-256 `8578e1579e6c3d2fa82c34870369ecc5b17ce069ec95b999d77325d29263c5d2`.

- [ ] **Step 7: Commit**

```powershell
git add src/infrastructure/exchange/binance/research_data/three_day_feature_history.py tests/infrastructure/exchange/binance/research_data/test_three_day_feature_history.py scripts/chart_regime_balance_diagnostic.py tests/test_chart_regime_balance_diagnostic.py
git commit -m "refactor: share three-day feature history loading"
```

### Task 2: Restore Fixed Diagnostic Fits Safely

**Files:**
- Create: `src/infrastructure/regime/historical_replay_source.py`
- Create: `tests/infrastructure/regime/test_historical_replay_source.py`

- [ ] **Step 1: Write failing source-contract tests**

```python
SOURCE_SHA256 = "2e656b11b89baf412d1f6af3217c8900165d45c14531c28f64795695baaa8f4c"


def test_loads_only_fixed_k4_and_k8_diagnostic_fits():
    source = load_historical_replay_source(REPORT, expected_sha256=SOURCE_SHA256)
    assert tuple(source.fits) == ("gmm-diag-k4", "gmm-diag-k8")
    assert source.training_start_at == datetime(2024, 7, 1, tzinfo=timezone.utc)
    assert source.training_end_at == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert all(isinstance(fit, ClusterDiagnosticFit) for fit in source.fits.values())
    assert all(fit.config.model_type == "gmm" and fit.config.covariance_type == "diag" for fit in source.fits.values())
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_historical_replay_source.py -q`

Expected: missing-module import failure.

- [ ] **Step 3: Implement strict source reconstruction**

```python
@dataclass(frozen=True)
class HistoricalReplaySource:
    report_sha256: str
    training_start_at: datetime
    training_end_at: datetime
    registry: tuple[ChartFeatureSpec, ...]
    fits: Mapping[str, ClusterDiagnosticFit]
    training_counts: Mapping[str, Mapping[str, int]]


def load_historical_replay_source(path: Path, *, expected_sha256: str) -> HistoricalReplaySource:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("source diagnostic report hash mismatch")
    payload = json.loads(raw)
    # Validate kind/version/symbol/interval/sample_count/schema/full registry and false outcome flags.
    # Select accepted gmm-diag-k4 and gmm-diag-k8 exactly once.
    # Reconstruct RegimeModelConfig and ClusterDiagnosticFit through their real constructors.
```

Copy every nested numeric sequence into tuples and every map into immutable copied mappings. Recompute fit fingerprints through `ClusterDiagnosticFit`, require candidate identity/config agreement, exact training counts, and no technical rejection. Do not deserialize any runtime artifact type.

- [ ] **Step 4: Add fail-closed tampering tests**

Mutate, one at a time: file hash, kind/version, interval, sample count, strategy flags, registry field, retained name, config identity, mean, covariance, weight, fingerprint, duplicate/missing K4/K8, and candidate status. Every mutation must fail before returning a source.

- [ ] **Step 5: Run focused and artifact-isolation tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/infrastructure/regime/test_historical_replay_source.py `
  tests/infrastructure/regime/test_sklearn_cluster_diagnostic.py `
  tests/infrastructure/regime/test_sklearn_regime_model.py -q
```

Expected: all pass, including frozen seven-day hashes and proof that replay fits are not `RegimeModelArtifact`.

- [ ] **Step 6: Commit**

```powershell
git add src/infrastructure/regime/historical_replay_source.py tests/infrastructure/regime/test_historical_replay_source.py
git commit -m "feat: load fixed historical replay fits"
```

### Task 3: Compute Training-Reference Historical Replay Diagnostics

**Files:**
- Create: `src/application/services/regime_historical_replay.py`
- Create: `tests/application/services/test_regime_historical_replay.py`

- [ ] **Step 1: Write failing clipping and confidence tests**

```python
def test_envelope_diagnostics_count_pre_clipping_exceedances():
    result = summarize_training_envelope(RAW_MATRIX, FEATURE_NAMES, LOWER, UPPER)
    assert result.any_feature_exceedance_count == 2
    assert result.any_feature_exceedance_share == pytest.approx(0.5)
    assert result.per_feature["return_3d"].lower_count == 1
    assert result.clipped_dimension_quantiles == {"p50": 0.5, "p95": 1.0, "max": 1}


def test_training_reference_is_fitted_only_from_training_assignments():
    reference = build_confidence_reference(TRAINING_DIAGNOSTICS, FIT)
    replay = compare_confidence_to_training(HISTORICAL_DIAGNOSTICS, reference)
    assert reference.posterior_fifth_percentile == pytest.approx(EXPECTED_TRAIN_P05)
    assert replay.posterior_below_reference_count == EXPECTED_OLD_LOW_COUNT
    assert replay.component_distance_above_reference_count == EXPECTED_OLD_HIGH_COUNT
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_regime_historical_replay.py -q`

Expected: missing-module import failure.

- [ ] **Step 3: Implement immutable per-anchor GMM diagnostics**

```python
@dataclass(frozen=True)
class ReplayAssignmentDiagnostic:
    anchor_at: datetime
    fingerprint: str
    dominant_probability: float
    probability_margin: float
    mahalanobis_distance: float
    clipped_dimension_count: int


def diagnose_gmm_assignments(
    fit: ClusterDiagnosticFit,
    vectors: Sequence[ThreeDayChartFeatureVector],
    registry: Sequence[ChartFeatureSpec],
) -> tuple[ReplayAssignmentDiagnostic, ...]:
    # Validate fixed GMM-diag fit and vector order.
    # Measure raw envelope exceedance before np.clip.
    # Assign with SklearnClusterDiagnostic and compute winner-specific sqrt Mahalanobis distance.
```

Wrap the complete numerical calculation with `threadpool_limits(1)` and verify thread limits restore. Reject non-diagonal GMM fits, non-finite posterior/margin/distance, unknown fingerprints, and dimension mismatches.

- [ ] **Step 4: Implement training references and comparison metrics**

```python
def build_confidence_reference(training, fingerprints) -> ConfidenceReference:
    # p05 dominant posterior and margin globally.
    # p99.5 assigned Mahalanobis distance separately for every fingerprint.


def jensen_shannon_divergence(training_shares, historical_shares, fingerprints) -> float:
    # Natural-log JSD: 0.5*KL(P||M) + 0.5*KL(Q||M), with zero terms omitted.


def rank_historical_replay_candidates(results):
    return tuple(sorted(results, key=lambda item: (
        item.envelope.any_feature_exceedance_share,
        item.confidence.margin_below_reference_share,
        item.confidence.distance_above_reference_share,
        item.quarter_warning_count,
        -item.effective_sample_sizes.minimum,
        item.jensen_shannon_divergence,
        item.cluster_count,
        item.identity,
    )))
```

Use NumPy's explicit linear quantile method consistently and record it in result metadata. Historical values must never affect reference cutoffs.

- [ ] **Step 5: Integrate overlap-aware distribution diagnostics**

For each model, calculate `summarize_cluster_balance`, fourteen-quarter `quarterly_cluster_counts`, three-day/5,000/95%/seed-20260714 bootstrap intervals, lag-30 `effective_sample_sizes`, training-versus-history JSD, and quarterly zero-count/concentration warnings. Store raw per-anchor diagnostics for audit.

- [ ] **Step 6: Add independent formula, invalid-state, and ranking tests**

Cover posterior margin, diagonal Mahalanobis distance by hand, component-specific p99.5 cutoffs, zero-share JSD, each model's frozen fingerprint ordering, fourteen quarters, reference/historical separation, immutable copies, bool/non-finite rejection, derived-summary recomputation, and every lexicographic tie-break.

- [ ] **Step 7: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/application/services/test_regime_historical_replay.py `
  tests/application/services/test_regime_balance_diagnostics.py `
  tests/infrastructure/regime/test_sklearn_cluster_diagnostic.py -q
```

Expected: all pass deterministically when repeated.

- [ ] **Step 8: Commit**

```powershell
git add src/application/services/regime_historical_replay.py tests/application/services/test_regime_historical_replay.py
git commit -m "feat: measure historical regime replay coverage"
```

### Task 4: Build the Historical Replay CLI and Reports

**Files:**
- Create: `scripts/chart_regime_historical_replay.py`
- Create: `tests/test_chart_regime_historical_replay.py`

- [ ] **Step 1: Write failing CLI and orchestration tests**

```python
def test_defaults_freeze_historical_training_and_source_contracts():
    args = parse_args([])
    assert (args.historical_start, args.historical_end) == (HISTORICAL_START, HISTORICAL_END)
    assert (args.training_start, args.training_end) == (TRAINING_START, TRAINING_END)
    assert args.expected_source_sha256 == SOURCE_SHA256


def test_fixture_replay_uses_1274_old_and_727_training_vectors_without_refit():
    report = run_fixture_replay()
    assert report["historical_sample_count"] == 1274
    assert report["training_reference_sample_count"] == 727
    assert tuple(item["identity"] for item in report["models"]) == ("gmm-diag-k4", "gmm-diag-k8")
    assert report["models_refit"] is False
    assert report["runtime_thresholds_present"] is False
    assert report["historical_cutoffs_fitted"] is False
    assert report["strategy_outcomes_read"] is False
    assert report["strategy_outcomes_evaluated"] is False
    assert report["production_model_selected"] is False
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_chart_regime_historical_replay.py -q`

Expected: missing-script import failure.

- [ ] **Step 3: Implement strict CLI and orchestration**

Defaults:

```text
--symbol BTCUSDT
--historical-start 2021-01-01
--historical-end 2024-07-01
--training-start 2024-07-01
--training-end 2026-07-01
--source-report docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json
--expected-source-sha256 2e656b11b89baf412d1f6af3217c8900165d45c14531c28f64795695baaa8f4c
--raw-kline-root .research-data/binance-usdm/raw/klines
--output-json docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.json
--output-markdown docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.md
```

Load and validate the fixed source, stream 1,274 historical and 727 training-reference vectors, ensure the two intervals are disjoint and adjacent, diagnose both fits without calling `fit`, calculate Task 3 metrics, and rank only as a research preference.

- [ ] **Step 4: Implement canonical JSON and compact Markdown**

JSON must include source/archive hashes, stable provenance separated by interval, exact model fits' fingerprints and configs, reference cutoff metadata, per-anchor diagnostics, aggregate metrics, ranking, and all false flags from the design. Reject all non-finite values recursively.

Markdown must contain a K=4/K=8 comparison table, confidence-reference tails, clipping, JSD, ESS, fourteen-quarter warnings, selected research preference and rationale, plus explicit reverse-time/overlap/no-strategy/no-production limitations. Do not embed full fit matrices or per-anchor rows in Markdown.

- [ ] **Step 5: Reuse paired atomic publication safely**

Use the proven canonical serializer and rollback behavior from `chart_regime_balance_diagnostic.py` through explicit imports, or extract a focused shared helper only with byte-for-byte existing-report regression. Reject exact, lexical, case-normalized, and resolved destination aliases before rendering or directory mutation.

- [ ] **Step 6: Add fail-closed and subprocess determinism tests**

Test source hash/schema/fit tampering, wrong vector count/bounds/symbol, archive checksum/gap/duplicate, historical/training overlap, accidental adapter `fit` call, changed reference cutoff from historical data, non-finite metrics, destination alias, second-replace rollback, cleanup error preservation, direct UTF-8 `--help`, and two subprocess runs under different external thread limits producing identical canonical payload bytes.

- [ ] **Step 7: Run affected and full tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_chart_regime_historical_replay.py `
  tests/test_chart_regime_balance_diagnostic.py `
  tests/application/services/test_regime_historical_replay.py `
  tests/application/services/test_regime_balance_diagnostics.py `
  tests/infrastructure/regime `
  tests/infrastructure/exchange/binance/research_data `
  tests/domain/regime -q
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all pass; record the two known Windows/joblib warnings separately if reproduced.

- [ ] **Step 8: Commit without generated reports**

```powershell
git add scripts/chart_regime_historical_replay.py tests/test_chart_regime_historical_replay.py
git commit -m "feat: add historical regime replay diagnostic"
```

### Task 5: Run, Reproduce, Audit, and Commit Real Historical Evidence

**Files:**
- Generate: `docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.json`
- Generate: `docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.md`
- Modify only after a failing real-data regression: files introduced or touched in Tasks 1-4 and their tests.

- [ ] **Step 1: Run the exact real replay twice**

```powershell
.\.venv\Scripts\python.exe scripts\chart_regime_historical_replay.py `
  --symbol BTCUSDT `
  --historical-start 2021-01-01 --historical-end 2024-07-01 `
  --training-start 2024-07-01 --training-end 2026-07-01 `
  --source-report docs\backtests\chart-regime-balance-btcusdt-3d-1d-2024-2026.json `
  --expected-source-sha256 2e656b11b89baf412d1f6af3217c8900165d45c14531c28f64795695baaa8f4c `
  --raw-kline-root .research-data\binance-usdm\raw\klines `
  --output-json docs\backtests\chart-regime-historical-replay-btcusdt-3d-2021-2024.json `
  --output-markdown docs\backtests\chart-regime-historical-replay-btcusdt-3d-2021-2024.md
```

Run once more to ignored temporary destinations. Require byte-identical JSON and Markdown SHA-256 before continuing.

- [ ] **Step 2: Independently audit evidence**

Recompute archive hashes/bytes/combined hashes, source-report hash, 1,274 and 727 boundaries, all per-anchor labels/posteriors/margins/Mahalanobis distances/clipping counts, training cutoffs, balance/shares/entropy, fourteen quarter tables, bootstrap intervals, ESS, JSD, preference comparator, false flags, and Markdown values/limitations. Confirm no historical value enters a reference cutoff.

- [ ] **Step 3: Run final verification**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: zero failures. Record known environment warnings without suppressing new warnings.

- [ ] **Step 4: Commit only deterministic evidence**

```powershell
git add -f docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.json docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.md
git commit -m "docs: record BTC historical regime replay evidence"
```

- [ ] **Step 5: Request final whole-branch review**

Review from `ebe4c49` through the evidence commit. Require no P0-P2 findings, independent evidence regeneration or calculation, a clean `git diff --check`, a clean worktree, no tracked raw/temp data, and explicit confirmation that seven-day runtime remains unchanged and disabled by default.
