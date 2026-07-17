# Frozen K4 Diagnosis Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a new immutable frozen-K4 completion run that explains Component 0's 24 OOD exceedances and tests the full-sample empirical drift/OOD conclusions across every 3-day and 7-day offset without any offset refit, rematch, or gate decision.

**Architecture:** Leave the existing frozen replay command, manifest contract, and published run byte-identical. Add a pure completion service that consumes the already reproduced replay and decomposition, then add a separate publisher that validates the prior run as parent provenance and writes a schema-versioned deterministic run under a different output root.

**Tech Stack:** Python 3.11, frozen dataclasses, NumPy, existing SciPy/scikit-learn replay objects, canonical JSON/CSV, SHA-256, pytest 9.

---

## File map

- Create `src/domain/regime/frozen_k4_diagnosis_completion.py`: completion schema constants, fixed thresholds, output filename set, and immutable completion-manifest contract.
- Create `src/application/services/frozen_k4_diagnosis_completion.py`: pure Component 0 OOD aggregation, registry provenance, full-sample empirical reference, offset empirical/OOD summaries, and consistency flags.
- Create `scripts/complete_frozen_three_day_k4_diagnosis.py`: parent-run validation, existing replay invocation, completion rendering, deterministic run identity, and atomic publication to a new root.
- Create `scripts/audit_frozen_k4_diagnosis_completion.py`: independent child/parent hash, sample receipt, aggregate, empirical, offset, and Markdown verification without importing completion calculation or rendering helpers.
- Create `tests/domain/regime/test_frozen_k4_diagnosis_completion.py`: manifest and fixed-policy contract tests.
- Create `tests/application/services/test_frozen_k4_diagnosis_completion.py`: arithmetic, tie-breaking, offset, and no-refit unit tests.
- Create `tests/test_complete_frozen_three_day_k4_diagnosis.py`: renderer, parent immutability, run identity, isolation, and byte-determinism tests.
- Create `tests/test_audit_frozen_k4_diagnosis_completion.py`: independent auditor tamper and reconciliation tests.
- Create the seven files listed in Task 9 under `docs/backtests/frozen_k4_diagnosis_completion/<run_id>/`: the final forced-added completion evidence only after all tests pass.
- Do not modify `scripts/diagnose_frozen_three_day_k4_failure.py`, `src/domain/regime/frozen_k4_failure_diagnostics.py`, or the existing directory `docs/backtests/frozen_k4_failure_diagnosis/d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af`.

The parent artifacts do not contain the complete half-fit parameters or assignment ledger. Therefore the standalone completion command must invoke the existing frozen replay once to reproduce exactly Half A and Half B. The no-fit/no-rematch invariant begins at the post-reproduction `complete_frozen_k4_diagnosis` boundary: it permits only those two already specified half fits and forbids every offset-specific or additional fit, scale fit, projection fit, rematch, gate decision, or artifact creation.

## Task 1: Freeze the completion identity and manifest contract

**Files:**
- Create: `src/domain/regime/frozen_k4_diagnosis_completion.py`
- Create: `tests/domain/regime/test_frozen_k4_diagnosis_completion.py`

- [ ] **Step 1: Write RED tests for schema identity, fixed policy, and manifest validation**

Add tests that import the following public constants and type, assert the exact values, construct a valid manifest, and reject a bad schema, parent hash, run ID, scope, threshold, filename set, or replacement flag:

```python
from src.domain.regime.frozen_k4_diagnosis_completion import (
    ANALYSIS_SCOPE,
    COMPLETION_ARTIFACT_FILENAMES,
    DIAGNOSTIC_SCHEMA_VERSION,
    RECURRENT_TOP1_THRESHOLD,
    SINGLE_FEATURE_THRESHOLD,
    VOLATILITY_FAMILY_THRESHOLD,
    FrozenK4DiagnosisCompletionManifest,
)


def test_completion_policy_is_frozen_before_analysis() -> None:
    assert DIAGNOSTIC_SCHEMA_VERSION == "frozen-k4-diagnosis-completion-v1"
    assert ANALYSIS_SCOPE == "primary-component-0-ood-exceedances"
    assert SINGLE_FEATURE_THRESHOLD == 0.50
    assert VOLATILITY_FAMILY_THRESHOLD == 0.70
    assert RECURRENT_TOP1_THRESHOLD == 0.50


def test_manifest_binds_parent_registry_policy_and_exact_files() -> None:
    manifest = FrozenK4DiagnosisCompletionManifest(
        run_id="a" * 64,
        parent_run_id="b" * 64,
        parent_manifest_sha256="c" * 64,
        input_identity_sha256="d" * 64,
        registry_schema_version="btc-chart-regime-ohlcv-3d-v1",
        registry_sha256="e" * 64,
        analysis_scope=ANALYSIS_SCOPE,
        thresholds={
            "single_feature_contribution_ratio": 0.50,
            "volatility_family_contribution_ratio": 0.70,
            "recurrent_feature_top1_ratio": 0.50,
        },
        file_sha256={name: "f" * 64 for name in COMPLETION_ARTIFACT_FILENAMES},
        file_bytes={name: 1 for name in COMPLETION_ARTIFACT_FILENAMES},
    )
    payload = manifest.canonical_payload()
    assert payload["diagnostic_schema_version"] == DIAGNOSTIC_SCHEMA_VERSION
    assert payload["parent_run_id"] == "b" * 64
    assert set(payload["file_sha256"]) == COMPLETION_ARTIFACT_FILENAMES
    assert set(payload["file_bytes"]) == COMPLETION_ARTIFACT_FILENAMES
    assert payload["diagnostic_only"] is True
    assert payload["primary_replacement_allowed"] is False
```

Use parametrized invalid cases to require lowercase canonical SHA-256 strings, the exact three threshold keys and values, canonical basenames, and this exact artifact set:

```python
COMPLETION_ARTIFACT_FILENAMES = frozenset({
    "frozen_k4_diagnosis_completion.json",
    "frozen_k4_component_0_ood_feature_summary.csv",
    "frozen_k4_component_0_ood_family_summary.csv",
    "frozen_k4_offset_empirical_diagnostics.csv",
    "frozen_k4_offset_feature_contributions.csv",
    "frozen_k4_diagnosis_completion.md",
})
```

- [ ] **Step 2: Run the domain tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_frozen_k4_diagnosis_completion.py -q
```

Expected: collection fails with `ModuleNotFoundError: src.domain.regime.frozen_k4_diagnosis_completion`.

- [ ] **Step 3: Implement the immutable policy and manifest**

Create the module with the exact constants above and a frozen dataclass with these fields:

```python
@dataclass(frozen=True)
class FrozenK4DiagnosisCompletionManifest:
    run_id: str
    parent_run_id: str
    parent_manifest_sha256: str
    input_identity_sha256: str
    registry_schema_version: str
    registry_sha256: str
    analysis_scope: str
    thresholds: Mapping[str, float]
    file_sha256: Mapping[str, str]
    file_bytes: Mapping[str, int]
    diagnostic_schema_version: str = DIAGNOSTIC_SCHEMA_VERSION
    status: str = "completed"
    diagnostic_only: bool = True
    primary_replacement_allowed: bool = False
```

In `__post_init__`, validate all hashes, exact schema/scope/status/policy values, exact file basenames, positive integer byte counts, and identical exact filename sets in `file_sha256` and `file_bytes`; copy all mappings into `MappingProxyType`. Implement `canonical_payload()` with fields in semantic order and ordinary dictionaries for canonical serialization. Export only the constants and manifest type in `__all__`.

- [ ] **Step 4: Run the domain tests and verify GREEN**

Run the same pytest command. Expected: all tests in the new file pass.

- [ ] **Step 5: Commit the contract**

```powershell
git add src/domain/regime/frozen_k4_diagnosis_completion.py tests/domain/regime/test_frozen_k4_diagnosis_completion.py
git commit -m "feat: define frozen K4 completion contract"
```

## Task 2: Aggregate Component 0 OOD feature and family contributions

**Files:**
- Create: `src/application/services/frozen_k4_diagnosis_completion.py`
- Create: `tests/application/services/test_frozen_k4_diagnosis_completion.py`

- [ ] **Step 1: Write RED tests for the exact Component 0 population and feature statistics**

Build a fixture containing `OODComponentRow(0, fingerprint, 409, 24, 24 / 409)` and exactly 24 `OODSampleContributionRow` values for Component 0. Use all retained frozen feature names in registry order, with controlled nonzero contributions for `rv_4h`, `rv_1d`, `range_ratio_3d`, and `volume_cv_3d`. Assert:

```python
analysis = summarize_component_zero_ood(
    decomposition,
    retained_feature_names=FROZEN_NAMES,
    registry=THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    registry_schema_version=THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)

assert analysis.analysis_scope == "primary-component-0-ood-exceedances"
assert analysis.primary_component_index == 0
assert analysis.assigned_sample_count == 409
assert analysis.ood_sample_count == 24
assert analysis.feature_rows[0].rank == 1
assert sum(row.contribution_sum for row in analysis.feature_rows) == pytest.approx(
    sum(row.squared_mahalanobis for row in decomposition.ood_samples)
)
assert all(row.registry_sha256 == analysis.registry_sha256 for row in analysis.feature_rows)
```

For a chosen feature, hand-calculate and assert contribution sum, overall ratio, mean, median, top-1 count/ratio, and top-5 count/ratio. Add a sample-level tie and require registry order, not alphabetical order, to decide top-1/top-5.

- [ ] **Step 2: Write RED tests for strict registry families and fixed boundary flags**

Assert that only `rv_4h`, `rv_1d`, `rv_3d`, and `rv_ratio_1d_3d` feed the volatility total; `range_ratio_3d` and `volume_cv_3d` must stay in their registry families. Require one family row for every retained family and assert the three independent flags immediately below, exactly at, and above `0.50`, `0.70`, and `0.50`.

Each family row must expose:

```python
assert volatility.family_name == "volatility"
assert volatility.family_feature_names == (
    "rv_4h", "rv_1d", "rv_3d", "rv_ratio_1d_3d"
)
assert volatility.concentration_threshold == 0.70
assert volatility.concentration_rule_applies is True
assert range_row.concentration_rule_applies is False
```

Also reject 23 or 25 Component 0 OOD rows, a denominator other than 409, a per-sample contribution sum that does not reproduce `squared_mahalanobis`, a missing retained registry feature, duplicate feature names, non-finite values, and any Component 0 OOD row whose strict-exceedance population is inconsistent with the component summary.

Add a canonical-hash test that repeated calls are identical, reversing registry order changes the hash, and changing any one of the five admitted registry fields changes the hash. Changing an unrelated object outside the registry payload must not change it.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/services/test_frozen_k4_diagnosis_completion.py -q
```

Expected: collection fails because the completion service does not exist.

- [ ] **Step 4: Implement immutable OOD summary contracts and registry hashing**

Add frozen dataclasses:

```python
@dataclass(frozen=True)
class OODFeatureSummaryRow:
    analysis_scope: str
    primary_component_index: int
    feature_name: str
    registry_family: str
    registry_schema_version: str
    registry_sha256: str
    contribution_sum: float
    contribution_ratio: float
    contribution_mean: float
    contribution_median: float
    top1_count: int
    top1_ratio: float
    top5_count: int
    top5_ratio: float
    rank: int


@dataclass(frozen=True)
class OODFamilySummaryRow:
    analysis_scope: str
    primary_component_index: int
    family_name: str
    family_feature_names: tuple[str, ...]
    registry_schema_version: str
    registry_sha256: str
    contribution_sum: float
    contribution_ratio: float
    concentration_threshold: float
    concentration_rule_applies: bool
    concentration_result: bool


@dataclass(frozen=True)
class ComponentZeroOODAnalysis:
    analysis_scope: str
    primary_component_index: int
    assigned_sample_count: int
    ood_sample_count: int
    registry_schema_version: str
    registry_sha256: str
    feature_rows: tuple[OODFeatureSummaryRow, ...]
    family_rows: tuple[OODFamilySummaryRow, ...]
    top_five_features: tuple[str, ...]
    single_feature_concentration: bool
    volatility_family_concentration: bool
    recurrent_feature_dominance: bool
    diagnostic_only: bool = True
```

Implement `_canonical_registry_sha256()` with canonical UTF-8 JSON over schema version, ordered retained names, and exactly the full ordered V1 registry fields `name`, `family`, `aggregation_minutes`, `lookback_minutes`, and `formula`. Use compact separators, `sort_keys=True`, and `allow_nan=False`. Do not reuse or change the parent's `feature_schema_sha256`, whose frozen payload includes additional policy fields.

- [ ] **Step 5: Implement the OOD aggregation minimally**

Implement `summarize_component_zero_ood` with the signature shown in Step 1 by filtering existing `decomposition.ood_samples`, never recomputing assignments or distances. Validate the 24/409 scope before aggregation. For each sample, order feature contributions by descending value then retained registry position. Aggregate with NumPy mean/median, rank totals by descending contribution then registry position, and calculate the three flags with inclusive `>=` comparisons.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Task 2 pytest command. Expected: all Component 0, family, boundary, tie, and validation tests pass.

- [ ] **Step 7: Commit the OOD analysis**

```powershell
git add src/application/services/frozen_k4_diagnosis_completion.py tests/application/services/test_frozen_k4_diagnosis_completion.py
git commit -m "feat: summarize component zero OOD causes"
```

## Task 3: Compute a directly comparable full-sample empirical reference

**Files:**
- Modify: `src/application/services/frozen_k4_diagnosis_completion.py`
- Modify: `tests/application/services/test_frozen_k4_diagnosis_completion.py`

- [ ] **Step 1: Write RED tests for frozen-primary projection and empirical centroids**

Construct a small two-half `FrozenK4Replay` fixture with fixed half assignments and fixed matched pairs. Give the primary fit nontrivial lower/upper bounds, medians, scales, means, and feature order. Hand-calculate the primary-coordinate vectors and assert:

```python
reference = build_full_sample_empirical_reference(replay, primary_fit, vectors)

assert {row.metric_name for row in reference.centroid_rows} == {
    "full_sample_empirical_centroid_distance"
}
row = next(
    item for item in reference.centroid_rows
    if item.half_label == "A" and item.primary_component_index == 0
)
assert row.assignment_source == "frozen_reproduced_half_assignment"
assert row.sample_count == 2
assert row.sample_share == pytest.approx(2 / 3)
assert row.empirical_centroid == pytest.approx(expected_centroid)
assert row.distance == pytest.approx(expected_distance)
assert sum(
    item.squared_distance
    for item in reference.feature_rows
    if item.scope_key == row.scope_key
) == pytest.approx(row.distance**2)
```

Prove that membership comes from `half.assignments` mapped through the existing `matched_pairs`, not from `replay.primary_assignments`. Include an empty matched component and require `centroid_status="insufficient_sample"`, null centroid/distance, and exclusion from the maximum. Include a one-sample component and require a valid descriptive centroid.

- [ ] **Step 2: Write RED tests for fixed maximum and feature tie rules**

Require maximum distance ties to resolve by half label, primary component index, then half component index. Require feature contribution ties to resolve by frozen registry position. Assert the maximum row and its ordered top five are stored in the full-sample summary.

- [ ] **Step 3: Run the empirical-reference tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/services/test_frozen_k4_diagnosis_completion.py -q -k "full_sample or empirical_centroid or primary_projection"
```

Expected: failures report missing empirical contracts/functions.

- [ ] **Step 4: Add the empirical result contracts**

Add frozen contracts with explicit scope fields:

```python
@dataclass(frozen=True)
class EmpiricalCentroidRow:
    sample_scope: str
    spacing_days: int | None
    offset: int | None
    offset_origin_anchor: str
    half_label: str
    primary_component_index: int
    half_component_index: int
    primary_component_fingerprint: str
    sample_count: int
    sample_share: float
    centroid_status: str
    metric_name: str
    empirical_centroid: tuple[float, ...] | None
    distance: float | None
    assignment_source: str = "frozen_reproduced_half_assignment"
    refit_performed: bool = False
    rematch_performed: bool = False
    diagnostic_only: bool = True


@dataclass(frozen=True)
class EmpiricalFeatureContributionRow:
    sample_scope: str
    spacing_days: int | None
    offset: int | None
    half_label: str
    primary_component_index: int
    half_component_index: int
    feature_name: str
    registry_family: str
    squared_distance: float
    contribution_ratio: float
    rank: int


@dataclass(frozen=True)
class EmpiricalScopeSummary:
    sample_scope: str
    spacing_days: int | None
    offset: int | None
    selected_sample_count: int
    centroid_rows: tuple[EmpiricalCentroidRow, ...]
    feature_rows: tuple[EmpiricalFeatureContributionRow, ...]
    maximum_drift_half_label: str
    maximum_drift_primary_component_index: int
    maximum_drift_half_component_index: int
    maximum_drift_distance: float
    top_five_drift_features: tuple[str, ...]
```

- [ ] **Step 5: Implement the one-scope empirical kernel and full-sample wrapper**

Implement `_primary_scaled_matrix()` as `clip(raw, lower_bounds, upper_bounds)`, then `(clipped - medians) / scales`. Implement `_build_empirical_scope(replay, primary_fit, vectors, primary_scaled, selected_indices, sample_scope, spacing_days, offset)` once and call it from `build_full_sample_empirical_reference()` with every global index. Slice half assignments only by existing half receipt counts, map each half component through `matched_pairs`, and never call a fitter, scaler `.fit`, projector, or matcher.

- [ ] **Step 6: Run the empirical-reference tests and verify GREEN**

Run the Step 3 command. Expected: all selected tests pass.

- [ ] **Step 7: Commit the full-sample reference**

```powershell
git add src/application/services/frozen_k4_diagnosis_completion.py tests/application/services/test_frozen_k4_diagnosis_completion.py
git commit -m "feat: add full sample empirical drift reference"
```

## Task 4: Add every 3-day and 7-day offset plus OOD consistency

**Files:**
- Modify: `src/application/services/frozen_k4_diagnosis_completion.py`
- Modify: `tests/application/services/test_frozen_k4_diagnosis_completion.py`

- [ ] **Step 1: Write RED tests for global-index offset selection**

Use 23 ordered anchors and assert selection uses global position `index % spacing == offset`, with exactly `(3 + 7) = 10` offset summaries. For each spacing, concatenate and sort selected indices from all offsets and require every full index exactly once. Assert the origin is the first full-sample anchor and that half boundaries do not restart the modulo sequence.

- [ ] **Step 2: Write RED tests for fixed-assignment offset centroids and OOD rows**

Call the completion function with fit/rematch seams monkeypatched to raise. Assert each offset reuses the same primary transform, half assignments, matches, `primary_ood_rows`, squared distances, and thresholds. Require one OOD diagnostic per frozen primary component per offset, including zero-exceedance rows and null rate when denominator is zero.

Use this exact OOD maximum ordering: rate descending, numerator descending, denominator descending, component index ascending. Assert no offset result contains a newly fitted object or gate result.

- [ ] **Step 3: Write RED tests for empirical-to-empirical consistency flags**

Create offsets that exercise all four comparisons:

```python
assert conclusion.drift_component_matches_full_sample is True
assert conclusion.ood_component_matches_full_sample is False
assert conclusion.ordered_top5_matches_full_sample is False
assert conclusion.top5_set_matches_full_sample is True
```

Require consistency to compare against `full_sample_empirical_centroid_distance`, never the existing fitted-parameter `pair.euclidean_distance`. Add a regression in which those two full-sample maxima differ and assert the empirical component is used.

- [ ] **Step 4: Run offset tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/services/test_frozen_k4_diagnosis_completion.py -q -k "offset or ood_consistency or no_refit"
```

Expected: failures report missing offset/OOD contracts and coordinator.

- [ ] **Step 5: Implement offset OOD and conclusion contracts**

Add:

```python
@dataclass(frozen=True)
class OffsetOODRow:
    sample_scope: str
    spacing_days: int | None
    offset: int | None
    primary_component_index: int
    primary_component_fingerprint: str
    numerator: int
    denominator: int
    rate: float | None
    distance_source: str = "existing_primary_ood_row"
    threshold_source: str = "frozen_component_chi_square_threshold"


@dataclass(frozen=True)
class OffsetConclusion:
    spacing_days: int
    offset: int
    maximum_drift_primary_component_index: int
    maximum_ood_primary_component_index: int
    top_five_drift_features: tuple[str, ...]
    drift_component_matches_full_sample: bool
    ood_component_matches_full_sample: bool
    ordered_top5_matches_full_sample: bool
    top5_set_matches_full_sample: bool


@dataclass(frozen=True)
class FixedSampleReceipt:
    global_index: int
    anchor_at: str
    half_label: str
    half_component_index: int
    matched_primary_component_index: int
    primary_component_index: int
    squared_mahalanobis: float
    ood_threshold: float
    ood_exceeds: bool
    assignment_source: str = "existing_reproduced_assignments"


@dataclass(frozen=True)
class FrozenK4DiagnosisCompletion:
    component_zero_ood: ComponentZeroOODAnalysis
    full_sample_empirical: EmpiricalScopeSummary
    full_sample_ood: tuple[OffsetOODRow, ...]
    offset_empirical: tuple[EmpiricalScopeSummary, ...]
    offset_ood: tuple[OffsetOODRow, ...]
    offset_conclusions: tuple[OffsetConclusion, ...]
    sample_receipts: tuple[FixedSampleReceipt, ...]
    diagnostic_only: bool = True
```

- [ ] **Step 6: Implement the coordinator with no new model operation**

Implement:

```python
def complete_frozen_k4_diagnosis(
    replay: FrozenK4Replay,
    primary_fit: object,
    vectors: tuple[object, ...],
    decomposition: FrozenK4Decomposition,
) -> FrozenK4DiagnosisCompletion:
    """Return immutable descriptive completion evidence from fixed replay state."""
```

Validate reproduced status, tuple inputs, one-to-one vector/assignment/OOD lengths, exact half receipt coverage, and registry compatibility. First create one ordered `FixedSampleReceipt` per anchor by joining existing half assignments/matches, primary assignments, and primary OOD rows without recalculation. Build the full-sample empirical and OOD references next. Loop spacings `(3, 7)` and offsets `range(spacing)`, pass the global selected indices to the same empirical kernel, filter existing OOD rows by those indices, and then calculate the four consistency booleans.

- [ ] **Step 7: Run the full service test file and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/services/test_frozen_k4_diagnosis_completion.py -q
```

Expected: all OOD, full-sample, offset, empty/one-sample, tie, consistency, immutability, and isolation tests pass.

- [ ] **Step 8: Commit the offset analysis**

```powershell
git add src/application/services/frozen_k4_diagnosis_completion.py tests/application/services/test_frozen_k4_diagnosis_completion.py
git commit -m "feat: compare frozen K4 offset diagnostics"
```

## Task 5: Validate the immutable parent and derive the child identity

**Files:**
- Create: `scripts/complete_frozen_three_day_k4_diagnosis.py`
- Create: `tests/test_complete_frozen_three_day_k4_diagnosis.py`

- [ ] **Step 1: Write RED parent-validation and snapshot tests**

Create a temporary parent run with a valid existing `FrozenK4DiagnosisManifest` and byte payloads. Test that the parent loader and child-identity helper:

- validates every parent `file_sha256` before analysis;
- validates `parent_manifest.run_id == parent_dir.name`;
- requires parent status `reproduced`;
- requires parent `input_identity_sha256` to equal the reconstructed source identity hash;
- records the SHA-256 of the exact parent `manifest.json` bytes;
- reject a completion output root inside the parent run;
- leave `_directory_bytes(parent_dir)` exactly unchanged on successful and failed validation.

Reject a missing file, extra file, nested entry, symlink/reparse point, corrupt file, mismatched run ID, mismatched input identity, a completion output root inside the parent run, and any identity that collides with the parent run ID.

- [ ] **Step 2: Write RED deterministic child identity tests**

Derive the child identity twice against byte-identical parent/source fixtures and assert the same child run ID. Change each of schema version, parent manifest hash, input identity hash, registry hash, or one fixed threshold and require a different identity or closed validation failure. Assert the run ID does not depend on output-root path or wall-clock time.

- [ ] **Step 3: Run publisher tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_complete_frozen_three_day_k4_diagnosis.py -q
```

Expected: collection fails because the completion script does not exist.

- [ ] **Step 4: Implement strict parent loading**

Add constants:

```python
DEFAULT_PARENT_RUN = REPO_ROOT / "docs" / "backtests" / "frozen_k4_failure_diagnosis" / "d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "docs" / "backtests" / "frozen_k4_diagnosis_completion"
```

Implement `_load_parent_provenance(parent_dir)` by bounded-reading `manifest.json`, rejecting noncanonical JSON values, reconstructing `FrozenK4DiagnosisManifest`, requiring its filename set plus manifest and no extras, hashing every referenced byte, and returning an immutable record with `run_id`, `manifest_sha256`, `input_identity_sha256`, and the full before-snapshot.

- [ ] **Step 5: Implement the child identity helper**

Implement `_completion_identity_payload(parent, input_identity_sha256, registry_schema_version, registry_sha256)` with the exact schema version, parent run/hash, input identity hash, registry schema/hash, analysis scope, and three fixed thresholds. Implement `_completion_run_id` as the canonical SHA-256 of that payload and reject equality with the parent run ID. Add argument parsing for `--parent-run`, `--model-attempt`, `--raw-kline-root`, and `--output-root`; Task 6 adds the production orchestration body.

The production orchestration must call, in order:

```python
source = load_frozen_k4_diagnostic_source(model_attempt, raw_kline_root)
replay = replay_frozen_k4_failures(source)
decomposition = decompose_frozen_k4_failure(
    replay, source.primary_fit, tuple(source.vectors)
)
completion = complete_frozen_k4_diagnosis(
    replay, source.primary_fit, tuple(source.vectors), decomposition
)
```

It must fail before rendering unless replay status is reproduced and the parent input identity matches. It must target only `DEFAULT_OUTPUT_ROOT / run_id` and compare the complete parent byte snapshot again before returning.

- [ ] **Step 6: Run publisher tests and verify GREEN**

Run the Task 5 pytest command. Expected: all parent validation, snapshot, identity, and collision tests pass.

- [ ] **Step 7: Commit the publication boundary**

```powershell
git add scripts/complete_frozen_three_day_k4_diagnosis.py tests/test_complete_frozen_three_day_k4_diagnosis.py
git commit -m "feat: bind K4 completion parent identity"
```

## Task 6: Render auditable CSV, JSON, and Markdown answers

**Files:**
- Modify: `scripts/complete_frozen_three_day_k4_diagnosis.py`
- Modify: `tests/test_complete_frozen_three_day_k4_diagnosis.py`

- [ ] **Step 1: Write RED schema tests for the Component 0 CSVs**

Require `frozen_k4_component_0_ood_feature_summary.csv` to contain the exact feature summary fields from Task 2 and every row to carry `analysis_scope`, `primary_component_index=0`, registry schema, registry hash, family, and rank. Require `frozen_k4_component_0_ood_family_summary.csv` to contain every retained registry family, ordered by registry first appearance, with feature names, contribution sum/ratio, threshold, applicability, and result.

- [ ] **Step 2: Write RED schema tests for empirical/offset CSVs**

Use a tagged-record schema in `frozen_k4_offset_empirical_diagnostics.csv`:

- `record_type=centroid` for every full-sample and offset half/component empirical row;
- `record_type=ood` for every full-sample and offset primary-component OOD row;
- `record_type=conclusion` for each of the ten offset comparison rows.

Require explicit `sample_scope`, nullable spacing/offset, origin anchor, counts/shares, status, metric name, distance, OOD numerator/denominator/rate, maximum flags, and all four consistency flags. Blank fields must serialize as empty CSV cells, never strings such as `None` or `nan`.

Require `frozen_k4_offset_feature_contributions.csv` to contain full-sample and offset feature rows with family, rank, squared distance, contribution ratio, and an `is_top_five` flag.

- [ ] **Step 3: Write RED JSON, Markdown, manifest, and byte tests**

Require `frozen_k4_diagnosis_completion.json` to contain:

```json
{
  "diagnostic_schema_version": "frozen-k4-diagnosis-completion-v1",
  "analysis_scope": "primary-component-0-ood-exceedances",
  "parent_provenance": {},
  "registry_provenance": {},
  "fixed_thresholds": {},
  "component_zero_ood": {},
  "full_sample_empirical": {},
  "offset_consistency": [],
  "fixed_sample_receipts": [],
  "diagnostic_only": true,
  "primary_replacement_allowed": false
}
```

Require Markdown to state the Component 0 top five, all family ratios, all three flags, the separately named fitted-parameter and full-sample empirical maxima, and 3-day/7-day match counts for drift component, OOD component, ordered top five, and top-five set. Require wording `universal`, `mixed`, or `subset-only` from exact match counts and forbid any gate pass/fail verdict.

Assert the child manifest includes exactly the six artifact hashes and byte counts, excludes `manifest.json` from both maps, and reproduces every artifact hash/byte count on a second clean run.

Call the production publisher through injected source/replay/decomposition/completion fixtures. Require atomic cleanup on rename failure, byte-identical acceptance when the deterministic child directory already exists, rejection when an existing child differs, and exact parent snapshots after every success and failure seam.

- [ ] **Step 4: Run renderer tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_complete_frozen_three_day_k4_diagnosis.py -q -k "csv or json or markdown or manifest or deterministic"
```

Expected: failures show missing renderers or incomplete output schemas.

- [ ] **Step 5: Implement deterministic row renderers**

Add `_ood_feature_rows`, `_ood_family_rows`, `_empirical_diagnostic_rows`, and `_empirical_feature_rows`. Sort by semantic keys and use the existing canonical float representation. Render null numeric values as empty cells and booleans as lowercase `true`/`false`. Do not compact feature mappings into a pipe-delimited cell when one feature per row is available.

- [ ] **Step 6: Implement JSON and Markdown renderers**

Render a complete structured payload from immutable completion contracts, including all 1,641 ordered fixed sample receipts so a separate auditor can reconstruct offset selection and assignment accounting without fitting or matching. In Markdown, report aggregate values without rounding away distinctions needed to reproduce flags, and always distinguish:

- `fitted_parameter_centroid_distance` from the parent diagnosis;
- `full_sample_empirical_centroid_distance` from this completion;
- `offset_empirical_centroid_distance` for each subsample.

Calculate match counts from the ten stored `OffsetConclusion` rows rather than from prose-specific recomputation.

Implement `publish_frozen_k4_diagnosis_completion` with keyword arguments `parent_run`, `model_attempt`, `raw_kline_root`, `output_root`, plus injectable `source_loader`, `replay_runner`, `decomposition_runner`, `completion_runner`, and `replace_directory`. Follow the Task 5 orchestration sequence, render the six artifacts, create `FrozenK4DiagnosisCompletionManifest` with both hash and byte maps, publish atomically under the child run ID, and compare the full parent snapshot immediately before returning. `main()` prints the final child directory and returns zero only after all checks pass.

- [ ] **Step 7: Run the full renderer tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_complete_frozen_three_day_k4_diagnosis.py -q
```

Expected: all renderer/publication tests pass and repeat runs are byte-identical.

- [ ] **Step 8: Commit the auditable outputs**

```powershell
git add scripts/complete_frozen_three_day_k4_diagnosis.py tests/test_complete_frozen_three_day_k4_diagnosis.py
git commit -m "feat: render frozen K4 completion evidence"
```

## Task 7: Prove isolation, reconciliation, and regression safety

**Files:**
- Modify: `tests/application/services/test_frozen_k4_diagnosis_completion.py`
- Modify: `tests/test_complete_frozen_three_day_k4_diagnosis.py`

- [ ] **Step 1: Add forbidden-operation isolation tests**

Monkeypatch these operations to raise while calling only `complete_frozen_k4_diagnosis` with an already reproduced replay:

```python
monkeypatch.setattr("sklearn.mixture.GaussianMixture.fit", forbidden)
monkeypatch.setattr("sklearn.preprocessing.RobustScaler.fit", forbidden)
monkeypatch.setattr(
    "src.application.services.frozen_k4_failure_replay._match_projected_centroids",
    forbidden,
)
monkeypatch.setattr(
    "src.infrastructure.regime.three_day_k4_model_artifact.write_three_day_k4_model_artifact",
    forbidden,
    raising=False,
)
monkeypatch.setattr(
    "src.application.usecases.regime.select_regime_model_usecase.select_model",
    forbidden,
)
monkeypatch.setattr(
    "src.application.usecases.regime.select_regime_model_usecase._apply_gates",
    forbidden,
)
monkeypatch.setattr(
    "src.infrastructure.regime.three_day_k4_model_artifact.ThreeDayK4ModelArtifact.from_fit",
    forbidden,
)
monkeypatch.setattr(
    "src.application.usecases.regime.build_strategy_mapping_usecase.BuildStrategyMappingUseCase.execute",
    forbidden,
)
monkeypatch.setattr(
    "src.application.usecases.regime.build_daily_strategy_mapping_usecase.BuildDailyStrategyMappingUseCase.execute",
    forbidden,
)
```

Also guard Mapping, Evidence, strategy, candidate, and untouched-Test paths from reads, and guard all files under the parent run from write/open modes containing `w`, `a`, `x`, or `+`.

- [ ] **Step 2: Add arithmetic reconciliation tests**

Independently recompute and assert:

- 24 Component 0 OOD rows and denominator 409;
- each OOD feature total and every family total;
- total feature contributions equal total sample Mahalanobis distances;
- volatility includes exactly the four strict registry members;
- every empirical feature sum equals squared centroid distance;
- each spacing's offset indices partition all 1,641 indices;
- each offset's component OOD numerators/denominators reconcile to selected existing OOD rows;
- all report flags equal the fixed inclusive thresholds.

- [ ] **Step 3: Add parent-directory and old-suite regression tests**

Hash every byte in the committed parent run before and after a completion publication and require equality. Then run the old diagnosis tests unchanged to prove the original publisher and manifest contract retain their behavior.

- [ ] **Step 4: Run the focused completion and old diagnosis suites**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_frozen_k4_diagnosis_completion.py tests/application/services/test_frozen_k4_diagnosis_completion.py tests/test_complete_frozen_three_day_k4_diagnosis.py -q
.\.venv\Scripts\python.exe -m pytest tests/domain/regime/test_frozen_k4_failure_diagnostics.py tests/application/services/test_frozen_k4_failure_decomposition.py tests/test_diagnose_frozen_three_day_k4_failure.py -q
```

Expected: both commands pass; the second command requires no edits to old production or test files.

- [ ] **Step 5: Commit the isolation proof**

```powershell
git add tests/application/services/test_frozen_k4_diagnosis_completion.py tests/test_complete_frozen_three_day_k4_diagnosis.py
git commit -m "test: prove frozen K4 completion isolation"
```

## Task 8: Build an independent completion auditor

**Files:**
- Create: `scripts/audit_frozen_k4_diagnosis_completion.py`
- Create: `tests/test_audit_frozen_k4_diagnosis_completion.py`

- [ ] **Step 1: Write RED tests for independent hash and parent verification**

Build a valid temporary parent/child pair from static bytes. Call the auditor as a library and require it to verify the child manifest schema, exact artifact membership, SHA-256, byte counts, run-ID identity payload, parent run ID, exact parent manifest-byte hash, every parent artifact hash, and parent/child path separation. Parametrize one-byte mutations in each artifact and require a closed audit failure naming the affected invariant.

- [ ] **Step 2: Write RED tests for independent analytical recomputation**

Use a small but complete fixture containing raw vectors, primary fit, all fixed sample receipts, feature/family CSVs, empirical diagnostic rows, feature contribution rows, JSON summaries, and Markdown. Require the auditor to recompute without importing `src.application.services.frozen_k4_diagnosis_completion` or `scripts.complete_frozen_three_day_k4_diagnosis`:

- primary clipping/scaling from the frozen primary fit;
- Component 0 per-sample Mahalanobis contributions and 24/409 population;
- feature sum/ratio/mean/median/top-1/top-5 and global rank;
- strict registry family totals and all three inclusive-threshold flags;
- full-sample and offset empirical centroids from sample receipts;
- all 3-day/7-day offset partitions, OOD rows, maxima, ties, and four consistency flags;
- JSON and Markdown claims from the recomputed values.

Monkeypatch both forbidden modules in `sys.modules` with objects that raise on attribute access to prove the audit does not share calculation/rendering helpers.

- [ ] **Step 3: Run auditor tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_audit_frozen_k4_diagnosis_completion.py -q
```

Expected: collection fails because the independent audit script does not exist.

- [ ] **Step 4: Implement strict audit inputs and receipts**

Implement `audit_frozen_k4_diagnosis_completion(*, parent_run, completion_run, model_attempt, raw_kline_root) -> Mapping[str, object]`. Load the frozen source only through `load_frozen_k4_diagnostic_source` to obtain verified vectors and the frozen primary fit; do not call replay, decomposition, completion, renderer, fitter, scaler `.fit`, or matcher code. Parse CSV with `csv.DictReader`, JSON with non-finite constants rejected, and Markdown as immutable UTF-8 text.

Return a canonical receipt with parent/child IDs, checked file count, Component 0 numerator/denominator, registry hash, ten checked offsets, three flags, and `status="verified"`. The CLI exits nonzero on any mismatch and prints the canonical receipt on success.

- [ ] **Step 5: Implement independent formulas and claim reconciliation**

Reimplement the primary transform and diagonal distance directly from frozen arrays. Join ordered source anchors to `fixed_sample_receipts` one-to-one, validate both existing assignment kinds and OOD strict `>`, then recompute all aggregates and empirical scopes using the fixed selection formula. Compare values with `math.isclose(rel_tol=1e-12, abs_tol=1e-12)` and require exact identities, ranks, booleans, tie outcomes, and Markdown sentences.

- [ ] **Step 6: Run auditor tests and verify GREEN**

Run the Task 8 pytest command. Expected: all valid, mutation, independence, and analytical reconciliation tests pass.

- [ ] **Step 7: Commit the independent audit**

```powershell
git add scripts/audit_frozen_k4_diagnosis_completion.py tests/test_audit_frozen_k4_diagnosis_completion.py
git commit -m "test: audit frozen K4 completion evidence"
```

## Task 9: Execute twice, independently verify, and publish the completion evidence

**Files:**
- Create: `docs/backtests/frozen_k4_diagnosis_completion/<run_id>/frozen_k4_diagnosis_completion.json`
- Create: `docs/backtests/frozen_k4_diagnosis_completion/<run_id>/frozen_k4_component_0_ood_feature_summary.csv`
- Create: `docs/backtests/frozen_k4_diagnosis_completion/<run_id>/frozen_k4_component_0_ood_family_summary.csv`
- Create: `docs/backtests/frozen_k4_diagnosis_completion/<run_id>/frozen_k4_offset_empirical_diagnostics.csv`
- Create: `docs/backtests/frozen_k4_diagnosis_completion/<run_id>/frozen_k4_offset_feature_contributions.csv`
- Create: `docs/backtests/frozen_k4_diagnosis_completion/<run_id>/frozen_k4_diagnosis_completion.md`
- Create: `docs/backtests/frozen_k4_diagnosis_completion/<run_id>/manifest.json`

- [ ] **Step 1: Record and verify the immutable parent snapshot**

Compute SHA-256 and byte length for every file in the parent directory, including its manifest, and retain the sorted relative-path map outside both output roots. Require parent run ID `d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af`, exact published manifest SHA-256 `5b65aed30c9a8d7c67cf383df9667d599c9fb2938b95b59813be5235077a0824`, and valid manifest file hashes before proceeding.

- [ ] **Step 2: Execute two clean single-threaded completion runs**

Run the command twice with identical inputs but separate temporary output roots:

```powershell
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
.\.venv\Scripts\python.exe scripts/complete_frozen_three_day_k4_diagnosis.py --parent-run docs/backtests/frozen_k4_failure_diagnosis/d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af --model-attempt docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json --raw-kline-root .research-data/binance-usdm/raw/klines --output-root .agents/backtest-cache/frozen-k4-completion-a
.\.venv\Scripts\python.exe scripts/complete_frozen_three_day_k4_diagnosis.py --parent-run docs/backtests/frozen_k4_failure_diagnosis/d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af --model-attempt docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json --raw-kline-root .research-data/binance-usdm/raw/klines --output-root .agents/backtest-cache/frozen-k4-completion-b
```

Expected: both commands print the same child run ID; the two seven-file directory trees are byte-identical; the parent snapshot is unchanged.

- [ ] **Step 3: Independently recompute the reported conclusions from outputs**

Run the auditor separately against both clean runs:

```powershell
$runsA = @(Get-ChildItem .agents/backtest-cache/frozen-k4-completion-a -Directory)
$runsB = @(Get-ChildItem .agents/backtest-cache/frozen-k4-completion-b -Directory)
if ($runsA.Count -ne 1 -or $runsB.Count -ne 1) { throw "expected one deterministic run directory per clean output root" }
$runA = $runsA[0]
$runB = $runsB[0]
.\.venv\Scripts\python.exe scripts/audit_frozen_k4_diagnosis_completion.py --parent-run docs/backtests/frozen_k4_failure_diagnosis/d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af --completion-run $runA.FullName --model-attempt docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json --raw-kline-root .research-data/binance-usdm/raw/klines
.\.venv\Scripts\python.exe scripts/audit_frozen_k4_diagnosis_completion.py --parent-run docs/backtests/frozen_k4_failure_diagnosis/d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af --completion-run $runB.FullName --model-attempt docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json --raw-kline-root .research-data/binance-usdm/raw/klines
```

Expected: both receipts are identical and report `status=verified`, `component_0_ood=24/409`, and `checked_offsets=10`. Any mismatch blocks publication.

- [ ] **Step 4: Publish once to the canonical completion root**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/complete_frozen_three_day_k4_diagnosis.py --parent-run docs/backtests/frozen_k4_failure_diagnosis/d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af --model-attempt docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json --raw-kline-root .research-data/binance-usdm/raw/klines --output-root docs/backtests/frozen_k4_diagnosis_completion
```

Expected: the canonical directory matches both clean-run trees byte for byte and the original parent remains byte-identical.

Run the independent auditor once more against the canonical directory and require the same verified receipt as both clean runs.

- [ ] **Step 5: Run full repository verification**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
git status --short
```

Expected: the full suite passes, diff check is clean, and status contains only the intended completion code/tests/evidence before commit.

- [ ] **Step 6: Commit the completion evidence**

```powershell
git add -f docs/backtests/frozen_k4_diagnosis_completion
git commit -m "docs: publish frozen K4 diagnosis completion"
```

## Task 10: Final specification and quality review

**Files:**
- Review all files changed since `1515e65`.

- [ ] **Step 1: Review every design invariant against code and evidence**

Map each design requirement to a contract, focused test, and published field. Treat any parent mutation, empirical-to-fitted offset comparison, range/volume inclusion in volatility, threshold drift, offset fit/rematch, gate verdict, model artifact, or strategy access as a blocking defect.

- [ ] **Step 2: Review numerical and publication quality**

Check finite-value validation, inclusive threshold boundaries, empty component behavior, deterministic ties, registry-order stability, canonical hashing, tagged CSV null encoding, path containment, atomic publication, and repeat-run byte identity.

- [ ] **Step 3: Fix each finding with a failing regression first**

For every finding, add the narrowest failing test, run it to confirm RED, make the minimal correction, rerun it to GREEN, then rerun the focused commands and full suite from Tasks 7 through 9.

- [ ] **Step 4: Confirm the diagnosis boundary is complete**

Verify the new report answers the Component 0 OOD and every 3-day/7-day offset question, explicitly states that the frozen K4 cause diagnosis is complete, and does not start pseudo-OOS development or strategy mapping.
