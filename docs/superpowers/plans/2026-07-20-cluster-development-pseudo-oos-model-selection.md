# Cluster Development Pseudo-OOS Model Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research-only, resumable Cluster Development pseudo-OOS pipeline that evaluates the fixed 60-candidate/20-seed grid and produces a deterministic `ranked_but_not_qualified` baseline unless a separately precommitted absolute-quality policy is supplied.

**Architecture:** Keep the existing runtime `RegimeModelConfig`, runtime artifact types, and Strategy/Mapping code untouched. Add narrow research-only domain contracts, fold construction, sklearn fitting, metrics/selection services, content-addressed checkpoints, and one CLI orchestrator. Capability and formal phases use separate namespaces; every formal job is represented by a verified terminal receipt before aggregation.

**Tech Stack:** Python 3.14, NumPy, SciPy, scikit-learn 1.9, threadpoolctl, pytest 9, canonical JSON/CSV, SHA-256.

---

## Scope Boundary

This plan implements only Cluster Development clustering research over anchors `[2021-01-01, 2025-06-30)` with raw lookback starting `2020-12-29`. It must not import or read Strategy Mapping, Strategy Evidence, Validation, Test, outcome, PnL, or strategy-performance code/data.

The first formal run has no absolute-quality policy and therefore must end as `ranked_but_not_qualified`. Qualification and freeze code paths are implemented and tested, but they execute only when a precommitted policy file is supplied before run identity calculation. No runtime-loadable model artifact is created by this plan.

## File Structure

- `src/domain/regime/pseudo_oos.py`: immutable research-only feature/model/fold/job/policy contracts and fixed registries.
- `src/application/services/cluster_development_folds.py`: exact 12 origins, expanding/rolling splits, purge enforcement, and matrix extraction.
- `src/infrastructure/regime/sklearn_pseudo_oos.py`: research-only preprocessing, K-Means/GMM fitting for K=2 and four covariance types, fixed assignment, OOD, confidence, and model fingerprints.
- `src/application/services/cluster_pseudo_oos_metrics.py`: centroid/covariance/prevalence/OOD/temporal/semantic metrics and Hungarian relative-margin matching.
- `src/application/services/cluster_pseudo_oos_selection.py`: seed aggregation, representative seed, percentile-rank scoring, absolute policy evaluation, qualification status, and gate calibration.
- `src/infrastructure/regime/pseudo_oos_checkpoint.py`: canonical serialization, checkpoint validation/resume, terminal completeness, immutable run identity, CSV/JSONL rendering, and atomic directory publication.
- `scripts/cluster_development_pseudo_oos.py`: data-access guard, capability/formal orchestration, deterministic parallel scheduling, and report rendering.
- Mirrored tests under `tests/domain/regime`, `tests/application/services`, `tests/infrastructure/regime`, and `tests/`.

Do not modify `src/domain/regime/model.py`, `src/infrastructure/regime/sklearn_cluster_core.py`, `src/infrastructure/regime/sklearn_cluster_diagnostic.py`, or any Strategy/Mapping module.

### Task 1: Freeze Research-Only Registries and Contracts

**Files:**
- Create: `src/domain/regime/pseudo_oos.py`
- Create: `tests/domain/regime/test_pseudo_oos.py`

- [ ] **Step 1: Write failing registry and validation tests**

```python
from datetime import datetime, timezone

import pytest

from src.domain.regime.pseudo_oos import (
    FEATURE_SETS,
    PSEUDO_OOS_SEEDS,
    CandidateSpec,
    PseudoOosModelConfig,
    build_candidate_registry,
)


def test_fixed_registry_contains_60_candidates_and_20_seeds():
    candidates = build_candidate_registry()
    assert tuple(FEATURE_SETS) == ("core25_v1", "dedup_vol_range22_v1")
    assert len(FEATURE_SETS["core25_v1"].feature_names) == 25
    assert len(FEATURE_SETS["dedup_vol_range22_v1"].feature_names) == 22
    assert PSEUDO_OOS_SEEDS == tuple(range(20260720, 20260740))
    assert len(candidates) == 60
    assert len({item.candidate_id for item in candidates}) == 60
    assert {item.model.cluster_count for item in candidates} == {2, 3, 4, 5, 6, 8}
    assert {item.model.covariance_type for item in candidates if item.model.model_type == "gmm"} == {
        "diag", "tied", "full", "spherical"
    }


def test_research_config_rejects_runtime_contract_leakage():
    with pytest.raises(ValueError, match="n_init"):
        PseudoOosModelConfig("gmm", 4, "diag", n_init=0)
    with pytest.raises(ValueError, match="covariance"):
        PseudoOosModelConfig("kmeans", 4, "diag")
    with pytest.raises(ValueError, match="cluster count"):
        PseudoOosModelConfig("gmm", 7, "full")


def test_candidate_identity_is_canonical_and_feature_scoped():
    item = CandidateSpec(
        "core25_v1__gmm-full-k2",
        "core25_v1",
        PseudoOosModelConfig("gmm", 2, "full", random_seed=20260720, n_init=1),
    )
    assert item.candidate_id == "core25_v1__gmm-full-k2"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_pseudo_oos.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'src.domain.regime.pseudo_oos'`.

- [ ] **Step 3: Implement the fixed registries and dataclasses**

Implement these exact public contracts:

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Mapping


CLUSTER_COUNTS = (2, 3, 4, 5, 6, 8)
GMM_COVARIANCE_TYPES = ("diag", "tied", "full", "spherical")
PSEUDO_OOS_SEEDS = tuple(range(20260720, 20260740))


@dataclass(frozen=True)
class FeatureSetSpec:
    feature_set_id: str
    feature_names: tuple[str, ...]
    hypothesis_provenance: str


@dataclass(frozen=True)
class PseudoOosModelConfig:
    model_type: Literal["kmeans", "gmm"]
    cluster_count: int
    covariance_type: Literal["diag", "tied", "full", "spherical"] | None = None
    random_seed: int = 20260720
    n_init: int = 1
    regularization: float = 1e-6
    max_iter: int = 200


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    feature_set_id: str
    model: PseudoOosModelConfig


@dataclass(frozen=True)
class FoldSpec:
    fold_id: str
    scheme: Literal["expanding", "rolling"]
    train_start_at: datetime
    train_end_at: datetime
    purge_start_at: datetime
    validation_start_at: datetime
    validation_end_at: datetime
    expected_train_count: int
    expected_validation_count: int


@dataclass(frozen=True, order=True)
class JobKey:
    phase: Literal["capability", "formal", "qualification"]
    fold_id: str
    candidate_id: str
    seed: int


@dataclass(frozen=True)
class AbsoluteQualityPolicy:
    schema_version: str
    provenance_hash: str
    p05_seed_ari_min: float
    p05_seed_nmi_min: float
    minimum_validation_component_share_min: float
    maximum_collapse_fold_count: int
    maximum_overall_ood_rate: float
    maximum_component_ood_rate: float
    minimum_ood_assignment_coverage: float
    maximum_within_fold_centroid_distance: float
    minimum_covariance_component_coverage: float
```

Populate `core25_v1` in this exact order:

```python
CORE25_FEATURE_NAMES = (
    "return_4h",
    "return_12h",
    "return_1d",
    "return_2d",
    "return_3d",
    "rv_4h",
    "rv_1d",
    "rv_3d",
    "rv_ratio_1d_3d",
    "range_ratio_3d",
    "close_location_3d",
    "directional_efficiency_1d",
    "directional_efficiency_3d",
    "sign_change_rate_1d",
    "sign_change_rate_3d",
    "return_autocorr_1d",
    "return_autocorr_3d",
    "max_drawdown_3d",
    "max_runup_3d",
    "breakout_rate_3d",
    "mean_body_ratio_3d",
    "mean_upper_wick_ratio_3d",
    "mean_lower_wick_ratio_3d",
    "volume_cv_3d",
    "volume_ratio_1d_3d",
)
```

Build `dedup_vol_range22_v1` by removing only `rv_4h`, `rv_3d`, and `range_ratio_3d` while preserving the remaining order. Its `hypothesis_provenance` must state that this is a post-frozen-K4 diagnostic development hypothesis evaluated only inside Cluster Development, without Mapping/Validation/Test outcomes. Validate canonical IDs, registry order, finite numeric policy fields, allowed K/covariance combinations, UTC fold boundaries, and `n_init >= 1`. `build_candidate_registry()` must iterate feature set, K, then model order `kmeans`, `gmm-diag`, `gmm-tied`, `gmm-full`, `gmm-spherical` deterministically.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_pseudo_oos.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/domain/regime/pseudo_oos.py tests/domain/regime/test_pseudo_oos.py
git commit -m "feat: define pseudo-OOS research contracts"
```

### Task 2: Build Exact Expanding and Rolling Folds

**Files:**
- Create: `src/application/services/cluster_development_folds.py`
- Create: `tests/application/services/test_cluster_development_folds.py`

- [ ] **Step 1: Write failing fold-boundary and leakage tests**

```python
from datetime import datetime, timedelta, timezone

import pytest

from src.application.services.cluster_development_folds import build_fold_registry, split_fold_vectors


UTC = timezone.utc


def dt(year, month, day):
    return datetime(year, month, day, tzinfo=UTC)


def test_fold_registry_has_exact_24_contexts_and_counts():
    folds = build_fold_registry()
    assert len(folds) == 24
    assert folds[0].fold_id == "2022q3-expanding"
    assert (folds[0].expected_train_count, folds[0].expected_validation_count) == (546, 89)
    assert folds[1].fold_id == "2022q3-rolling"
    assert folds[-1].fold_id == "2025q2-rolling"
    assert (folds[-1].expected_train_count, folds[-1].expected_validation_count) == (548, 87)


def test_every_fold_has_three_day_purge_and_no_raw_window_overlap():
    for fold in build_fold_registry():
        assert fold.validation_start_at - fold.purge_start_at == timedelta(days=3)
        last_train_anchor = fold.train_end_at - timedelta(days=1)
        first_validation_window_start = fold.validation_start_at - timedelta(days=3)
        assert last_train_anchor < first_validation_window_start


def test_split_rejects_any_anchor_outside_cluster_development(fake_vectors):
    from dataclasses import replace
    altered = list(fake_vectors)
    altered[-1] = replace(
        altered[-1],
        anchor_at=dt(2025, 6, 30),
        window_start_at=dt(2025, 6, 27),
    )
    with pytest.raises(ValueError, match="Cluster Development"):
        split_fold_vectors(tuple(altered), build_fold_registry()[0])
```

Create the local `fake_vectors` fixture with 1,641 daily `ThreeDayChartFeatureVector` objects from `2021-01-01` through `2025-06-29`, using registry-ordered finite values and `window_start_at=anchor-3 days`.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_development_folds.py -q`

Expected: collection fails because the module is absent.

- [ ] **Step 3: Implement fold construction and vector splitting**

Expose:

```python
CLUSTER_RAW_START = datetime(2020, 12, 29, tzinfo=timezone.utc)
CLUSTER_ANCHOR_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
CLUSTER_END = datetime(2025, 6, 30, tzinfo=timezone.utc)
EXPECTED_ANCHOR_COUNT = 1641


def _subtract_18_months(value: datetime) -> datetime:
    month_index = value.year * 12 + value.month - 1 - 18
    return value.replace(year=month_index // 12, month=month_index % 12 + 1)


def build_fold_registry() -> tuple[FoldSpec, ...]:
    origins = (
        datetime(2022, 7, 1, tzinfo=timezone.utc),
        datetime(2022, 10, 1, tzinfo=timezone.utc),
        datetime(2023, 1, 1, tzinfo=timezone.utc),
        datetime(2023, 4, 1, tzinfo=timezone.utc),
        datetime(2023, 7, 1, tzinfo=timezone.utc),
        datetime(2023, 10, 1, tzinfo=timezone.utc),
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 4, 1, tzinfo=timezone.utc),
        datetime(2024, 7, 1, tzinfo=timezone.utc),
        datetime(2024, 10, 1, tzinfo=timezone.utc),
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 4, 1, tzinfo=timezone.utc),
    )
    ends = (*origins[1:], CLUSTER_END)
    folds = []
    for origin, validation_end in zip(origins, ends, strict=True):
        quarter = (origin.month - 1) // 3 + 1
        validation_start = origin + timedelta(days=3)
        for scheme, train_start in (
            ("expanding", CLUSTER_ANCHOR_START),
            ("rolling", _subtract_18_months(origin)),
        ):
            folds.append(FoldSpec(
                fold_id=f"{origin.year}q{quarter}-{scheme}",
                scheme=scheme,
                train_start_at=train_start,
                train_end_at=origin,
                purge_start_at=origin,
                validation_start_at=validation_start,
                validation_end_at=validation_end,
                expected_train_count=(origin - train_start).days,
                expected_validation_count=(validation_end - validation_start).days,
            ))
    return tuple(folds)


def validate_cluster_development_vectors(
    vectors: tuple[ThreeDayChartFeatureVector, ...],
) -> tuple[ThreeDayChartFeatureVector, ...]:
    expected = tuple(
        CLUSTER_ANCHOR_START + timedelta(days=index)
        for index in range(EXPECTED_ANCHOR_COUNT)
    )
    if len(vectors) != EXPECTED_ANCHOR_COUNT:
        raise ValueError("Cluster Development requires exactly 1641 anchors")
    if tuple(vector.anchor_at for vector in vectors) != expected:
        raise ValueError("Cluster Development anchors are incomplete or noncanonical")
    if any(vector.window_start_at != vector.anchor_at - timedelta(days=3) for vector in vectors):
        raise ValueError("Cluster Development feature windows are invalid")
    return vectors


def split_fold_vectors(
    vectors: tuple[ThreeDayChartFeatureVector, ...], fold: FoldSpec,
) -> tuple[tuple[ThreeDayChartFeatureVector, ...], tuple[ThreeDayChartFeatureVector, ...]]:
    values = validate_cluster_development_vectors(vectors)
    train = tuple(vector for vector in values if fold.train_start_at <= vector.anchor_at < fold.train_end_at)
    validation = tuple(
        vector for vector in values
        if fold.validation_start_at <= vector.anchor_at < fold.validation_end_at
    )
    if len(train) != fold.expected_train_count or len(validation) != fold.expected_validation_count:
        raise ValueError("fold vector counts do not match the frozen registry")
    return train, validation


def feature_matrix(
    vectors: tuple[ThreeDayChartFeatureVector, ...], feature_set: FeatureSetSpec,
) -> np.ndarray:
    matrix = np.asarray([
        [vector.values[name] for name in feature_set.feature_names]
        for vector in vectors
    ], dtype=float)
    if matrix.shape != (len(vectors), len(feature_set.feature_names)) or not np.isfinite(matrix).all():
        raise ValueError("feature matrix is non-finite or has the wrong shape")
    return matrix
```

Use the 12 origins and exact counts from the approved design. Implement calendar-month subtraction without pandas. Validation anchors start exactly three days after the origin. Validate all 1,641 anchors before slicing; do not silently sort, drop, or deduplicate. `feature_matrix` must select the precommitted feature names in their fixed order and reject non-finite values.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_development_folds.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/application/services/cluster_development_folds.py tests/application/services/test_cluster_development_folds.py
git commit -m "feat: define pseudo-OOS fold registry"
```

### Task 3: Implement the Research-Only sklearn Fit Contract

**Files:**
- Create: `src/infrastructure/regime/sklearn_pseudo_oos.py`
- Create: `tests/infrastructure/regime/test_sklearn_pseudo_oos.py`

- [ ] **Step 1: Write failing preprocessing, covariance, and n-init tests**

```python
import numpy as np
import pytest

from src.domain.regime.pseudo_oos import PseudoOosModelConfig
from src.infrastructure.regime.sklearn_pseudo_oos import SklearnPseudoOosEstimator


@pytest.mark.parametrize("covariance", ["diag", "tied", "full", "spherical"])
def test_gmm_supports_every_research_covariance(covariance, stable_matrix):
    fit = SklearnPseudoOosEstimator().fit(
        PseudoOosModelConfig("gmm", 2, covariance, random_seed=20260720, n_init=1),
        stable_matrix,
        ("a", "b", "c"),
        "fixture-v1",
    )
    assert np.asarray(fit.covariances).shape == (2, 3, 3)
    assert fit.n_init == 1
    assert len(fit.fingerprints) == 2


def test_fit_uses_train_only_clipping_and_scaler(stable_matrix):
    fit = SklearnPseudoOosEstimator().fit(
        PseudoOosModelConfig("kmeans", 2, None, random_seed=20260720, n_init=1),
        stable_matrix,
        ("a", "b", "c"),
        "fixture-v1",
    )
    assert fit.lower_bounds == pytest.approx(np.quantile(stable_matrix, .005, axis=0))
    assert fit.upper_bounds == pytest.approx(np.quantile(stable_matrix, .995, axis=0))


def test_n_init_is_forwarded_without_mutating_runtime_core(monkeypatch, stable_matrix):
    import src.infrastructure.regime.sklearn_pseudo_oos as module
    seen = {}
    original = module.GaussianMixture
    def factory(**kwargs):
        seen.update({key: kwargs[key] for key in ("random_state", "n_init", "covariance_type")})
        return original(**kwargs)
    monkeypatch.setattr(module, "GaussianMixture", factory)
    SklearnPseudoOosEstimator().fit(
        PseudoOosModelConfig("gmm", 2, "diag", random_seed=9, n_init=7),
        stable_matrix,
        ("a", "b", "c"),
        "fixture-v1",
    )
    assert seen == {"random_state": 9, "n_init": 7, "covariance_type": "diag"}
```

The fixture matrix must have at least 80 deterministic rows and three non-constant dimensions. The recording estimator must expose the sklearn attributes consumed by the implementation.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_sklearn_pseudo_oos.py -q`

Expected: collection fails because the estimator module is absent.

- [ ] **Step 3: Implement normalized fit arrays**

Define immutable `PseudoOosFit` with config, feature/schema identities, bounds, medians, scales, sorted fingerprints, weights, means, covariances shaped `(K,d,d)`, p99 OOD thresholds, K-Means component distance medians, convergence metadata, and a SHA-256 fit fingerprint.

`SklearnPseudoOosEstimator.fit(config, train_matrix, feature_names, schema_version)` must:

1. validate finite 2-D input and `rows >= K`;
2. fit p0.5/p99.5 bounds and `RobustScaler` on train only;
3. call `KMeans(n_clusters=config.cluster_count, random_state=config.random_seed, n_init=config.n_init, max_iter=config.max_iter)` or `GaussianMixture(n_components=config.cluster_count, random_state=config.random_seed, n_init=config.n_init, covariance_type=config.covariance_type, reg_covar=config.regularization, max_iter=config.max_iter)` under `threadpool_limits(1)`;
4. normalize covariance to `(K,d,d)` for all four GMM covariance types;
5. hard-assign train rows and calculate component p99 squared-distance OOD thresholds;
6. calculate K-Means component median squared distance;
7. sort components by a canonical SHA-256 fingerprint and remap every component array;
8. reject convergence warnings, invalid covariance, zero scaler widths, or non-finite parameters.

Use these covariance conversions:

```python
def full_covariances(estimator, covariance_type, k, d):
    raw = np.asarray(estimator.covariances_, dtype=float)
    if covariance_type == "full":
        return raw
    if covariance_type == "tied":
        return np.repeat(raw[None, :, :], k, axis=0)
    if covariance_type == "diag":
        return np.asarray([np.diag(row) for row in raw])
    return np.asarray([np.eye(d) * value for value in raw])
```

Do not import or call `_fit_components`; the existing runtime core remains unchanged.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_sklearn_pseudo_oos.py -q`

Expected: all tests pass, including all covariance types.

- [ ] **Step 5: Commit**

```powershell
git add src/infrastructure/regime/sklearn_pseudo_oos.py tests/infrastructure/regime/test_sklearn_pseudo_oos.py
git commit -m "feat: fit research-only pseudo-OOS models"
```

### Task 4: Add Fixed Assignment, OOD, and Model-Native Confidence

**Files:**
- Modify: `src/infrastructure/regime/sklearn_pseudo_oos.py`
- Modify: `tests/infrastructure/regime/test_sklearn_pseudo_oos.py`

- [ ] **Step 1: Write failing assignment isolation tests**

```python
def test_validation_assignment_never_changes_fit(stable_matrix):
    estimator = SklearnPseudoOosEstimator()
    config = PseudoOosModelConfig("gmm", 2, "full", random_seed=20260720, n_init=1)
    fit = estimator.fit(config, stable_matrix, ("a", "b", "c"), "fixture-v1")
    before = fit.canonical_hash
    assigned = estimator.assign(fit, stable_matrix * 1000)
    assert fit.canonical_hash == before
    assert len(assigned.component_indices) == len(stable_matrix)
    assert assigned.preclip_exceedance_rate > 0


def test_kmeans_uses_component_normalized_distance_margin(stable_matrix):
    estimator = SklearnPseudoOosEstimator()
    fit = estimator.fit(
        PseudoOosModelConfig("kmeans", 2, None, n_init=1),
        stable_matrix,
        ("a", "b", "c"),
        "fixture-v1",
    )
    assigned = estimator.assign(fit, stable_matrix[:5])
    assert assigned.posterior_maxima is None
    assert assigned.normalized_distance_margins is not None
    assert all(0 <= value <= 1 for value in assigned.normalized_distance_margins)


def test_unavailable_component_threshold_reduces_ood_coverage_without_imputation(stable_matrix):
    from dataclasses import replace
    estimator = SklearnPseudoOosEstimator()
    fit = estimator.fit(
        PseudoOosModelConfig("kmeans", 2, None, n_init=1),
        stable_matrix,
        ("a", "b", "c"),
        "fixture-v1",
    )
    without_threshold = replace(fit, ood_thresholds=(None, fit.ood_thresholds[1]))
    result = estimator.assign(without_threshold, stable_matrix)
    assert result.ood_assignment_coverage < 1
    assert None in result.ood_flags
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_sklearn_pseudo_oos.py -q`

Expected: failures report missing `assign`/assignment fields.

- [ ] **Step 3: Implement `PseudoOosAssignments` and `assign`**

The immutable result contains component indices/fingerprints, scaled values, preclip exceedances, winning squared distances, OOD flags as `bool | None`, overall OOD numerator/denominator/rate, OOD assignment coverage, and exactly one of:

- GMM `posterior_maxima` and `posterior_margins`;
- K-Means `normalized_distance_softmax_maxima` and `normalized_distance_margins`.

For GMM, compute log joint density with `slogdet` and `solve` against the persisted full covariance matrices, then normalize with log-sum-exp. For K-Means, compute `q_j=d_j²/max(component_train_median_j,1e-12)`, descriptive softmax over `-q`, and `(q2-q1)/max(q2,1e-12)`. Apply only the fit's clipping/scaler; never fit on validation.

- [ ] **Step 4: Run estimator tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_sklearn_pseudo_oos.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/infrastructure/regime/sklearn_pseudo_oos.py tests/infrastructure/regime/test_sklearn_pseudo_oos.py
git commit -m "feat: assign pseudo-OOS validation samples"
```

### Task 5: Implement Drift, Matching, Collapse, and Temporal Metrics

**Files:**
- Create: `src/application/services/cluster_pseudo_oos_metrics.py`
- Create: `tests/application/services/test_cluster_pseudo_oos_metrics.py`

- [ ] **Step 1: Write failing metric edge-case tests**

```python
import numpy as np
import pytest

from src.application.services.cluster_pseudo_oos_metrics import (
    covariance_drift,
    hungarian_match,
    summarize_fold_metrics,
)


def test_covariance_unavailable_does_not_discard_other_metrics(fold_fixture):
    fixture = fold_fixture.with_validation_counts((84, 1, 0))
    metrics = summarize_fold_metrics(fixture)
    assert metrics.component_metrics[1].collapse is True
    assert metrics.component_metrics[1].covariance_drift.available is False
    assert metrics.component_metrics[2].prevalence_share == 0
    assert metrics.overall_ood_rate.available is True


def test_hungarian_uses_relative_margin_and_marks_ambiguous():
    cost = np.asarray([[1.0, 1.01], [1.01, 1.0]])
    result = hungarian_match(cost, minimum_relative_margin=.05)
    assert result.available is False
    assert result.relative_margin == pytest.approx(.02)


def test_covariance_drift_is_zero_for_identical_samples():
    values = np.asarray([[0., 1.], [1., 0.], [2., 1.], [1., 2.]])
    assert covariance_drift(values, values).value == pytest.approx(0)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_pseudo_oos_metrics.py -q`

Expected: collection fails because the metric module is absent.

- [ ] **Step 3: Implement immutable metric records and algorithms**

Implement `AvailableMetric(value, available, reason)`, `ComponentMetrics`, `FoldMetrics`, `HungarianMatch`, and these functions:

```python
@dataclass(frozen=True)
class AvailableMetric:
    value: float | None
    available: bool
    reason: str | None

    @classmethod
    def measured(cls, value: float):
        if not math.isfinite(value):
            raise ValueError("metric must be finite")
        return cls(float(value), True, None)

    @classmethod
    def unavailable(cls, reason: str):
        if not reason or reason != reason.strip():
            raise ValueError("unavailable metric requires a canonical reason")
        return cls(None, False, reason)


def fit_common_reference(earliest_train_matrix: np.ndarray) -> CommonReference:
    lower = np.quantile(earliest_train_matrix, .005, axis=0)
    upper = np.quantile(earliest_train_matrix, .995, axis=0)
    scaler = RobustScaler().fit(np.clip(earliest_train_matrix, lower, upper))
    return CommonReference(
        tuple(float(value) for value in lower),
        tuple(float(value) for value in upper),
        tuple(float(value) for value in scaler.center_),
        tuple(float(value) for value in scaler.scale_),
    )


def project_centroids_to_reference(fit: PseudoOosFit, reference: CommonReference) -> np.ndarray:
    raw = np.asarray(fit.means) * np.asarray(fit.scales) + np.asarray(fit.medians)
    return (raw - np.asarray(reference.medians)) / np.asarray(reference.scales)


def within_fold_centroid_drift(
    fit: PseudoOosFit, assignments: PseudoOosAssignments,
) -> tuple[AvailableMetric, ...]:
    result = []
    scaled = np.asarray(assignments.scaled_values)
    labels = np.asarray(assignments.component_indices)
    for component, train_mean in enumerate(np.asarray(fit.means)):
        rows = scaled[labels == component]
        if not len(rows):
            result.append(AvailableMetric.unavailable("empty_validation_component"))
        else:
            delta = rows.mean(axis=0) - train_mean
            result.append(AvailableMetric.measured(float(delta @ delta / len(delta))))
    return tuple(result)


def _matrix_log(values: np.ndarray) -> np.ndarray:
    eigenvalues, eigenvectors = np.linalg.eigh(values)
    if np.any(eigenvalues <= 0):
        raise ValueError("covariance must be positive definite")
    return (eigenvectors * np.log(eigenvalues)) @ eigenvectors.T


def covariance_drift(train_rows: np.ndarray, validation_rows: np.ndarray) -> AvailableMetric:
    if len(train_rows) < 2 or len(validation_rows) < 2:
        return AvailableMetric.unavailable("component_count_below_two")
    train_cov = LedoitWolf().fit(train_rows).covariance_
    validation_cov = LedoitWolf().fit(validation_rows).covariance_
    ridge = np.eye(train_cov.shape[0]) * 1e-9
    delta = _matrix_log(train_cov + ridge) - _matrix_log(validation_cov + ridge)
    return AvailableMetric.measured(float(np.linalg.norm(delta, ord="fro") / math.sqrt(len(delta))))


def hungarian_match(cost: np.ndarray, minimum_relative_margin: float = .05) -> HungarianMatch:
    rows, columns = linear_sum_assignment(cost)
    best = float(cost[rows, columns].sum())
    alternatives = []
    for row, column in zip(rows, columns, strict=True):
        altered = np.array(cost, copy=True)
        altered[row, column] = np.inf
        alt_rows, alt_columns = linear_sum_assignment(altered)
        alternatives.append(float(altered[alt_rows, alt_columns].sum()))
    second = min(alternatives)
    margin = (second - best) / max(abs(best), 1e-12)
    return HungarianMatch(
        assignment=tuple(int(columns[np.where(rows == row)[0][0]]) for row in range(len(rows))),
        best_cost=best,
        second_best_cost=second,
        relative_margin=margin,
        available=margin >= minimum_relative_margin,
    )
```

Add `temporal_metrics` that run-length encodes component indices without crossing a fold boundary and returns median/p25/p75/p95 duration, one-day fraction, and switching rate. `summarize_fold_metrics` must call the functions above, compute counts/shares/TV drift/collapse/OOD/semantic fields, and preserve every unavailable reason. Count `<2` makes only covariance unavailable; count `<5` sets collapse. Earliest-reference values are descriptive fields. Primary centroid/semantic fields use within-fold scaled train-versus-validation comparisons.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_pseudo_oos_metrics.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/application/services/cluster_pseudo_oos_metrics.py tests/application/services/test_cluster_pseudo_oos_metrics.py
git commit -m "feat: compute pseudo-OOS stability metrics"
```

### Task 6: Build Job Execution and Seed Stability Aggregation

**Files:**
- Create: `src/application/services/cluster_pseudo_oos_selection.py`
- Create: `tests/application/services/test_cluster_pseudo_oos_selection.py`

- [ ] **Step 1: Write failing job and representative-seed tests**

```python
from src.application.services.cluster_pseudo_oos_selection import (
    choose_representative_seed,
    expected_formal_job_keys,
    pairwise_seed_stability,
)
from src.domain.regime.pseudo_oos import build_candidate_registry
from src.application.services.cluster_development_folds import build_fold_registry


def test_formal_grid_has_exact_unique_job_keys():
    keys = expected_formal_job_keys(build_fold_registry(), build_candidate_registry())
    assert len(keys) == 28_800
    assert len(set(keys)) == 28_800


def test_pairwise_seed_stability_has_190_pairs_per_candidate_fold(seed_label_fixture):
    rows = pairwise_seed_stability(seed_label_fixture)
    assert len(rows) == 190


def test_representative_seed_uses_mean_ari_then_nmi_then_smallest(seed_stability_fixture):
    assert choose_representative_seed(seed_stability_fixture) == 20260721
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_pseudo_oos_selection.py -q`

Expected: collection fails because the service is absent.

- [ ] **Step 3: Implement deterministic job execution contracts**

Add `JobResult`, `RejectedJob`, `SeedPairMetric`, and `CandidateAggregate`. `run_fit_job(job_key, fold, candidate, train_matrix, validation_matrix, schema_version, estimator)` must catch only declared candidate-level numerical/convergence exceptions and return a rejected terminal result; data-boundary, registry, duplicate-key, or serialization errors must escape and invalidate the run.

`expected_formal_job_keys()` must create 24×60×20 sorted keys. `pairwise_seed_stability()` computes all 190 ARI/NMI pairs from validation component indices without Hungarian matching. A seed is globally valid only if all 24 jobs completed. Require at least 18 globally valid seeds before choosing the representative seed by mean ARI, mean NMI, then smallest numeric seed.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_pseudo_oos_selection.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/application/services/cluster_pseudo_oos_selection.py tests/application/services/test_cluster_pseudo_oos_selection.py
git commit -m "feat: aggregate pseudo-OOS seed stability"
```

### Task 7: Implement Relative Ranking and Absolute Qualification Status

**Files:**
- Modify: `src/application/services/cluster_pseudo_oos_selection.py`
- Modify: `tests/application/services/test_cluster_pseudo_oos_selection.py`

- [ ] **Step 1: Write failing score/status tests**

```python
from src.application.services.cluster_pseudo_oos_selection import rank_candidates


def test_policy_absence_can_rank_but_never_select(candidate_aggregates):
    result = rank_candidates(candidate_aggregates, policy=None)
    assert result.status == "ranked_but_not_qualified"
    assert result.provisional_ranking
    assert result.selected_candidate_id is None


def test_single_relative_winner_must_still_pass_absolute_policy(candidate_aggregates, strict_policy):
    result = rank_candidates((candidate_aggregates[0],), policy=strict_policy)
    assert result.status == "no_eligible_candidate"
    assert result.selected_candidate_id is None


def test_tie_break_prefers_worst_domain_then_22_features_then_complexity(tied_aggregates, permissive_policy):
    result = rank_candidates(tied_aggregates, policy=permissive_policy)
    assert result.qualified_ranking[0].candidate_id == "dedup_vol_range22_v1__kmeans-k3"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_pseudo_oos_selection.py -q`

Expected: failures report missing ranking/status behavior.

- [ ] **Step 3: Implement the precommitted score and policy gate**

Use the exact domain weights from the design. Convert candidate p95 loss/p05 gain summaries to average-tie percentile loss ranks. A metric with zero observations receives loss rank `1.0`; covariance, matching, and OOD availability have explicit coverage inputs. Compute free parameter counts from K, d, and covariance type.

Return immutable `SelectionResult` with:

```python
status: Literal["ranked_but_not_qualified", "qualification_required", "no_eligible_candidate"]
provisional_ranking: tuple[RankedCandidate, ...]
qualified_ranking: tuple[RankedCandidate, ...]
selected_candidate_id: None
policy_hash: str | None
```

Apply absolute policy before qualified ranking. Use the approved `0.01` score tie band and six tie-breaks. This task never returns `selected`; only the multi-init qualification task may do that.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_pseudo_oos_selection.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/application/services/cluster_pseudo_oos_selection.py tests/application/services/test_cluster_pseudo_oos_selection.py
git commit -m "feat: rank and qualify cluster candidates"
```

### Task 8: Add Multi-Init Qualification and Gate Calibration

**Files:**
- Modify: `src/application/services/cluster_pseudo_oos_selection.py`
- Modify: `tests/application/services/test_cluster_pseudo_oos_selection.py`

- [ ] **Step 1: Write failing qualification and quantile-provenance tests**

```python
def test_qualification_uses_same_seed_with_n_init_20(qualification_runner, permissive_policy):
    result = qualification_runner.run(
        candidate_id="core25_v1__gmm-diag-k4",
        representative_seed=20260723,
        policy=permissive_policy,
    )
    assert len(result.receipts) == 24
    assert {row.n_init for row in result.receipts} == {20}
    assert {row.seed for row in result.receipts} == {20260723}


def test_gate_receipt_preserves_all_raw_values_and_driver():
    receipt = calibrate_fold_gate(
        "overall_ood_rate",
        expanding=tuple(float(value) for value in range(12)),
        rolling=tuple(float(value) for value in range(12, 24)),
        direction="high",
    )
    assert len(receipt.expanding_raw_values) == 12
    assert len(receipt.rolling_raw_values) == 12
    assert receipt.dominant_scheme == "rolling"
    assert receipt.maximum == 23
    assert len(receipt.interpolation_folds) == 2
    assert receipt.median_absolute_deviation >= 0


def test_failed_multi_init_qualification_does_not_fallback(qualification_runner, strict_policy):
    result = qualification_runner.run_top_only(strict_policy)
    assert result.status == "no_eligible_candidate"
    assert result.attempted_candidate_ids == (result.ranked_candidate_ids[0],)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_pseudo_oos_selection.py -q`

Expected: missing qualification/gate functions fail.

- [ ] **Step 3: Implement qualification and gate receipts**

Qualification clones the winner config with `n_init=20` and the representative seed, reruns all 24 folds, and reapplies every non-seed absolute criterion. Seed ARI/NMI remain sourced from the n-init-1 grid. No second-ranked fallback is allowed.

Add an immutable final qualification result whose status is `Literal["selected", "no_eligible_candidate"]`. `run_top_only` accepts only a `SelectionResult` in `qualification_required` state, records the single attempted candidate ID, returns `selected` only when all 24 qualification receipts are terminal and every non-seed absolute criterion passes, and otherwise returns `no_eligible_candidate` without changing the qualified ranking. A policy-free `ranked_but_not_qualified` result cannot enter this method.

Implement `linear_quantile_receipt(values, q)` using sorted values, position `(n-1)*q`, lower/upper indices, and linear interpolation weights. `calibrate_fold_gate` stores 12+12 raw values, p95/p05, min/max, median, unscaled MAD, interpolation fold IDs/weights, maximum fold, and dominant scheme. K-Means gate input is normalized-distance margin only.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/application/services/test_cluster_pseudo_oos_selection.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/application/services/cluster_pseudo_oos_selection.py tests/application/services/test_cluster_pseudo_oos_selection.py
git commit -m "feat: qualify and calibrate cluster selection"
```

### Task 9: Implement Canonical Checkpoints and Immutable Publication

**Files:**
- Create: `src/infrastructure/regime/pseudo_oos_checkpoint.py`
- Create: `tests/infrastructure/regime/test_pseudo_oos_checkpoint.py`

- [ ] **Step 1: Write failing checkpoint integrity tests**

```python
import pytest

from src.infrastructure.regime.pseudo_oos_checkpoint import (
    CheckpointStore,
    build_run_identity,
    verify_terminal_completeness,
)


def test_checkpoint_namespace_prevents_capability_reuse_in_formal(tmp_path, completed_job):
    store = CheckpointStore(tmp_path)
    store.put("capability", completed_job)
    assert store.get("formal", completed_job.key) is None


def test_corrupt_checkpoint_is_never_reused(tmp_path, completed_job):
    store = CheckpointStore(tmp_path)
    path = store.put("formal", completed_job)
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="checkpoint"):
        store.get("formal", completed_job.key)


def test_terminal_completeness_requires_every_expected_key(expected_keys, terminal_receipts):
    with pytest.raises(ValueError, match="terminal receipt"):
        verify_terminal_completeness(expected_keys, terminal_receipts[:-1])


def test_run_identity_changes_with_policy_hash(base_identity_payload):
    first = build_run_identity({**base_identity_payload, "absolute_quality_policy_hash": None})
    second = build_run_identity({**base_identity_payload, "absolute_quality_policy_hash": "a" * 64})
    assert first != second
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_pseudo_oos_checkpoint.py -q`

Expected: collection fails because the checkpoint module is absent.

- [ ] **Step 3: Implement canonical storage and atomic publication**

Use `json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"`. Store each checkpoint as an envelope containing schema version, namespace, job key, payload SHA-256, implementation hash, and payload. Write to a temporary sibling, flush/fsync, then replace. On read, validate every identity/hash before returning.

`build_run_identity` hashes design hash, implementation hash, source provenance hash, feature/fold/candidate registries, seed list, phase, and absolute-policy hash. `verify_terminal_completeness` requires exactly the expected 28,800 unique keys with status completed/rejected.

`publish_run_directory(staging, final)` must reject an existing final directory, symlink/junction traversal, missing manifest, or manifest hash mismatch; then atomically rename staging to the deterministic final path. Failed/incomplete runs remain outside the immutable `runs/<run_id>` namespace.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/regime/test_pseudo_oos_checkpoint.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/infrastructure/regime/pseudo_oos_checkpoint.py tests/infrastructure/regime/test_pseudo_oos_checkpoint.py
git commit -m "feat: checkpoint pseudo-OOS research jobs"
```

### Task 10: Build the Capability and Formal CLI Orchestrator

**Files:**
- Create: `scripts/cluster_development_pseudo_oos.py`
- Create: `tests/test_cluster_development_pseudo_oos.py`

- [ ] **Step 1: Write failing CLI and access-boundary tests**

```python
from pathlib import Path

import pytest

import scripts.cluster_development_pseudo_oos as cli


def test_capability_plan_is_600_fits_and_cannot_publish_selection():
    plan = cli.build_capability_plan()
    assert len(plan.synthetic_jobs) == 120
    assert len(plan.real_jobs) == 480
    assert plan.can_publish_selection is False


def test_formal_plan_is_exact_and_strategy_free():
    plan = cli.build_formal_plan()
    assert len(plan.job_keys) == 28_800
    source = Path(cli.__file__).read_text(encoding="utf-8")
    forbidden = ("strategy_mapping", "daily_strategy_evidence", "validation_evidence", "test_evidence")
    assert not any(name in source for name in forbidden)


def test_loader_uses_only_lookback_and_cluster_development(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli, "load_three_day_feature_history", recording_loader(seen))
    cli.load_cluster_development_vectors(tmp_path)
    assert seen["start"].isoformat() == "2020-12-29T00:00:00+00:00"
    assert seen["end"].isoformat() == "2025-06-30T00:00:00+00:00"
    assert seen["expected_anchor_count"] == 1641


def test_policy_free_formal_fixture_is_ranked_not_qualified(tmp_path, tiny_vector_source):
    result = cli.run_formal_fixture(tmp_path, vector_source=tiny_vector_source, policy_path=None)
    assert result.selection_status == "ranked_but_not_qualified"
    assert result.model_artifact_path is None
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cluster_development_pseudo_oos.py -q`

Expected: import fails because the CLI is absent.

- [ ] **Step 3: Implement CLI arguments and orchestration**

Required arguments:

```text
--phase capability|formal
--raw-root PATH
--output-root PATH                  default .research-data/cluster-development-pseudo-oos
--absolute-quality-policy PATH      optional and hashed before job execution
--workers INTEGER                   positive, default min(physical cores, 8)
--resume                            reuse only verified same-namespace checkpoints
```

`load_cluster_development_vectors` calls the existing verified loader with raw start `2020-12-29`, end `2025-06-30`, and expected count 1,641, then validates the exact anchor interval. Build capability jobs in their own namespace and never feed their outputs to formal aggregation.

For formal execution, schedule sorted missing job keys with `ProcessPoolExecutor`; worker entry points must be top-level/pickleable and wrap estimator calls in `threadpool_limits(1)`. Persist each terminal result immediately. After all futures complete, verify all 28,800 receipts before aggregation. If interrupted, retain verified checkpoints but write only an incomplete local receipt, not a published run.

- [ ] **Step 4: Run CLI tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cluster_development_pseudo_oos.py -q`

Expected: all tests pass using fixtures; no real 28,800-job run occurs in tests.

- [ ] **Step 5: Commit**

```powershell
git add scripts/cluster_development_pseudo_oos.py tests/test_cluster_development_pseudo_oos.py
git commit -m "feat: orchestrate pseudo-OOS cluster selection"
```

### Task 11: Render Deterministic Outputs and Manifests

**Files:**
- Modify: `scripts/cluster_development_pseudo_oos.py`
- Modify: `tests/test_cluster_development_pseudo_oos.py`

- [ ] **Step 1: Write failing output-contract tests**

```python
EXPECTED_FILES = {
    "design_receipt.json",
    "data_access_receipt.json",
    "feature_sets.json",
    "folds.json",
    "candidate_registry.json",
    "fit_receipts.jsonl",
    "fold_metrics.csv",
    "seed_stability.csv",
    "candidate_summary.json",
    "leaderboard.csv",
    "absolute_quality_policy.json",
    "qualification_receipts.jsonl",
    "gate_calibration.json",
    "selection_receipt.json",
    "report.md",
    "manifest.json",
}


def test_policy_free_fixture_publishes_exact_ranked_output_set(tmp_path, completed_fixture_run):
    output = completed_fixture_run.publish(tmp_path)
    assert {path.name for path in output.iterdir()} == EXPECTED_FILES
    assert read_json(output / "selection_receipt.json")["status"] == "ranked_but_not_qualified"
    assert read_json(output / "absolute_quality_policy.json")["status"] == "not_supplied"
    assert read_json(output / "gate_calibration.json")["status"] == "not_run"


def test_output_is_byte_identical_for_same_input(tmp_path, completed_fixture_run):
    first = completed_fixture_run.render_all()
    second = completed_fixture_run.render_all()
    assert first == second
    assert verify_manifest_bytes(first)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cluster_development_pseudo_oos.py -q`

Expected: failures list missing renderer/publication outputs.

- [ ] **Step 3: Implement canonical renderers**

Sort every row by canonical job/candidate/fold/component key. Use `newline=""` and `lineterminator="\n"` for CSV, canonical JSON for JSON/JSONL, and ASCII field names. `manifest.json` contains schema version, run ID, implementation hash, design hash, parent source hashes, and SHA-256/byte count for every other file. The manifest does not hash itself, and no hashed child file embeds the manifest hash; an auditor computes the manifest SHA-256 after publication.

For policy-free runs, render explicit not-supplied/not-run receipts rather than omitting files. `report.md` must lead with `ranked_but_not_qualified`, state that no model was selected/frozen, show the provisional leaderboard, rejected-job counts, metric coverage, and the Strategy/Mapping/Validation/Test access boundary.

- [ ] **Step 4: Run output tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cluster_development_pseudo_oos.py -q`

Expected: all tests pass and repeated renders are byte-identical.

- [ ] **Step 5: Commit**

```powershell
git add scripts/cluster_development_pseudo_oos.py tests/test_cluster_development_pseudo_oos.py
git commit -m "feat: publish pseudo-OOS selection receipts"
```

### Task 12: Verify Capability End-to-End and Regression Safety

**Files:**
- Modify: `tests/test_cluster_development_pseudo_oos.py`
- Modify: `docs/superpowers/specs/2026-07-20-cluster-development-pseudo-oos-model-selection-design.md` only if implementation reveals a contract mismatch; any semantic change requires user review before continuing.

- [ ] **Step 1: Add the end-to-end synthetic capability test**

```python
def test_synthetic_capability_covers_every_candidate_shape(tmp_path):
    result = run_synthetic_capability(output_root=tmp_path, seeds=(20260720, 20260739))
    assert result.fit_count == 120
    assert result.candidate_count == 60
    assert result.selection_status is None
    assert result.rejected_count == 0
    assert result.can_publish_selection is False
    assert {row.config.covariance_type for row in result.completed if row.config.model_type == "gmm"} == {
        "diag", "tied", "full", "spherical"
    }
```

Build the synthetic fixture as eight well-separated Gaussian groups with 64 rows each and all 25 `core25_v1` dimensions, then derive the 22-feature matrix through the frozen feature-set registry. This gives every K/covariance candidate enough support without using market results.

- [ ] **Step 2: Run the focused pseudo-OOS suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/domain/regime/test_pseudo_oos.py `
  tests/application/services/test_cluster_development_folds.py `
  tests/infrastructure/regime/test_sklearn_pseudo_oos.py `
  tests/application/services/test_cluster_pseudo_oos_metrics.py `
  tests/application/services/test_cluster_pseudo_oos_selection.py `
  tests/infrastructure/regime/test_pseudo_oos_checkpoint.py `
  tests/test_cluster_development_pseudo_oos.py -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run existing regime regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/domain/regime `
  tests/application/services/test_regime_balance_diagnostics.py `
  tests/infrastructure/regime `
  tests/test_chart_regime_balance_diagnostic.py `
  tests/test_chart_regime_historical_replay.py -q
```

Expected: all selected regression tests pass; no runtime model/artifact behavior changes.

- [ ] **Step 4: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: full suite passes. Existing environment-only warnings about physical-core detection or Windows subprocess decoding may remain, but no new warnings are accepted.

- [ ] **Step 5: Audit forbidden dependencies and worktree state**

Run:

```powershell
rg -n "strategy_mapping|daily_strategy_evidence|mapping_evidence|validation_evidence|test_evidence|PnL|Sharpe" `
  src/domain/regime/pseudo_oos.py `
  src/application/services/cluster_development_folds.py `
  src/application/services/cluster_pseudo_oos_metrics.py `
  src/application/services/cluster_pseudo_oos_selection.py `
  src/infrastructure/regime/sklearn_pseudo_oos.py `
  src/infrastructure/regime/pseudo_oos_checkpoint.py `
  scripts/cluster_development_pseudo_oos.py
git status --short
```

Expected: `rg` returns no matches; Git shows only the intended implementation/test changes before the final commit.

- [ ] **Step 6: Commit final verification fixtures**

```powershell
git add tests/test_cluster_development_pseudo_oos.py
git commit -m "test: verify pseudo-OOS capability pipeline"
```

## Execution Boundary After This Plan

After Tasks 1–12 pass, run only the capability phase first. Review its terminal receipts and resource estimate. Do not remove candidates based on capability output. The formal 28,800-job baseline run requires a separate explicit execution decision because it is long-running and may acquire/consume substantial local research data and compute.

The first policy-free formal result must be `ranked_but_not_qualified`; it cannot create a model artifact. A later absolute-quality policy requires its own reviewed Cluster Development baseline provenance and hash before a qualification or freeze run is authorized.
