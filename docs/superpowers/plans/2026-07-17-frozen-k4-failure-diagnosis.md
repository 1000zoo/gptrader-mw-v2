# Frozen K4 Failure Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce the frozen BTCUSDT three-day K4 model's two failed gate values without changing the model, then publish a deterministic, leakage-safe decomposition of the responsible components, features, tails, and OOD samples.

**Architecture:** A standalone CLI reads the failed primary model attempt and provenance-bound Cluster Development archives through a local-only adapter. Pure diagnostic services replay exactly two historical half fits, gate all further analysis on exact/tolerant reproduction, and then compute descriptive decompositions with fixed assignments. A renderer stages a deterministic run directory, validates hashes and schemas, and atomically renames it into `docs/backtests/frozen_k4_failure_diagnosis/`.

**Tech Stack:** Python 3.14, NumPy, SciPy, scikit-learn, immutable dataclasses, canonical JSON/CSV/Markdown, pytest.

---

## File map

- Create `src/domain/regime/frozen_k4_failure_diagnostics.py`: immutable contracts, canonical identities, reproduction checks, and output-row validation.
- Create `src/infrastructure/regime/frozen_k4_diagnostic_source.py`: local-only model/source loader with archive and interval enforcement.
- Create `src/application/services/frozen_k4_failure_replay.py`: exact half-refit, projection, Hungarian matching, and primary OOD reproduction.
- Create `src/application/services/frozen_k4_failure_decomposition.py`: fixed-assignment robust location, tail, Gaussian distance, clipping, and offset analysis.
- Create `scripts/diagnose_frozen_three_day_k4_failure.py`: CLI, access audit, rendering, deterministic run ID, and atomic publication.
- Create focused tests mirroring each file plus a real local-source CLI integration test.
- Create the real evidence directory under `docs/backtests/frozen_k4_failure_diagnosis/<run_id>/` only after all code tests pass.

Existing experiment, auditor, mapping, selector, registry, and Test code remain unchanged unless a failing regression proves an extraction is strictly necessary.

## Task 1: Define immutable diagnostic contracts

**Files:**
- Create: `src/domain/regime/frozen_k4_failure_diagnostics.py`
- Create: `tests/domain/regime/test_frozen_k4_failure_diagnostics.py`

- [ ] **Step 1: Write RED tests for reproduction and identity contracts**

Add tests for exact-bit comparison, `math.isclose` tolerance, canonical SHA-256 validation, half labels, diagnostic-only flags, strict OOD numerator/denominator, and forbidden non-finite values.

```python
def test_metric_reproduction_records_bits_tolerance_and_errors():
    result = MetricReproduction.compare(2.3526219570607076, 2.3526219570607076)
    assert result.exact_bit_match is True
    assert result.numeric_tolerance_match is True
    assert result.absolute_error == 0.0


def test_metric_reproduction_rejects_value_outside_frozen_tolerance():
    result = MetricReproduction.compare(2.3526219570607076, 2.3526219571)
    assert result.numeric_tolerance_match is False
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_frozen_k4_failure_diagnostics.py -q
```

Expected: collection fails because the new module and types do not exist.

- [ ] **Step 3: Implement the minimal immutable types**

Define at least:

```python
@dataclass(frozen=True)
class MetricReproduction:
    expected_value: float
    reproduced_value: float
    exact_bit_match: bool
    numeric_tolerance_match: bool
    absolute_error: float
    relative_error: float

    @classmethod
    def compare(cls, expected: float, reproduced: float) -> "MetricReproduction":
        exact = struct.pack(">d", expected) == struct.pack(">d", reproduced)
        absolute = abs(reproduced - expected)
        relative = absolute / abs(expected) if expected else absolute
        return cls(
            expected, reproduced, exact,
            math.isclose(reproduced, expected, rel_tol=1e-12, abs_tol=1e-12),
            absolute, relative,
        )
```

Also define validated contracts for the input identity manifest, half-fit receipt, matched pair, OOD row, sensitivity row, diagnosis status, and final manifest. All public payload methods return deterministic plain mappings and tuples, never mutable internal dictionaries.

- [ ] **Step 4: Run the domain tests and verify GREEN**

Expected: all new domain tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add src/domain/regime/frozen_k4_failure_diagnostics.py tests/domain/regime/test_frozen_k4_failure_diagnostics.py
git commit -m "feat: define frozen K4 diagnosis contracts"
```

## Task 2: Load only provenance-bound Cluster Development inputs

**Files:**
- Create: `src/infrastructure/regime/frozen_k4_diagnostic_source.py`
- Create: `tests/infrastructure/regime/test_frozen_k4_diagnostic_source.py`
- Modify: `src/infrastructure/regime/__init__.py`

- [ ] **Step 1: Write RED local-source and access-boundary tests**

Create real miniature Binance-style ZIP fixtures. Assert the loader verifies URL basename, ZIP member, byte count, SHA-256, one-minute continuity, 4,320-minute feature windows, exact 1,641-anchor manifest shape in the production-profile test, and float64 feature order. Assert it rejects:

- missing or mutated archives;
- extra ZIP members or path traversal;
- anchors at or after `2025-06-30T00:00:00Z`;
- Mapping, Validation, Evidence, candidate, or Test material in the input payload;
- network fallback when a local file is absent.

```python
def test_loader_never_fetches_missing_cluster_archive(monkeypatch, fixture):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_: pytest.fail("network"))
    fixture.archive.unlink()
    with pytest.raises(FileNotFoundError):
        load_frozen_k4_diagnostic_source(fixture.model, fixture.raw_root)
```

- [ ] **Step 2: Run loader tests and verify RED**

Expected: module import failure.

- [ ] **Step 3: Implement a local-only source adapter**

The adapter must:

```python
@dataclass(frozen=True)
class FrozenK4DiagnosticSource:
    attempt_payload: Mapping[str, object]
    primary_fit: ClusterDiagnosticFit
    vectors: tuple[ThreeDayChartFeatureVector, ...]
    identity: FrozenK4InputIdentity
```

Parse the primary fit from the published failed-model attempt rather than fitting it. Use the attempt's exact `source_provenance` to locate local archives and inject a downloader that cannot access the network into the existing three-day feature loader. Derive canonical hashes for primary parameters, scaler, clipping bounds, feature schema, source anchors, vectors, and dependencies.

- [ ] **Step 4: Verify loader GREEN and existing artifact regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_frozen_k4_diagnostic_source.py tests/infrastructure/regime/test_three_day_k4_model_artifact.py -q
```

- [ ] **Step 5: Commit Task 2**

```powershell
git add src/infrastructure/regime/frozen_k4_diagnostic_source.py src/infrastructure/regime/__init__.py tests/infrastructure/regime/test_frozen_k4_diagnostic_source.py
git commit -m "feat: load frozen K4 diagnostic inputs offline"
```

## Task 3: Reproduce the temporal and OOD failures exactly

**Files:**
- Create: `src/application/services/frozen_k4_failure_replay.py`
- Create: `tests/application/services/test_frozen_k4_failure_replay.py`

- [ ] **Step 1: Write RED projection, matching, and OOD tests**

Tests must prove the reproduction uses:

```python
raw = half_mean * half_scale + half_median
clipped = np.clip(raw, primary_lower, primary_upper)
projected = (clipped - primary_median) / primary_scale
```

Add an adversarial fixture where omitting the primary clipping changes the matched pair. Assert fingerprint identity remains stable when display component indices are permuted. Assert OOD uses strict `distance > threshold`, not `>=`, and stores integer numerator and denominator.

- [ ] **Step 2: Run replay tests and verify RED**

Expected: module import failure.

- [ ] **Step 3: Implement exactly two diagnostic half fits**

Implement:

```python
def replay_frozen_k4_failures(source: FrozenK4DiagnosticSource) -> FrozenK4Replay:
    half_a, half_b = split_exactly(source.vectors, split_at=UTC_2023_04_01)
    fits = tuple(
        SklearnClusterDiagnostic().fit(
            source.primary_fit.config,
            half,
            THREE_DAY_CHART_FEATURE_REGISTRY_V1,
            retained_feature_names=source.primary_fit.feature_names,
        )
        for half in (half_a, half_b)
    )
    # project with primary clipping, Hungarian-match, and preserve all receipts
```

Do not import the main orchestration's conclusion object. Reuse only the low-level diagnostic fitter and independently implement the already frozen projection/matching formulas. Fit count must be asserted as exactly two.

Assign all 1,641 vectors to the parsed frozen primary fit and independently reconstruct the squared-Mahalanobis exceedance rate with the frozen chi-square rule.

- [ ] **Step 4: Add the reproduction barrier**

If either expected metric fails `math.isclose(..., rel_tol=1e-12, abs_tol=1e-12)`, return a terminal replay status and do not expose half assignments to decomposition consumers.

Tests must inject separate vector, split, preprocessing, fit, projection, matching, and dependency mutations and assert the correct mismatch classification.

- [ ] **Step 5: Run replay and existing K4 fit tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/services/test_frozen_k4_failure_replay.py tests/test_chart_regime_strategy_mapping.py -q
```

- [ ] **Step 6: Commit Task 3**

```powershell
git add src/application/services/frozen_k4_failure_replay.py tests/application/services/test_frozen_k4_failure_replay.py
git commit -m "feat: replay frozen K4 failure gates"
```

## Task 4: Decompose drift, tails, component distances, and offsets

**Files:**
- Create: `src/application/services/frozen_k4_failure_decomposition.py`
- Create: `tests/application/services/test_frozen_k4_failure_decomposition.py`

- [ ] **Step 1: Write RED formula tests**

Use small hand-computable diagonal Gaussian fixtures to test:

- squared Euclidean contribution ratios;
- coordinate median, 10% trimmed mean, and medoid;
- clipped-sample identification and lower/upper direction;
- removal of 1, 3, 5, and farthest 1% with stable anchor tie-breaks;
- pooled Mahalanobis with `(primary_variance + empirical_half_variance) / 2` and `1e-6` floor;
- symmetric KL, Bhattacharyya, and diagonal Wasserstein-2;
- per-component OOD counts and per-feature Mahalanobis contributions;
- all offsets `0..2` and `0..6` without another fit.

```python
def test_sensitivity_rows_cannot_claim_refitted_model():
    row = sensitivity_for_fixed_assignments(...)
    assert row.assignment_source == "frozen_reproduced_half_assignment"
    assert row.refit_after_exclusion is False
    assert row.diagnostic_only is True
```

- [ ] **Step 2: Run decomposition tests and verify RED**

Expected: module import failure.

- [ ] **Step 3: Implement pure decomposition functions**

No function in this module may import or call a fit method. Accept only a successful `FrozenK4Replay` plus immutable input vectors. Explicitly produce:

- matched-pair and cluster summary rows;
- feature-contribution rows;
- OOD sample rows;
- covariance-aware distance rows;
- robust-location and exclusion sensitivity payloads;
- spaced-anchor offset payloads;
- an evidence-based cause classification that may contain multiple causes.

- [ ] **Step 4: Add no-refit and no-later-data guards**

Monkeypatch `SklearnClusterDiagnostic.fit` to fail and prove decomposition remains GREEN. Recursively scan decomposition inputs and outputs for dates at or after the Mapping boundary and forbidden strategy/Test keys.

- [ ] **Step 5: Run decomposition tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/services/test_frozen_k4_failure_decomposition.py -q
```

- [ ] **Step 6: Commit Task 4**

```powershell
git add src/application/services/frozen_k4_failure_decomposition.py tests/application/services/test_frozen_k4_failure_decomposition.py
git commit -m "feat: decompose frozen K4 drift and OOD"
```

## Task 5: Render and atomically publish the diagnostic run

**Files:**
- Create: `scripts/diagnose_frozen_three_day_k4_failure.py`
- Create: `tests/test_diagnose_frozen_three_day_k4_failure.py`

- [ ] **Step 1: Write RED CLI and renderer tests**

Test exact CSV headers and ordering, canonical JSON, UTF-8 Markdown, deterministic float formatting, required ten-question introduction, file hashes, deterministic run ID, and single-thread environment capture.

Test both terminal paths:

- reproduction success publishes six evidence files plus `manifest.json`;
- reproduction failure publishes only JSON, Markdown, and `manifest.json`.

Inject write/rename failures and assert no partial final run directory appears.

- [ ] **Step 2: Run CLI tests and verify RED**

Expected: script import failure.

- [ ] **Step 3: Implement CLI orchestration**

Expose:

```text
--model-attempt
--raw-kline-root
--output-root
--expected-centroid-distance
--expected-ood-rate
```

Defaults bind to the published BTCUSDT frozen result. Reject alternate expected values unless an explicit test-only dependency is injected; the public CLI cannot redefine the frozen failure.

- [ ] **Step 4: Implement deterministic publication**

Derive `run_id` from the canonical input manifest hash. Write all outputs beneath a sibling temporary directory, fsync files/directories, validate schemas and hashes, write `manifest.json` last, and atomically rename. If the deterministic final directory already exists, accept only byte-identical content; otherwise fail closed.

- [ ] **Step 5: Run CLI tests and diff checks**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_diagnose_frozen_three_day_k4_failure.py -q
git diff --check
```

- [ ] **Step 6: Commit Task 5**

```powershell
git add scripts/diagnose_frozen_three_day_k4_failure.py tests/test_diagnose_frozen_three_day_k4_failure.py
git commit -m "feat: publish frozen K4 failure diagnosis"
```

## Task 6: Prove real-schema integration and access isolation

**Files:**
- Modify: `tests/test_diagnose_frozen_three_day_k4_failure.py`
- Modify: `tests/application/services/test_frozen_k4_failure_replay.py`

- [ ] **Step 1: Add a real typed integration fixture**

Construct a real failed-model-attempt payload, local Binance ZIPs, 1,641 daily vectors or a production-schema reduced interval with injected expected receipts, and real two-half `SklearnClusterDiagnostic` fits. Do not mock projection, matching, primary assignment, or publication.

- [ ] **Step 2: Add forbidden-access and registry tests**

Snapshot registry bytes before the CLI run. Plant Mapping, Validation, Evidence, candidate, and Test paths containing sentinel content that raises if opened. Assert the diagnostic succeeds without reads and registry bytes remain identical.

- [ ] **Step 3: Add deterministic subprocess tests**

Run the fixture twice with fixed OMP/MKL/OpenBLAS limits and compare every published byte. Mutate dependency metadata and confirm reproduction stops rather than silently replacing the expected metric.

- [ ] **Step 4: Run the focused integration suite**

```powershell
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
.\.venv\Scripts\python.exe -m pytest tests/test_diagnose_frozen_three_day_k4_failure.py tests/application/services/test_frozen_k4_failure_replay.py tests/application/services/test_frozen_k4_failure_decomposition.py -q
```

- [ ] **Step 5: Commit Task 6**

```powershell
git add tests/test_diagnose_frozen_three_day_k4_failure.py tests/application/services/test_frozen_k4_failure_replay.py
git commit -m "test: verify frozen K4 diagnosis isolation"
```

## Task 7: Execute the real diagnosis twice and publish evidence

**Files:**
- Create: `docs/backtests/frozen_k4_failure_diagnosis/<run_id>/frozen_k4_failure_reproduction.json`
- Create: `docs/backtests/frozen_k4_failure_diagnosis/<run_id>/frozen_k4_cluster_diagnostics.csv`
- Create: `docs/backtests/frozen_k4_failure_diagnosis/<run_id>/frozen_k4_feature_contributions.csv`
- Create: `docs/backtests/frozen_k4_failure_diagnosis/<run_id>/frozen_k4_ood_samples.csv`
- Create: `docs/backtests/frozen_k4_failure_diagnosis/<run_id>/frozen_k4_distance_comparison.csv`
- Create: `docs/backtests/frozen_k4_failure_diagnosis/<run_id>/frozen_k4_failure_diagnosis.md`
- Create: `docs/backtests/frozen_k4_failure_diagnosis/<run_id>/manifest.json`

- [ ] **Step 1: Verify real local inputs before fitting**

Check that the published failed-model attempt hash is
`83e25e21a2bccb5cf14572da000718deae7f3e068c45b2898a26e78cef67101f`, the model file hash is
`e19ff1b2ec685f60b05d9aa98d088ea3883b62f0a394cf9fbdc2b84264ec23a5`, all source archives are present beneath `.research-data/binance-usdm/raw/klines`, and no later-period path is opened.

- [ ] **Step 2: Run the real diagnosis with one thread**

```powershell
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
.\.venv\Scripts\python.exe scripts/diagnose_frozen_three_day_k4_failure.py `
  --model-attempt docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json `
  --raw-kline-root .research-data/binance-usdm/raw/klines `
  --output-root docs/backtests/frozen_k4_failure_diagnosis
```

Expected: both frozen failure metrics reproduce within `1e-12`; the success run directory contains all seven files.

- [ ] **Step 3: Snapshot and rerun for byte determinism**

Copy the first run directory to `.agents/backtest-cache/frozen-k4-diagnosis-run1/`, rerun the identical command into `.agents/backtest-cache/frozen-k4-diagnosis-run2/`, and compare SHA-256 for all seven files. Any mismatch blocks publication.

- [ ] **Step 4: Review the ten answers against raw evidence**

Independently recompute the failed pair identity, top-five contribution sum, OOD numerator/denominator, largest centroid/OOD fingerprints, and offset extrema from the CSV/JSON rows. Confirm Markdown claims match those values exactly.

- [ ] **Step 5: Run full repository verification**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
git status --short
```

- [ ] **Step 6: Commit the evidence**

```powershell
git add -f docs/backtests/frozen_k4_failure_diagnosis
git commit -m "docs: publish frozen K4 failure diagnosis"
```

## Task 8: Final specification and quality review

**Files:**
- Review all files changed since `851d860`.

- [ ] **Step 1: Specification review**

Verify every allowed action, forbidden action, reproduction formula, output schema, and final question in the design document has direct code and test evidence. Treat any Mapping/Validation/Evidence/Test read or any fit beyond the exact two halves as P0.

- [ ] **Step 2: Code-quality review**

Review numerical stability, Gaussian formulas, float serialization, path/ZIP safety, atomic publication, memory/runtime scaling, mutation resistance, and whether any diagnostic result can be loaded as a runtime model.

- [ ] **Step 3: Fix findings with TDD and rerun verification**

Every finding requires a failing regression before a code change. After approval, rerun the focused suite, full suite, real diagnostic hash comparison, and `git diff --check` before completion.
