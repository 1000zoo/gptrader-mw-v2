# Clusterability Feasibility Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a research-only, fail-closed study that determines whether the fixed BTCUSDT `core25` or `dedup22` feature spaces contain temporally repeatable K=2 or K=3 structure beyond Gaussian and radial heavy-tail elliptical nulls.

**Architecture:** Keep runtime regime models and all Strategy/Mapping code untouched. Add immutable study contracts, exact fold/data guards, a sklearn-based geometry probe and null engine, deterministic statistical decisions, content-addressed checkpoints, and a CLI that separates fixture, capability, and formal identities. No code path can select or freeze a model.

**Tech Stack:** Python 3.14, NumPy, SciPy, scikit-learn 1.9, threadpoolctl, pytest 9, canonical JSON/CSV, SHA-256.

---

## Scope and execution checkpoints

The implementation may access only BTCUSDT Cluster Development OHLCV and the existing
three-day feature registry. It must not import Strategy Mapping, Evidence, Validation,
Test, outcome, PnL, or strategy-performance modules.

Execution stops at two explicit review points:

1. fixture and focused test suite must pass before real-data capability;
2. capability receipts must be complete and valid before requesting approval for formal
   105,504-fit execution.

Capability results cannot remove a feature set, K, null family, fold, threshold, or
metric from the formal design.

## File structure

- `src/domain/regime/clusterability.py`: immutable feature, fold, probe, policy, receipt,
  and decision contracts plus fixed registries.
- `src/application/services/clusterability_folds.py`: exact 24 fold contexts, data
  boundary validation, and ordered matrix extraction.
- `src/infrastructure/regime/sklearn_clusterability.py`: train-only preprocessing, PCA
  diagnostics, K-Means probe, null generation, and circular block bootstrap.
- `src/application/services/clusterability_metrics.py`: Monte Carlo p-values, Holm
  correction, fold/configuration decisions, and final study status.
- `src/infrastructure/regime/clusterability_checkpoint.py`: canonical serialization,
  content-addressed checkpoints, terminal completeness, atomic publication, and manifest
  verification.
- `scripts/clusterability_feasibility_study.py`: fixture/capability/formal orchestration,
  forbidden-boundary guards, rendering, and CLI.
- Tests mirror each production file under `tests/`.

### Task 1: Add immutable study contracts and fixed registries

**Files:**
- Create: `src/domain/regime/clusterability.py`
- Modify: `src/domain/regime/__init__.py`
- Create: `tests/domain/regime/test_clusterability.py`

- [ ] **Step 1: Write failing registry and validation tests**

```python
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.domain.regime.clusterability import (
    CLUSTERABILITY_POLICY_V1,
    FEATURE_SETS_V1,
    PROBE_CONFIGS_V1,
    FeatureSetSpec,
    StudyDecision,
)


def test_fixed_feature_and_probe_registries_are_exact():
    assert tuple(item.identity for item in FEATURE_SETS_V1) == (
        "core25_v1",
        "dedup_vol_range22_v1",
    )
    assert len(FEATURE_SETS_V1[0].feature_names) == 25
    assert FEATURE_SETS_V1[1].feature_names == tuple(
        name for name in FEATURE_SETS_V1[0].feature_names
        if name not in {"rv_4h", "rv_3d", "range_ratio_3d"}
    )
    assert tuple((item.feature_set_id, item.cluster_count) for item in PROBE_CONFIGS_V1) == (
        ("core25_v1", 2),
        ("core25_v1", 3),
        ("dedup_vol_range22_v1", 2),
        ("dedup_vol_range22_v1", 3),
    )


def test_policy_is_frozen_before_results():
    policy = CLUSTERABILITY_POLICY_V1
    assert policy.null_replicates == 499
    assert policy.bootstrap_refits == 100
    assert policy.bootstrap_block_days == 28
    assert policy.expanding_required_passes == 10
    assert policy.rolling_required_passes == 8
    assert policy.minimum_component_count == 5
    assert policy.minimum_component_share == 0.05
    assert policy.minimum_p05_ari == policy.minimum_p05_nmi == 0.80


def test_contracts_reject_noncanonical_or_selecting_state():
    with pytest.raises(ValueError, match="feature set"):
        FeatureSetSpec(" core25_v1", ("return_4h",), "registry")
    with pytest.raises(ValueError, match="status"):
        StudyDecision(
            status="selected",
            configuration_decisions=(),
            design_hash="a" * 64,
            input_hash="b" * 64,
        )
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_clusterability.py -q
```

Expected: collection fails because `src.domain.regime.clusterability` does not exist.

- [ ] **Step 3: Implement the immutable contracts**

Create these public types and constants:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Literal


StudyStatus = Literal[
    "clusterability_supported",
    "clusterability_not_supported",
    "inconclusive",
]


@dataclass(frozen=True)
class FeatureSetSpec:
    identity: str
    feature_names: tuple[str, ...]
    hypothesis_provenance: str

    def __post_init__(self) -> None:
        if (
            not self.identity
            or self.identity != self.identity.strip()
            or not self.feature_names
            or len(set(self.feature_names)) != len(self.feature_names)
        ):
            raise ValueError("feature set identity and names must be canonical")


@dataclass(frozen=True)
class FoldSpec:
    identity: str
    scheme: Literal["expanding", "rolling"]
    train_start_at: datetime
    train_end_at: datetime
    purge_start_at: datetime
    validation_start_at: datetime
    validation_end_at: datetime
    expected_train_count: int
    expected_validation_count: int


@dataclass(frozen=True)
class ProbeConfig:
    identity: str
    feature_set_id: str
    cluster_count: Literal[2, 3]


@dataclass(frozen=True)
class ClusterabilityPolicy:
    schema_version: str
    root_seed: int
    null_replicates: int
    bootstrap_refits: int
    bootstrap_block_days: int
    expanding_required_passes: int
    rolling_required_passes: int
    minimum_component_count: int
    minimum_component_share: float
    minimum_p05_ari: float
    minimum_p05_nmi: float
    familywise_alpha: float

    def __post_init__(self) -> None:
        numeric = (
            self.minimum_component_share,
            self.minimum_p05_ari,
            self.minimum_p05_nmi,
            self.familywise_alpha,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("policy values must be finite")


@dataclass(frozen=True)
class ConfigurationDecision:
    configuration_id: str
    expanding_null_passes: int
    expanding_stability_passes: int
    rolling_null_passes: int
    rolling_stability_passes: int
    collapse_fold_count: int
    unavailable_metric_count: int
    supported: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StudyDecision:
    status: StudyStatus
    configuration_decisions: tuple[ConfigurationDecision, ...]
    design_hash: str
    input_hash: str

    def __post_init__(self) -> None:
        if self.status not in {
            "clusterability_supported",
            "clusterability_not_supported",
            "inconclusive",
        }:
            raise ValueError("study status must be non-selecting and canonical")
```

Define `CORE25_FEATURE_NAMES` exactly as section 4.1 of the design. Build
`FEATURE_SETS_V1`, `PROBE_CONFIGS_V1`, and:

```python
CLUSTERABILITY_POLICY_V1 = ClusterabilityPolicy(
    schema_version="clusterability-feasibility-v1",
    root_seed=20260723,
    null_replicates=499,
    bootstrap_refits=100,
    bootstrap_block_days=28,
    expanding_required_passes=10,
    rolling_required_passes=8,
    minimum_component_count=5,
    minimum_component_share=0.05,
    minimum_p05_ari=0.80,
    minimum_p05_nmi=0.80,
    familywise_alpha=0.05,
)
```

Validate UTC fold boundaries, SHA-256 fields, positive counts, allowed K, and canonical
ordering. Export only the research contracts through `src/domain/regime/__init__.py`;
do not add any runtime artifact or selection type.

- [ ] **Step 4: Run the test and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/domain/regime/clusterability.py src/domain/regime/__init__.py tests/domain/regime/test_clusterability.py
git commit -m "feat: add clusterability study contracts"
```

### Task 2: Build exact folds and Cluster Development data guards

**Files:**
- Create: `src/application/services/clusterability_folds.py`
- Create: `tests/application/services/test_clusterability_folds.py`

- [ ] **Step 1: Write failing fold, anchor, and leakage tests**

```python
from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from src.application.services.clusterability_folds import (
    EXPECTED_ANCHOR_COUNT,
    build_fold_registry,
    feature_matrix,
    validate_cluster_development_vectors,
)


UTC = timezone.utc


def dt(year, month, day):
    return datetime(year, month, day, tzinfo=UTC)


def test_registry_has_exact_24_contexts_and_purge():
    folds = build_fold_registry()
    assert len(folds) == 24
    assert folds[0].identity == "2022q3-expanding"
    assert (folds[0].expected_train_count, folds[0].expected_validation_count) == (546, 89)
    assert folds[-1].identity == "2025q2-rolling"
    assert (folds[-1].expected_train_count, folds[-1].expected_validation_count) == (548, 87)
    assert all(
        fold.validation_start_at - fold.purge_start_at == timedelta(days=3)
        for fold in folds
    )


def test_vectors_require_exact_daily_cluster_development_contract(fake_vectors):
    assert len(validate_cluster_development_vectors(fake_vectors)) == EXPECTED_ANCHOR_COUNT
    duplicate = (*fake_vectors[:-1], fake_vectors[-2])
    with pytest.raises(ValueError, match="exact"):
        validate_cluster_development_vectors(duplicate)
    future = (*fake_vectors[:-1], replace(fake_vectors[-1], anchor_at=dt(2025, 6, 30)))
    with pytest.raises(ValueError, match="Cluster Development"):
        validate_cluster_development_vectors(future)


def test_matrix_preserves_registry_order_and_rejects_nonfinite(fake_vectors):
    matrix = feature_matrix(fake_vectors[:10], ("return_4h", "rv_1d"))
    assert matrix.shape == (10, 2)
```

The local `fake_vectors` fixture must generate 1,641 ordered daily
`ThreeDayChartFeatureVector` values from 2021-01-01 through 2025-06-29 with
`window_start_at=anchor_at-3 days`.

- [ ] **Step 2: Run the test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/services/test_clusterability_folds.py -q
```

Expected: module collection failure.

- [ ] **Step 3: Implement fold construction and matrix extraction**

Expose these exact boundaries:

```python
CLUSTER_RAW_START = datetime(2020, 12, 29, tzinfo=timezone.utc)
CLUSTER_ANCHOR_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
CLUSTER_END = datetime(2025, 6, 30, tzinfo=timezone.utc)
EXPECTED_CANDLE_COUNT = 2_367_360
EXPECTED_ANCHOR_COUNT = 1_641
```

`build_fold_registry()` must use the twelve origins from the design, calendar subtraction
of 18 months, a three-day purge, and deterministic order: origin then expanding/rolling.

`validate_cluster_development_vectors()` must reject sorting, dropping, deduplication,
non-UTC anchors, missing days, future anchors, incomplete windows, schema mismatch,
registry-order mismatch, and nonfinite values.

`split_fold_vectors()` returns exact train/validation tuples and checks expected counts.
`feature_matrix()` selects precommitted names in order and returns a finite `float64`
two-dimensional array.

- [ ] **Step 4: Run the test and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/application/services/clusterability_folds.py tests/application/services/test_clusterability_folds.py
git commit -m "feat: add clusterability fold guards"
```

### Task 3: Add train-only preprocessing and descriptive geometry

**Files:**
- Create: `src/infrastructure/regime/sklearn_clusterability.py`
- Create: `tests/infrastructure/regime/test_sklearn_clusterability.py`

- [ ] **Step 1: Write failing preprocessing and geometry tests**

```python
import numpy as np

from src.infrastructure.regime.sklearn_clusterability import (
    fit_preprocessor,
    geometry_diagnostics,
)


def test_preprocessor_is_train_only_and_deterministic():
    train = np.arange(240, dtype=float).reshape(60, 4)
    validation = np.full((8, 4), 1_000_000.0)
    first = fit_preprocessor(train)
    second = fit_preprocessor(train)
    assert first == second
    assert max(first.upper_bounds) < float(validation.min())
    np.testing.assert_allclose(first.transform(train), second.transform(train))
    assert np.isfinite(first.transform(validation)).all()


def test_geometry_reports_effective_dimension_and_fixed_pair_sample():
    rng = np.random.default_rng(7)
    matrix = rng.normal(size=(100, 5))
    result = geometry_diagnostics(matrix, root_seed=20260723)
    assert 1.0 <= result.effective_dimension <= 5.0
    assert 1 <= result.components_80 <= result.components_90 <= result.components_95 <= 5
    assert result.distance_pair_count == 4_950
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_sklearn_clusterability.py -q
```

Expected: module or symbol missing.

- [ ] **Step 3: Implement immutable preprocessing and geometry results**

Add:

```python
@dataclass(frozen=True)
class FittedPreprocessor:
    lower_bounds: tuple[float, ...]
    upper_bounds: tuple[float, ...]
    medians: tuple[float, ...]
    scales: tuple[float, ...]

    def transform(self, matrix: np.ndarray) -> np.ndarray:
        values = _finite_matrix(matrix, width=len(self.medians))
        clipped = np.clip(values, self.lower_bounds, self.upper_bounds)
        return (clipped - np.asarray(self.medians)) / np.asarray(self.scales)


def fit_preprocessor(train: np.ndarray) -> FittedPreprocessor:
    values = _finite_matrix(train)
    lower, upper = np.quantile(values, (0.005, 0.995), axis=0)
    clipped = np.clip(values, lower, upper)
    median = np.median(clipped, axis=0)
    q25, q75 = np.quantile(clipped, (0.25, 0.75), axis=0)
    scale = q75 - q25
    if np.any(upper <= lower) or np.any(scale <= 0):
        raise ValueError("preprocessing widths and IQR scales must be positive")
    return FittedPreprocessor(
        tuple(lower), tuple(upper), tuple(median), tuple(scale)
    )
```

The two quantiles above are the fixed p0.5/p99.5 clipping contract.
Add `GeometryDiagnostics` with eigenvalues, `components_80/90/95`,
participation-ratio effective dimension, correlation pairs/family summaries, pair count,
and distance coefficient of variation. Fit `PCA(svd_solver="full")` only on scaled train.
Select all pairs if there are at most 10,000; otherwise select exactly 10,000 unique
unordered pairs with a deterministic RNG.

- [ ] **Step 4: Run the test and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/infrastructure/regime/sklearn_clusterability.py tests/infrastructure/regime/test_sklearn_clusterability.py
git commit -m "feat: add clusterability preprocessing geometry"
```

### Task 4: Implement the observed K-Means geometry probe

**Files:**
- Modify: `src/infrastructure/regime/sklearn_clusterability.py`
- Modify: `tests/infrastructure/regime/test_sklearn_clusterability.py`

- [ ] **Step 1: Add failing observed-probe tests**

```python
import pytest

from src.infrastructure.regime.sklearn_clusterability import fit_observed_probe


def test_observed_probe_uses_fixed_train_model_for_validation():
    rng = np.random.default_rng(11)
    train = np.vstack((rng.normal(-3, .2, (60, 3)), rng.normal(3, .2, (60, 3))))
    validation = np.vstack((rng.normal(-3, .2, (20, 3)), rng.normal(3, .2, (20, 3))))
    result = fit_observed_probe(train, validation, cluster_count=2, seed=20260723)
    assert result.train_cluster_index < 0.05
    assert result.validation_silhouette > 0.8
    assert result.validation_counts == (20, 20)
    assert result.collapsed is False


def test_collapse_is_negative_evidence_not_unavailable():
    train = np.vstack((np.zeros((30, 2)), np.ones((30, 2)) * 10))
    validation = np.vstack((np.zeros((39, 2)), np.ones((1, 2)) * 10))
    result = fit_observed_probe(train, validation, cluster_count=2, seed=20260723)
    assert result.collapsed is True
    assert result.unavailable_reason == "validation_collapse"
```

- [ ] **Step 2: Run the two tests and verify RED**

Run the Task 3 test command. Expected: import or assertion failure.

- [ ] **Step 3: Implement `ObservedProbeResult` and `fit_observed_probe`**

Fit:

```python
KMeans(
    n_clusters=cluster_count,
    init="k-means++",
    n_init=20,
    max_iter=500,
    tol=1e-4,
    random_state=seed,
)
```

Treat `ConvergenceWarning` as an exception. Sort component identity by lexicographic center
values before emitting counts/shares. Compute:

```python
train_cluster_index = within_sum_of_squares / total_sum_of_squares
prevalence_tv = 0.5 * np.abs(train_shares - validation_shares).sum()
collapsed = any(count < 5 or share < 0.05 for count, share in validation)
```

Use `silhouette_score(validation, validation_labels)` only if each requested component
has at least two validation samples. Record collapse separately; never impute silhouette.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 3 test command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/infrastructure/regime/sklearn_clusterability.py tests/infrastructure/regime/test_sklearn_clusterability.py
git commit -m "feat: add observed clusterability probe"
```

### Task 5: Implement Gaussian and radial heavy-tail nulls

**Files:**
- Modify: `src/infrastructure/regime/sklearn_clusterability.py`
- Modify: `tests/infrastructure/regime/test_sklearn_clusterability.py`

- [ ] **Step 1: Add failing null-generator tests**

```python
from src.infrastructure.regime.sklearn_clusterability import (
    fit_null_generator,
    generate_null_pair,
)


def test_null_generators_are_deterministic_and_train_fitted():
    rng = np.random.default_rng(13)
    train = rng.standard_t(df=4, size=(500, 4))
    for family in ("gaussian", "radial_heavy_tail"):
        fitted = fit_null_generator(train, family=family)
        first = generate_null_pair(fitted, 300, 80, seed=99)
        second = generate_null_pair(fitted, 300, 80, seed=99)
        np.testing.assert_allclose(first.train, second.train)
        np.testing.assert_allclose(first.validation, second.validation)
        assert first.train.shape == (300, 4)
        assert first.validation.shape == (80, 4)


def test_radial_null_preserves_empirical_radius_pool():
    rng = np.random.default_rng(17)
    train = rng.standard_t(df=3, size=(400, 3))
    fitted = fit_null_generator(train, family="radial_heavy_tail")
    assert len(fitted.empirical_radii) == 400
    assert min(fitted.empirical_radii) >= 0
```

- [ ] **Step 2: Run tests and verify RED**

Run the Task 3 test command. Expected: missing null symbols.

- [ ] **Step 3: Implement train-fitted null generators**

Use `LedoitWolf().fit(train)` and an eigen-decomposition with eigenvalue floor
`max(max_eigenvalue * 1e-12, np.finfo(float).eps)`.

Gaussian generation:

```python
rng.multivariate_normal(mean, covariance, size=count, check_valid="raise")
```

Radial generation:

```python
directions = rng.normal(size=(count, dimension))
directions /= np.linalg.norm(directions, axis=1, keepdims=True)
radii = rng.choice(empirical_radii, size=count, replace=True)
whitened = directions * radii[:, None]
values = mean + whitened @ covariance_sqrt.T
```

Compute empirical radii from the train whitening transform. Reject non-SPD covariance,
zero direction norm, nonfinite output, or any use of validation inputs during null fit.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 3 test command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/infrastructure/regime/sklearn_clusterability.py tests/infrastructure/regime/test_sklearn_clusterability.py
git commit -m "feat: add clusterability null generators"
```

### Task 6: Add Monte Carlo evaluation and Holm correction

**Files:**
- Create: `src/application/services/clusterability_metrics.py`
- Create: `tests/application/services/test_clusterability_metrics.py`

- [ ] **Step 1: Write failing p-value and Holm tests**

```python
import pytest

from src.application.services.clusterability_metrics import (
    holm_adjust,
    monte_carlo_lower_p,
    monte_carlo_upper_p,
)


def test_monte_carlo_p_values_include_plus_one_correction():
    null = (0.1, 0.2, 0.3, 0.4)
    assert monte_carlo_upper_p(0.5, null) == pytest.approx(0.2)
    assert monte_carlo_lower_p(0.05, null) == pytest.approx(0.2)


def test_holm_adjustment_is_order_independent_and_monotone():
    values = {"c": 0.03, "a": 0.001, "b": 0.01, "d": 0.8}
    adjusted = holm_adjust(values)
    assert tuple(adjusted) == ("a", "b", "c", "d")
    assert adjusted["a"] <= adjusted["b"] <= adjusted["c"] <= adjusted["d"]
    assert adjusted["a"] == pytest.approx(0.004)
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/services/test_clusterability_metrics.py -q
```

Expected: module collection failure.

- [ ] **Step 3: Implement exact statistical helpers**

```python
def monte_carlo_upper_p(observed: float, null_values: tuple[float, ...]) -> float:
    _validate_finite(observed, null_values)
    return (1 + sum(value >= observed for value in null_values)) / (len(null_values) + 1)


def monte_carlo_lower_p(observed: float, null_values: tuple[float, ...]) -> float:
    _validate_finite(observed, null_values)
    return (1 + sum(value <= observed for value in null_values)) / (len(null_values) + 1)


def holm_adjust(values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    running = 0.0
    adjusted = {}
    total = len(ordered)
    for rank, (identity, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * value))
        adjusted[identity] = running
    return dict(sorted(adjusted.items(), key=lambda item: (values[item[0]], item[0])))
```

Reject empty null collections, duplicate IDs, booleans, NaN/Inf, and values outside
`[0, 1]`. Add a function that applies separate Holm families for silhouette and cluster
index within each `(fold, null_family)` and marks a configuration pass only when both
adjusted values are `<= 0.05` for both null families.

- [ ] **Step 4: Run the test and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/application/services/clusterability_metrics.py tests/application/services/test_clusterability_metrics.py
git commit -m "feat: add clusterability null statistics"
```

### Task 7: Add 28-day circular block-bootstrap stability

**Files:**
- Modify: `src/infrastructure/regime/sklearn_clusterability.py`
- Modify: `tests/infrastructure/regime/test_sklearn_clusterability.py`

- [ ] **Step 1: Write failing bootstrap tests**

```python
from src.infrastructure.regime.sklearn_clusterability import bootstrap_stability


def test_circular_block_bootstrap_is_deterministic():
    rng = np.random.default_rng(23)
    matrix = np.vstack((rng.normal(-2, .3, (80, 4)), rng.normal(2, .3, (80, 4))))
    first = bootstrap_stability(
        matrix, cluster_count=2, block_length=28, refits=10, root_seed=20260723
    )
    second = bootstrap_stability(
        matrix, cluster_count=2, block_length=28, refits=10, root_seed=20260723
    )
    assert first == second
    assert first.assignment_pair_count == 45
    assert 0 <= first.p05_ari <= 1
    assert 0 <= first.p05_nmi <= 1


def test_bootstrap_rejects_block_larger_than_train():
    with pytest.raises(ValueError, match="block"):
        bootstrap_stability(
            np.ones((20, 3)), cluster_count=2, block_length=28,
            refits=10, root_seed=1,
        )
```

- [ ] **Step 2: Run tests and verify RED**

Run the Task 3 test command. Expected: missing symbol.

- [ ] **Step 3: Implement bootstrap refits**

For each child seed:

1. generate enough uniform block starts to cover `n` rows, with each block containing
   exactly 28 daily anchors;
2. concatenate `(start + arange(28)) % n` and truncate to `n`;
3. fit clipping/RobustScaler on that bootstrap sample;
4. fit K-Means with the child seed;
5. transform the original fold train with that bootstrap preprocessor;
6. predict original rows.

Compute all `refits choose 2` assignment pairs with
`adjusted_rand_score` and `normalized_mutual_info_score`. Use NumPy-compatible linear
quantile at 0.05. Treat convergence, missing K components, nonfinite values, or fewer
than two refits as unavailable rather than substituting a score.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 3 test command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/infrastructure/regime/sklearn_clusterability.py tests/infrastructure/regime/test_sklearn_clusterability.py
git commit -m "feat: add temporal clusterability bootstrap"
```

### Task 8: Implement configuration and study decisions

**Files:**
- Modify: `src/application/services/clusterability_metrics.py`
- Modify: `tests/application/services/test_clusterability_metrics.py`

- [ ] **Step 1: Add failing decision golden tests**

```python
from src.application.services.clusterability_metrics import decide_study


def test_decision_supports_without_selecting_a_winner(passing_fold_receipts):
    decision = decide_study(passing_fold_receipts, design_hash="a" * 64, input_hash="b" * 64)
    assert decision.status == "clusterability_supported"
    assert sum(item.supported for item in decision.configuration_decisions) >= 1
    assert not hasattr(decision, "selected_candidate")


def test_complete_failures_are_not_supported(complete_failing_fold_receipts):
    decision = decide_study(
        complete_failing_fold_receipts, design_hash="a" * 64, input_hash="b" * 64
    )
    assert decision.status == "clusterability_not_supported"


def test_missing_required_metric_is_inconclusive(unavailable_fold_receipts):
    decision = decide_study(
        unavailable_fold_receipts, design_hash="a" * 64, input_hash="b" * 64
    )
    assert decision.status == "inconclusive"
```

Fixture builders must create exact 12 expanding + 12 rolling receipts for each of the
four configurations.

- [ ] **Step 2: Run tests and verify RED**

Run the Task 6 test command. Expected: missing decision implementation.

- [ ] **Step 3: Implement all-AND decisions**

For each configuration count:

- expanding null passes and stability passes;
- rolling null passes and stability passes;
- validation collapse folds;
- non-collapse unavailable metrics.

Support requires at least 10 folds from expanding and at least 8 folds from rolling,
zero collapse folds, and zero unavailable metrics. Emit every condition and reason
deterministically. If any
non-collapse required metric is unavailable, study status is `inconclusive`; otherwise
status is supported if any configuration passes, else not-supported. Never rank
configurations.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 6 test command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/application/services/clusterability_metrics.py tests/application/services/test_clusterability_metrics.py
git commit -m "feat: decide clusterability feasibility"
```

### Task 9: Add content-addressed checkpointing and atomic publication

**Files:**
- Create: `src/infrastructure/regime/clusterability_checkpoint.py`
- Create: `tests/infrastructure/regime/test_clusterability_checkpoint.py`

- [ ] **Step 1: Write failing checkpoint, resume, and manifest tests**

```python
from pathlib import Path

import pytest

from src.infrastructure.regime.clusterability_checkpoint import (
    CheckpointStore,
    canonical_hash,
    publish_run,
    verify_manifest,
)


def test_checkpoint_namespace_is_identity_partitioned(tmp_path):
    store = CheckpointStore(tmp_path)
    store.write("capability", "job-a", {"status": "completed", "value": 1})
    assert store.read("capability", "job-a")["value"] == 1
    assert store.read("formal", "job-a") is None


def test_checkpoint_rejects_changed_payload(tmp_path):
    store = CheckpointStore(tmp_path)
    store.write("formal", "job-a", {"status": "completed", "value": 1})
    with pytest.raises(ValueError, match="conflict"):
        store.write("formal", "job-a", {"status": "completed", "value": 2})


def test_atomic_publication_manifest_covers_every_payload(tmp_path):
    run = publish_run(
        tmp_path / "runs",
        run_id="a" * 64,
        payloads={"report.md": b"# result\n", "study_decision.json": b"{}\n"},
        implementation_hash="b" * 64,
    )
    manifest = verify_manifest(run)
    assert set(manifest["payloads"]) == {"report.md", "study_decision.json"}
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_clusterability_checkpoint.py -q
```

Expected: module collection failure.

- [ ] **Step 3: Implement canonical checkpoint and publication boundaries**

Canonical JSON uses UTF-8, sorted keys, separators `(",", ":")`, `allow_nan=False`, and
exactly one trailing LF for files. `canonical_hash()` hashes semantic canonical bytes.

`CheckpointStore` path is:

```text
<root>/<phase>/<run_id>/<job_key_hash>.json
```

Each receipt contains schema, phase, run ID, full job key, input hash, implementation
hash, child seed, status, payload, and canonical hash. Existing identical receipts are
resumed; conflicts fail closed.

`publish_run()` writes to a sibling staging directory, fsyncs payloads where supported,
builds a manifest containing every payload byte count/SHA-256, verifies it, then uses one
atomic rename to the immutable run ID. Existing run directories must be byte-identical
or publication fails.

Add terminal completeness that rejects missing, extra, duplicate, capability, or
wrong-run job keys before aggregation.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/infrastructure/regime/clusterability_checkpoint.py tests/infrastructure/regime/test_clusterability_checkpoint.py
git commit -m "feat: checkpoint clusterability study"
```

### Task 10: Build the research-only CLI and boundary guards

**Files:**
- Create: `scripts/clusterability_feasibility_study.py`
- Create: `tests/test_clusterability_feasibility_study.py`

- [ ] **Step 1: Write failing CLI and access-boundary tests**

```python
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.clusterability_feasibility_study import (
    build_job_registry,
    parse_args,
    validate_forbidden_access,
)


def test_cli_defaults_are_local_research_only():
    args = parse_args(["fixture"])
    assert args.phase == "fixture"
    assert args.raw_root == Path(".research-data/binance-usdm")
    assert args.output_root == Path(".research-data/clusterability-feasibility")


def test_formal_registry_has_exact_counts():
    jobs = build_job_registry("formal")
    assert sum(job.kind == "observed" for job in jobs) == 96
    assert sum(job.kind == "null" for job in jobs) == 95_808
    assert sum(job.kind == "bootstrap" for job in jobs) == 9_600
    assert len(jobs) == 105_504


def test_forbidden_boundary_rejects_strategy_paths(tmp_path):
    with pytest.raises(ValueError, match="forbidden"):
        validate_forbidden_access((tmp_path / "strategy-results.json",))
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_clusterability_feasibility_study.py -q
```

Expected: script module collection failure.

- [ ] **Step 3: Implement phase-separated orchestration**

CLI:

```text
clusterability_feasibility_study.py fixture
clusterability_feasibility_study.py capability
clusterability_feasibility_study.py formal
clusterability_feasibility_study.py audit --run-id <sha256>
```

Common options:

```text
--raw-root .research-data/binance-usdm
--output-root .research-data/clusterability-feasibility
--workers <positive int>
--resume
```

Fixture uses synthetic data only. Capability uses the first origin, both schemes, all
four configurations, 9 null replicates/family, and 5 bootstrap refits. Formal uses exact
policy counts.

Before source acquisition:

- validate final paths are regular non-symlink destinations;
- scan imported project modules and accessed paths against explicit forbidden prefixes;
- calculate design file hash, implementation hash, feature registry hash, source
  provenance hash, and phase-specific run ID.

Acquire features only through
`load_three_day_feature_history(start=2020-12-29, end=2025-06-30,
expected_anchor_count=1641)`. Require its ordered archive provenance, SHA-256 and ZIP
member receipts, and verify that the covered interval implies exactly 2,367,360
continuous one-minute candles. The shared `Candle` contract supplies the OHLC envelope
and nonnegative-volume checks. Recompute the expected archive request registry and reject
any missing, extra, reordered, or noncanonical source receipt.

Use `threadpoolctl.threadpool_limits(1)` inside every worker. Generate deterministic child
seeds from SHA-256 of `(root_seed, phase, full_job_key)`, not worker order.

Render all design outputs. `study_decision.json` and `report.md` must say explicitly that
no model was selected/frozen and no Strategy/Mapping data was accessed.

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/clusterability_feasibility_study.py tests/test_clusterability_feasibility_study.py
git commit -m "feat: orchestrate clusterability study"
```

### Task 11: Verify fixture behavior and focused regression

**Files:**
- Modify only if a failing test identifies a defect in files from Tasks 1-10.

- [ ] **Step 1: Run the fixed focused suite**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/domain/regime/test_clusterability.py `
  tests/application/services/test_clusterability_folds.py `
  tests/application/services/test_clusterability_metrics.py `
  tests/infrastructure/regime/test_sklearn_clusterability.py `
  tests/infrastructure/regime/test_clusterability_checkpoint.py `
  tests/test_clusterability_feasibility_study.py -q
```

Expected: all tests pass, zero failures.

- [ ] **Step 2: Run synthetic fixture**

```powershell
.\.venv\Scripts\python.exe scripts/clusterability_feasibility_study.py fixture `
  --output-root .research-data/clusterability-feasibility
```

Expected:

- separated two-cluster fixture: support direction;
- single Gaussian fixture: not-supported direction;
- radial heavy-tail fixture: fails radial-null support;
- fixture status `completed`;
- no runtime artifact or selected-candidate field.

- [ ] **Step 3: Run existing regime regression**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/domain/regime `
  tests/application/services/test_three_day_chart_feature_extractor.py `
  tests/infrastructure/regime `
  tests/infrastructure/exchange/binance/research_data/test_three_day_feature_history.py -q
```

Expected: all tests in the allowed regime/data boundary pass.

- [ ] **Step 4: Verify diff and commit any fixture-driven fixes**

```powershell
git diff --check
git status --short
```

If no fixes were needed, do not create an empty commit. If fixes were needed, stage only
the files changed for the failing fixture and commit:

```powershell
git commit -m "fix: harden clusterability fixture path"
```

### Task 12: Run and audit real-data capability

**Files:**
- Output only: `.research-data/clusterability-feasibility/`

- [ ] **Step 1: Run capability with resume enabled**

```powershell
.\.venv\Scripts\python.exe scripts/clusterability_feasibility_study.py capability `
  --raw-root .research-data/binance-usdm `
  --output-root .research-data/clusterability-feasibility `
  --workers 4 `
  --resume
```

Expected:

- exact 1,641 anchors validated;
- exact first-origin expanding/rolling contexts;
- all four configurations;
- 8 observed jobs;
- 144 null jobs (`2 schemes × 4 configs × 2 families × 9`);
- 40 bootstrap jobs (`2 schemes × 4 configs × 5`);
- 192 terminal jobs total;
- rejected 0;
- no forbidden access;
- capability status `completed`.

- [ ] **Step 2: Prove actual resume**

Run the exact Step 1 command again. Expected: 192/192 receipts reused, zero fits executed,
and byte-identical capability manifest.

- [ ] **Step 3: Run capability audit**

```powershell
.\.venv\Scripts\python.exe scripts/clusterability_feasibility_study.py audit `
  --output-root .research-data/clusterability-feasibility `
  --run-id <capability-run-id>
```

Replace `<capability-run-id>` with the exact ID printed by Step 1. Expected: manifest,
terminal key set, hashes, fold counts, metric recomputation, and access boundary all pass.

- [ ] **Step 4: Report the capability checkpoint**

Report exact job counts, run ID, manifest hash, resume evidence, focused suite result,
regime regression result, and any warnings. Do not describe capability as formal
clusterability evidence.

- [ ] **Step 5: Request explicit approval before formal**

Do not start Task 13 without user approval after the Task 12 report.

### Task 13: Run formal study and independently audit the decision

**Files:**
- Output only: `.research-data/clusterability-feasibility/`

- [ ] **Step 1: Run formal after explicit approval**

```powershell
.\.venv\Scripts\python.exe scripts/clusterability_feasibility_study.py formal `
  --raw-root .research-data/binance-usdm `
  --output-root .research-data/clusterability-feasibility `
  --workers 4 `
  --resume
```

Expected terminal registry:

- 96 observed jobs;
- 95,808 null jobs;
- 9,600 bootstrap jobs;
- 105,504 total jobs;
- every job completed or explicitly rejected;
- aggregation only if rejected count is zero and terminal key set is exact.

- [ ] **Step 2: Audit immutable formal publication**

```powershell
.\.venv\Scripts\python.exe scripts/clusterability_feasibility_study.py audit `
  --output-root .research-data/clusterability-feasibility `
  --run-id <formal-run-id>
```

Expected: audit recomputes all Holm families, fold passes, configuration decisions, and
study status from raw receipts and matches published bytes exactly.

- [ ] **Step 3: Verify prohibited outcomes**

```powershell
rg -n "selected_candidate|model_artifact|qualification|gate_calibration|strategy_performance|pnl" `
  ".research-data/clusterability-feasibility/runs/<formal-run-id>"
```

Expected: no selected model, runtime artifact, qualification, gate calibration, or
strategy-performance result. Explanatory statements such as `no model was selected` are
allowed and must not be represented as fields that imply a selection API.

- [ ] **Step 4: Publish the exact research conclusion**

Report:

- formal completed/rejected counts;
- final `clusterability_supported`, `clusterability_not_supported`, or `inconclusive`;
- all four configuration condition traces without ranking;
- expanding and rolling null/stability numerators;
- collapse and unavailable counts;
- geometry diagnostics;
- run, design, implementation, source, policy, and manifest hashes;
- explicit statement that no model was selected/frozen and no Mapping/Test data was used.

- [ ] **Step 5: Stop before the next research design**

Do not begin low-dimensional feature engineering, HMM, Student-t, continuous regime,
Strategy Mapping, artifact creation, or freeze in this plan.
