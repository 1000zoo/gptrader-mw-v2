from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType, SimpleNamespace
import warnings

import pytest

from src.application.services.frozen_k4_failure_decomposition import (
    CauseClassification,
    FrozenK4Decomposition,
    OODComponentRow,
    OODSampleContributionRow,
)
from src.application.services.frozen_k4_diagnosis_completion import (
    ComponentZeroOODAnalysis,
    FixedSampleReceipt,
    FrozenK4DiagnosisCompletion,
    OffsetConclusion,
    OffsetOODRow,
    EmpiricalCentroidRow,
    EmpiricalFeatureContributionRow,
    EmpiricalScopeSummary,
    OODFamilySummaryRow,
    OODFeatureSummaryRow,
    _canonical_registry_payload,
    _canonical_registry_sha256,
    _meets_threshold,
    _global_offset_indices,
    _maximum_ood,
    build_full_sample_empirical_reference,
    complete_frozen_k4_diagnosis,
    summarize_component_zero_ood,
)
from src.application.services.frozen_k4_failure_replay import (
    FrozenK4HalfReplay,
    FrozenK4Replay,
)
from src.domain.regime import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)
from src.domain.regime.frozen_k4_failure_diagnostics import MatchedPair


REGISTRY = THREE_DAY_CHART_FEATURE_REGISTRY_V1
NAMES = tuple(spec.name for spec in REGISTRY)
FINGERPRINT = "a" * 24
SCOPE = "primary-component-0-ood-exceedances"


def _decomposition(
    contributions: tuple[dict[str, float], ...] | None = None,
    *,
    component_row: OODComponentRow | None = None,
    sample_fingerprint: str = FINGERPRINT,
    threshold: float = 0.5,
) -> FrozenK4Decomposition:
    if contributions is None:
        contributions = tuple(
            {name: (1.0 if name == "rv_4h" else 0.0) for name in NAMES}
            for _ in range(24)
        )
    samples = tuple(
        OODSampleContributionRow(
            anchor_at=f"2021-01-{index + 1:02d}T00:00:00Z",
            component_index=0,
            component_fingerprint=sample_fingerprint,
            squared_mahalanobis=sum(row.values()),
            threshold=threshold,
            feature_contributions=row,
        )
        for index, row in enumerate(contributions)
    )
    return FrozenK4Decomposition(
        cluster_summaries=(),
        cause_classification=CauseClassification((), {}),
        feature_contributions=(),
        top_drift_features={},
        location_distances=(),
        clipped_samples=(),
        exclusion_sensitivity=(),
        pooled_mahalanobis=(),
        component_distances=(),
        ood_by_component=(
            component_row or OODComponentRow(0, FINGERPRINT, 409, 24, 24 / 409),
        ),
        ood_samples=samples,
        offset_subsamples=(),
    )


def _rows(*pairs: tuple[str, float]) -> tuple[dict[str, float], ...]:
    row = dict.fromkeys(NAMES, 0.0)
    row.update(pairs)
    return tuple(dict(row) for _ in range(24))


def test_component_zero_summary_aggregates_feature_and_family_statistics() -> None:
    rows = []
    for index in range(24):
        row = dict.fromkeys(NAMES, 0.0)
        row["return_4h"] = 3.0 if index < 12 else 1.0
        row["rv_4h"] = 2.0
        row["rv_1d"] = 1.0
        row["range_ratio_3d"] = 1.0
        row["volume_cv_3d"] = 1.0
        rows.append(row)

    result = summarize_component_zero_ood(_decomposition(tuple(rows)), retained_feature_names=NAMES)

    assert isinstance(result, ComponentZeroOODAnalysis)
    assert result.analysis_scope == SCOPE
    assert result.primary_component_index == 0
    assert result.primary_component_fingerprint == FINGERPRINT
    assert (result.assigned_sample_count, result.ood_sample_count) == (409, 24)
    assert result.registry_schema_version == THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
    assert len(result.registry_sha256) == 64
    by_name = {row.feature_name: row for row in result.feature_rows}
    assert by_name["return_4h"].contribution_sum == 48.0
    assert by_name["return_4h"].contribution_mean == 2.0
    assert by_name["return_4h"].contribution_median == 2.0
    assert by_name["return_4h"].top1_count == 12
    assert by_name["return_4h"].top1_ratio == 0.5
    assert by_name["rv_4h"].top1_count == 12  # ties use registry order
    assert by_name["return_4h"].top5_count == 24
    assert sum(row.contribution_sum for row in result.feature_rows) == 168.0
    assert sum(row.contribution_ratio for row in result.feature_rows) == pytest.approx(1.0)
    assert result.top_five_features == (
        "return_4h", "rv_4h", "rv_1d", "range_ratio_3d", "volume_cv_3d"
    )
    assert [row.rank for row in result.feature_rows[:5]] == [1, 2, 3, 4, 5]

    families = {row.family_name: row for row in result.family_rows}
    assert tuple(families) == tuple(dict.fromkeys(spec.family for spec in REGISTRY))
    assert families["volatility"].family_feature_names == (
        "rv_4h", "rv_1d", "rv_3d", "rv_ratio_1d_3d"
    )
    assert "range_ratio_3d" not in families["volatility"].family_feature_names
    assert "volume_cv_3d" not in families["volatility"].family_feature_names
    assert families["volatility"].contribution_sum == 72.0
    assert families["volatility"].contribution_ratio == pytest.approx(72 / 168)
    assert all(row.concentration_threshold == 0.70 for row in result.family_rows)
    assert families["volatility"].concentration_rule_applies is True
    assert families["range"].concentration_rule_applies is False
    assert families["range"].concentration_result is False
    assert result.single_feature_concentration is False
    assert result.volatility_family_concentration is False
    assert result.recurrent_feature_dominance is True
    assert result.diagnostic_only is True


@pytest.mark.parametrize(
    ("share", "expected"),
    ((0.49, False), (0.50, True), (0.51, True)),
)
def test_single_feature_concentration_uses_inclusive_half_boundary(share: float, expected: bool) -> None:
    result = summarize_component_zero_ood(
        _decomposition(
            _rows(
                ("return_4h", share),
                ("rv_4h", (1 - share) / 2),
                ("range_ratio_3d", (1 - share) / 2),
            )
        ),
        retained_feature_names=NAMES,
    )
    assert result.single_feature_concentration is expected


@pytest.mark.parametrize(
    ("volatility_units", "range_units", "expected"),
    ((69.0, 31.0, False), (7.0, 3.0, True), (71.0, 29.0, True)),
)
def test_volatility_family_concentration_uses_registry_and_inclusive_boundary(
    volatility_units: float, range_units: float, expected: bool
) -> None:
    result = summarize_component_zero_ood(
        _decomposition(
            _rows(("rv_4h", volatility_units), ("range_ratio_3d", range_units)),
            threshold=0.5,
        ),
        retained_feature_names=NAMES,
    )
    assert result.volatility_family_concentration is expected


@pytest.mark.parametrize(("top1_count", "expected"), ((11, False), (12, True), (13, True)))
def test_recurrent_dominance_uses_inclusive_half_boundary(top1_count: int, expected: bool) -> None:
    rows = []
    for index in range(24):
        row = dict.fromkeys(NAMES, 0.0)
        winner = "return_4h" if index < top1_count else f"return_{['12h', '1d', '2d', '3d'][(index-top1_count) % 4]}"
        row[winner] = 2.0
        row["rv_4h"] = 1.0
        rows.append(row)
    result = summarize_component_zero_ood(_decomposition(tuple(rows)), retained_feature_names=NAMES)
    assert result.recurrent_feature_dominance is expected


@pytest.mark.parametrize(
    "decomposition",
    [
        _decomposition(_rows(("rv_4h", 1.0))[:23]),
        _decomposition(_rows(("rv_4h", 1.0)) + _rows(("rv_4h", 1.0))[:1]),
        _decomposition(component_row=OODComponentRow(0, FINGERPRINT, 408, 24, 24 / 408)),
        _decomposition(component_row=OODComponentRow(0, FINGERPRINT, 409, 23, 23 / 409)),
        _decomposition(component_row=OODComponentRow(0, FINGERPRINT, 409, 24, 0.1)),
        _decomposition(sample_fingerprint="b" * 24),
        _decomposition(threshold=1.0),
    ],
)
def test_rejects_noncanonical_component_zero_population(decomposition: FrozenK4Decomposition) -> None:
    with pytest.raises(ValueError):
        summarize_component_zero_ood(decomposition, retained_feature_names=NAMES)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0])
def test_rejects_invalid_contributions_and_distance_reconciliation(bad: float) -> None:
    rows = list(_rows(("rv_4h", 1.0)))
    rows[0]["rv_4h"] = bad
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(tuple(rows)), retained_feature_names=NAMES)

    valid = _decomposition()
    bad_sample = replace(valid.ood_samples[0], squared_mahalanobis=2.0)
    with pytest.raises(ValueError):
        summarize_component_zero_ood(replace(valid, ood_samples=(bad_sample,) + valid.ood_samples[1:]), retained_feature_names=NAMES)


@pytest.mark.parametrize(
    "names",
    [NAMES[:-1], NAMES + (NAMES[0],), tuple(reversed(NAMES)), ("not_registered",)],
)
def test_rejects_missing_duplicate_unknown_or_nonregistry_order_retained_names(names: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(), retained_feature_names=names)


def test_rejects_missing_or_extra_sample_contribution_keys_and_wrong_registry_contract() -> None:
    missing = list(_rows(("rv_4h", 1.0)))
    del missing[0][NAMES[-1]]
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(tuple(missing)), retained_feature_names=NAMES)
    extra = list(_rows(("rv_4h", 1.0)))
    extra[0]["extra"] = 0.0
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(tuple(extra)), retained_feature_names=NAMES)
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(), retained_feature_names=NAMES, registry=tuple(reversed(REGISTRY)))
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(), retained_feature_names=NAMES, registry_schema_version="wrong")
    with pytest.raises(ValueError):
        summarize_component_zero_ood(object(), retained_feature_names=NAMES)


def test_registry_hash_is_canonical_stable_and_sensitive_only_to_admitted_payload() -> None:
    first = _canonical_registry_sha256(NAMES, REGISTRY, THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)
    second = _canonical_registry_sha256(NAMES, REGISTRY, THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)
    assert first == "cf0b92c6d01a04e79a4b0510ee123ab42401576fe00cc6e6e83acec1e313b4ba"
    assert first == second
    assert first != _canonical_registry_sha256(NAMES, tuple(reversed(REGISTRY)), THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)
    mutations = (
        replace(REGISTRY[0], name=REGISTRY[0].name + "_changed"),
        replace(REGISTRY[0], family=REGISTRY[0].family + "_changed"),
        replace(REGISTRY[0], aggregation_minutes=REGISTRY[0].aggregation_minutes + 1),
        replace(REGISTRY[0], lookback_minutes=REGISTRY[0].lookback_minutes + 1),
        replace(REGISTRY[0], formula=REGISTRY[0].formula + " changed"),
    )
    assert all(
        first
        != _canonical_registry_sha256(NAMES, (changed,) + REGISTRY[1:], THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)
        for changed in mutations
    )
    policy_changed = replace(
        REGISTRY[0],
        null_policy="changed",
        clipping_policy="changed",
        scale_invariant=not REGISTRY[0].scale_invariant,
    )
    assert first == _canonical_registry_sha256(
        NAMES, (policy_changed,) + REGISTRY[1:], THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
    )
    payload = _canonical_registry_payload(NAMES, REGISTRY, THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)
    assert tuple(payload) == ("registry_schema_version", "retained_feature_names", "registry")
    assert set(payload["registry"][0]) == {
        "name", "family", "aggregation_minutes", "lookback_minutes", "formula"
    }


@pytest.mark.parametrize(
    ("value", "threshold", "expected"),
    (
        (0.5 - 5e-13, 0.5, False),
        (0.5, 0.5, True),
        (0.7 - 5e-13, 0.7, False),
        (0.7, 0.7, True),
    ),
)
def test_concentration_thresholds_are_literal_without_tolerance(
    value: float, threshold: float, expected: bool
) -> None:
    assert _meets_threshold(value, threshold) is expected


def test_result_and_nested_contracts_are_frozen_and_validate_invariants() -> None:
    result = summarize_component_zero_ood(_decomposition(), retained_feature_names=NAMES)
    assert isinstance(result.feature_rows, tuple)
    assert isinstance(result.family_rows, tuple)
    assert isinstance(result.feature_rows[0], OODFeatureSummaryRow)
    assert isinstance(result.family_rows[0], OODFamilySummaryRow)
    with pytest.raises(FrozenInstanceError):
        result.ood_sample_count = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.feature_rows[0].rank = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.family_rows[0].family_name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.feature_rows[0] = result.feature_rows[1]  # type: ignore[index]
    with pytest.raises(TypeError):
        result.family_rows[0] = result.family_rows[1]  # type: ignore[index]
    with pytest.raises(ValueError):
        replace(result.feature_rows[0], contribution_ratio=2.0)
    with pytest.raises(ValueError):
        replace(result.feature_rows[0], contribution_mean=2.0)
    with pytest.raises(ValueError):
        replace(result.family_rows[0], family_feature_names=("x", "x"))
    with pytest.raises(ValueError):
        replace(result, analysis_scope="wrong")
    with pytest.raises(ValueError):
        replace(result, top_five_features=("missing",))
    duplicated_family = replace(
        result.family_rows[1],
        family_feature_names=result.family_rows[0].family_feature_names,
    )
    with pytest.raises(ValueError):
        replace(result, family_rows=(result.family_rows[0], duplicated_family) + result.family_rows[2:])


def test_analysis_rejects_forged_feature_order_and_impossible_frequency_totals() -> None:
    result = summarize_component_zero_ood(_decomposition(), retained_feature_names=NAMES)
    first, second = result.feature_rows[:2]
    reordered = (
        replace(second, rank=1),
        replace(first, rank=2),
    ) + result.feature_rows[2:]
    with pytest.raises(ValueError, match="order"):
        replace(result, feature_rows=reordered, top_five_features=tuple(row.feature_name for row in reordered[:5]))

    zero_top1 = tuple(
        replace(row, top1_count=0, top1_ratio=0.0) for row in result.feature_rows
    )
    with pytest.raises(ValueError, match="top-1"):
        replace(result, feature_rows=zero_top1)
    excess_top1 = (
        replace(result.feature_rows[0], top1_count=24, top1_ratio=1.0),
        replace(result.feature_rows[1], top1_count=24, top1_ratio=1.0),
    ) + result.feature_rows[2:]
    with pytest.raises(ValueError, match="top-1"):
        replace(result, feature_rows=excess_top1)
    excess_top5 = tuple(
        replace(row, top5_count=24, top5_ratio=1.0) for row in result.feature_rows
    )
    with pytest.raises(ValueError, match="top-5"):
        replace(result, feature_rows=excess_top5)

    tied = summarize_component_zero_ood(
        _decomposition(_rows(("return_4h", 1.0), ("rv_4h", 1.0))),
        retained_feature_names=NAMES,
    )
    assert tied.feature_rows[:2][0].feature_name == "return_4h"
    tied_reordered = (
        replace(tied.feature_rows[1], rank=1),
        replace(tied.feature_rows[0], rank=2),
    ) + tied.feature_rows[2:]
    with pytest.raises(ValueError, match="canonical registry tie order"):
        replace(
            tied,
            feature_rows=tied_reordered,
            top_five_features=tuple(row.feature_name for row in tied_reordered[:5]),
        )


def test_analysis_rejects_forged_registry_hash_feature_and_family_provenance() -> None:
    result = summarize_component_zero_ood(_decomposition(), retained_feature_names=NAMES)
    fake_hash = "f" * 64
    forged_features = tuple(replace(row, registry_sha256=fake_hash) for row in result.feature_rows)
    forged_families = tuple(replace(row, registry_sha256=fake_hash) for row in result.family_rows)
    with pytest.raises(ValueError, match="canonical registry hash"):
        replace(
            result,
            registry_sha256=fake_hash,
            feature_rows=forged_features,
            family_rows=forged_families,
        )

    bad_family_feature = replace(result.feature_rows[0], registry_family="forged")
    with pytest.raises(ValueError, match="registry family"):
        replace(result, feature_rows=(bad_family_feature,) + result.feature_rows[1:])

    unknown = replace(result.feature_rows[0], feature_name="unknown_feature")
    with pytest.raises(ValueError, match="canonical registry"):
        replace(
            result,
            feature_rows=(unknown,) + result.feature_rows[1:],
            top_five_features=("unknown_feature",) + result.top_five_features[1:],
        )

    wrong_family_order = (result.family_rows[1], result.family_rows[0]) + result.family_rows[2:]
    with pytest.raises(ValueError, match="family order"):
        replace(result, family_rows=wrong_family_order)

    wrong_members = replace(
        result.family_rows[0], family_feature_names=result.family_rows[0].family_feature_names[:-1]
    )
    with pytest.raises(ValueError, match="family"):
        replace(result, family_rows=(wrong_members,) + result.family_rows[1:])


EMPIRICAL_NAMES = NAMES[:6]


def _empirical_vector(index: int, scaled: tuple[float, ...]) -> SimpleNamespace:
    anchor = datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    medians = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    scales = (1.0, 2.0, 1.0, 2.0, 1.0, 2.0)
    values = MappingProxyType(
        {
            name: median_value + scale * coordinate
            for name, median_value, scale, coordinate in zip(
                EMPIRICAL_NAMES, medians, scales, scaled
            )
        }
    )
    return SimpleNamespace(anchor_at=anchor, values=values)


def _empirical_fixture() -> tuple[FrozenK4Replay, SimpleNamespace, tuple[SimpleNamespace, ...]]:
    primary_fit = SimpleNamespace(
        feature_names=EMPIRICAL_NAMES,
        lower_bounds=(0.0,) * 6,
        upper_bounds=(5.0, 10.0, 7.0, 12.0, 9.0, 14.0),
        medians=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
        scales=(1.0, 2.0, 1.0, 2.0, 1.0, 2.0),
        fingerprints=("1" * 24, "2" * 24),
        means=((0.0,) * 6, (1.0,) * 6),
    )

    def half(label: str, count: int, assignments: tuple[int, ...], prefix: str) -> FrozenK4HalfReplay:
        half_fit = SimpleNamespace(
            feature_names=EMPIRICAL_NAMES,
            fingerprints=(prefix * 24, chr(ord(prefix) + 1) * 24),
            means=((9.0,) * 6, (8.0,) * 6),
            diagnostic_only=True,
            primary_replacement_allowed=False,
        )
        primary_indices = (1, 0) if label == "A" else (0, 1)
        pairs = tuple(
            MatchedPair(
                half_label=label,
                primary_component_fingerprint=primary_fit.fingerprints[primary_index],
                half_component_fingerprint=half_fit.fingerprints[half_index],
                primary_component_index=primary_index,
                half_component_index=half_index,
                matching_cost=float(half_index),
                euclidean_distance=float(half_index),
            )
            for half_index, primary_index in enumerate(primary_indices)
        )
        return FrozenK4HalfReplay(
            receipt=SimpleNamespace(
                half_label=label,
                anchor_count=count,
                anchor_range=(
                    "2021-01-01T00:00:00Z" if label == "A" else "2021-01-05T00:00:00Z",
                    "2021-01-05T00:00:00Z" if label == "A" else "2021-01-08T00:00:00Z",
                ),
                diagnostic_only=True,
                primary_replacement_allowed=False,
            ),
            fit=half_fit,
            assignments=assignments,
            posterior_probabilities=(),
            projected_centroids=(),
            projected_covariances=(),
            precisions=(),
            precisions_cholesky=(),
            cost_matrix=(),
            hungarian_assignment=(),
            matched_pairs=pairs,
            pair_euclidean_distances=(),
            component_weights=(),
        )

    halves = (
        half("A", 4, (0, 1, 1, 1), "3"),
        half("B", 3, (0, 0, 0), "5"),
    )
    vectors = (
        _empirical_vector(0, (3.0, 3.0, 0.0, 0.0, 0.0, 0.0)),
        _empirical_vector(1, (0.0,) * 6),
        _empirical_vector(2, (0.0,) * 6),
        _empirical_vector(3, (0.0,) * 6),
        _empirical_vector(4, (2.0,) * 6),
        _empirical_vector(5, (2.0,) * 6),
        _empirical_vector(6, (20.0,) * 6),  # proves frozen upper clipping is used
    )
    replay = FrozenK4Replay(
        input_identity=SimpleNamespace(),
        dependency_metadata={},
        status=SimpleNamespace(status="reproduced"),
        half_replays=halves,
        # Deliberately disagrees with both half assignment arrays.
        primary_assignments=(0, 0, 0, 0, 1, 1, 1),
        primary_ood_rows=tuple(
            SimpleNamespace(
                anchor_at=row.anchor_at.isoformat().replace("+00:00", "Z"),
                assigned_component_index=component,
                assigned_component_fingerprint=primary_fit.fingerprints[component],
                squared_mahalanobis=float(index % 4),
                threshold=1.5,
                exceeds=(index % 4) > 1.5,
                comparison_operator=">",
            )
            for index, (row, component) in enumerate(
                zip(vectors, (0, 0, 0, 0, 1, 1, 1))
            )
        ),
    )
    return replay, primary_fit, vectors


def _completion_fixture() -> tuple[
    FrozenK4Replay, SimpleNamespace, tuple[SimpleNamespace, ...], FrozenK4Decomposition
]:
    _, base_fit, _ = _empirical_fixture()
    primary_fit = SimpleNamespace(
        **(
            vars(base_fit)
            | {
                "fingerprints": tuple(str(index) * 24 for index in range(1, 5)),
                "means": tuple((float(index),) * 6 for index in range(4)),
            }
        )
    )
    vectors = tuple(_empirical_vector(index, (0.0,) * 6) for index in range(1641))
    primary_assignments = (0,) * 409 + (1,) * 410 + (2,) * 411 + (3,) * 411

    def half(label: str, start: int, count: int, prefix: str) -> FrozenK4HalfReplay:
        half_fit = SimpleNamespace(
            feature_names=EMPIRICAL_NAMES,
            fingerprints=tuple(chr(ord(prefix) + index) * 24 for index in range(4)),
            means=tuple((0.0,) * 6 for _ in range(4)),
            diagnostic_only=True,
            primary_replacement_allowed=False,
        )
        pairs = tuple(
            MatchedPair(
                half_label=label,
                primary_component_fingerprint=primary_fit.fingerprints[index],
                half_component_fingerprint=half_fit.fingerprints[index],
                primary_component_index=index,
                half_component_index=index,
                matching_cost=0.0,
                euclidean_distance=0.0,
            )
            for index in range(4)
        )
        end = start + count
        return FrozenK4HalfReplay(
            receipt=SimpleNamespace(
                half_label=label,
                anchor_count=count,
                anchor_range=(
                    vectors[start].anchor_at.isoformat().replace("+00:00", "Z"),
                    (vectors[end - 1].anchor_at + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                ),
                diagnostic_only=True,
                primary_replacement_allowed=False,
            ),
            fit=half_fit,
            assignments=primary_assignments[start:end],
            posterior_probabilities=(),
            projected_centroids=(),
            projected_covariances=(),
            precisions=(),
            precisions_cholesky=(),
            cost_matrix=(),
            hungarian_assignment=(),
            matched_pairs=pairs,
            pair_euclidean_distances=(),
            component_weights=(),
        )

    replay = FrozenK4Replay(
        input_identity=SimpleNamespace(),
        dependency_metadata={},
        status=SimpleNamespace(status="reproduced"),
        half_replays=(half("A", 0, 820, "5"), half("B", 820, 821, "a")),
        primary_assignments=primary_assignments,
        primary_ood_rows=tuple(
            SimpleNamespace(
                anchor_at=vector.anchor_at.isoformat().replace("+00:00", "Z"),
                assigned_component_index=component,
                assigned_component_fingerprint=primary_fit.fingerprints[component],
                squared_mahalanobis=1.0 if index < 24 else 0.0,
                threshold=0.5,
                exceeds=index < 24,
                comparison_operator=">",
            )
            for index, (vector, component) in enumerate(zip(vectors, primary_assignments))
        ),
    )
    contributions = tuple(
        {name: (1.0 if name == "rv_4h" else 0.0) for name in EMPIRICAL_NAMES}
        for _ in range(24)
    )
    decomposition = _decomposition(
        contributions,
        component_row=OODComponentRow(0, "1" * 24, 409, 24, 24 / 409),
        sample_fingerprint="1" * 24,
    )
    return replay, primary_fit, vectors, decomposition


def test_global_offset_selection_partitions_positions_without_restarting_at_half_boundary() -> None:
    for spacing in (3, 7):
        groups = tuple(_global_offset_indices(23, spacing, offset) for offset in range(spacing))
        assert sorted(index for group in groups for index in group) == list(range(23))
        assert sum(map(len, groups)) == len(set(index for group in groups for index in group))
        assert 4 in groups[4 % spacing]
        assert 4 not in groups[0]  # the B boundary is not a new local origin


def test_complete_diagnosis_builds_fixed_receipts_and_all_global_offsets() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    result = complete_frozen_k4_diagnosis(replay, primary_fit, vectors, decomposition)

    assert isinstance(result, FrozenK4DiagnosisCompletion)
    assert result.completion_scope == "frozen-k4-diagnosis-completion"
    assert len(result.sample_receipts) == 1641
    assert all(isinstance(row, FixedSampleReceipt) for row in result.sample_receipts)
    assert tuple(row.global_index for row in result.sample_receipts) == tuple(range(1641))
    assert len(result.offset_empirical) == 10
    assert len(result.offset_ood) == 40
    assert len(result.offset_conclusions) == 10
    assert {(row.spacing_days, row.offset) for row in result.offset_conclusions} == {
        *((3, offset) for offset in range(3)),
        *((7, offset) for offset in range(7)),
    }
    assert sum(row.denominator for row in result.full_sample_ood) == 1641
    assert len(result.full_sample_ood) == 4
    for spacing in (3, 7):
        assert sum(
            scope.selected_sample_count
            for scope in result.offset_empirical
            if scope.spacing_days == spacing
        ) == 1641
    assert all(row.distance_source == "existing_primary_ood_row" for row in result.offset_ood)
    assert all(scope.sample_scope == "offset_subsample" for scope in result.offset_empirical)
    assert result.diagnostic_only is True


def test_offset_ood_maximum_uses_rate_then_counts_and_empty_components_are_null() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    result = complete_frozen_k4_diagnosis(replay, primary_fit, vectors, decomposition)
    empty = OffsetOODRow(
        "offset_subsample", 7, 0, 2, "f" * 24, 0, 0, None
    )
    assert empty.denominator == 0 and empty.numerator == 0 and empty.rate is None
    conclusion = next(row for row in result.offset_conclusions if (row.spacing_days, row.offset) == (3, 1))
    assert isinstance(conclusion, OffsetConclusion)
    assert conclusion.maximum_ood_primary_component_index == 0
    with pytest.raises(ValueError, match="rate"):
        OffsetOODRow(
            "offset_subsample",
            3,
            0,
            0,
            "1" * 24,
            1,
            3,
            math.nextafter(1 / 3, 1.0),
        )


def test_ood_maximum_ties_use_literal_rate_numerator_denominator_then_index() -> None:
    def row(component: int, numerator: int, denominator: int) -> OffsetOODRow:
        return OffsetOODRow(
            "full_sample",
            None,
            None,
            component,
            str(component + 1) * 24,
            numerator,
            denominator,
            numerator / denominator,
        )

    assert _maximum_ood((row(0, 4, 10), row(1, 1, 2))).primary_component_index == 1
    assert _maximum_ood((row(0, 1, 2), row(1, 2, 4))).primary_component_index == 1
    assert _maximum_ood((row(0, 0, 5), row(1, 0, 7))).primary_component_index == 1
    assert _maximum_ood((row(1, 0, 7), row(0, 0, 7))).primary_component_index == 0


def test_completion_contract_rejects_forged_rate_receipt_flag_and_conclusion_flag() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    result = complete_frozen_k4_diagnosis(replay, primary_fit, vectors, decomposition)
    with pytest.raises(ValueError, match="rate"):
        replace(result.offset_ood[0], rate=0.123)
    with pytest.raises(ValueError, match="strict"):
        replace(result.sample_receipts[0], ood_exceeds=not result.sample_receipts[0].ood_exceeds)
    with pytest.raises(ValueError, match="conclusion"):
        replace(
            result,
            offset_conclusions=(
                replace(
                    result.offset_conclusions[0],
                    drift_component_matches_full_sample=not result.offset_conclusions[0].drift_component_matches_full_sample,
                ),
            ) + result.offset_conclusions[1:],
        )


def test_completion_never_invokes_fit_rematch_gate_artifact_or_strategy_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("completion must remain descriptive and frozen")

    monkeypatch.setattr(
        "src.application.services.frozen_k4_failure_replay.SklearnClusterDiagnostic.fit",
        forbidden,
    )
    monkeypatch.setattr(
        "src.application.services.frozen_k4_failure_replay.linear_sum_assignment",
        forbidden,
    )
    monkeypatch.setattr("sklearn.preprocessing.RobustScaler.fit", forbidden)
    completed = complete_frozen_k4_diagnosis(replay, primary_fit, vectors, decomposition)
    assert len(completed.offset_conclusions) == 10


def test_completion_rejects_forged_canonical_receipt_fingerprint() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    result = complete_frozen_k4_diagnosis(replay, primary_fit, vectors, decomposition)
    forged = replace(result.sample_receipts[0], half_component_fingerprint="f" * 24)
    with pytest.raises(ValueError, match="fingerprints"):
        replace(result, sample_receipts=(forged,) + result.sample_receipts[1:])


def test_offset_drift_flags_compare_with_full_empirical_not_fitted_pair_distance() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    result = complete_frozen_k4_diagnosis(replay, primary_fit, vectors, decomposition)
    fitted_winner = min(
        (pair for half in replay.half_replays for pair in half.matched_pairs),
        key=lambda pair: (-pair.euclidean_distance, pair.half_label, pair.primary_component_index),
    )
    assert fitted_winner.primary_component_index == 0
    assert result.full_sample_empirical.maximum_drift_primary_component_index == 3
    assert all(row.drift_component_matches_full_sample for row in result.offset_conclusions)


def test_completion_rejects_valid_looking_non_frozen_500_sample_input() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    with pytest.raises(ValueError, match="1,641"):
        complete_frozen_k4_diagnosis(replay, primary_fit, vectors[:500], decomposition)


def test_completion_rejects_offset_ood_counts_swapped_while_spacing_totals_stay_equal() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    result = complete_frozen_k4_diagnosis(replay, primary_fit, vectors, decomposition)
    rows = list(result.offset_ood)
    first = next(index for index, row in enumerate(rows) if (row.spacing_days, row.offset, row.primary_component_index) == (3, 0, 0))
    second = next(index for index, row in enumerate(rows) if (row.spacing_days, row.offset, row.primary_component_index) == (3, 1, 0))
    a, b = rows[first], rows[second]
    rows[first] = replace(a, numerator=b.numerator, denominator=b.denominator, rate=b.rate)
    rows[second] = replace(b, numerator=a.numerator, denominator=a.denominator, rate=a.rate)
    with pytest.raises(ValueError, match="ledger"):
        replace(result, offset_ood=tuple(rows))


def test_completion_rejects_forged_offset_origin_and_receipt_half_count() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    result = complete_frozen_k4_diagnosis(replay, primary_fit, vectors, decomposition)
    scope = result.offset_empirical[0]
    forged_rows = tuple(
        replace(row, offset_origin_anchor="2021-01-02T00:00:00Z")
        for row in scope.centroid_rows
    )
    forged_scope = replace(scope, centroid_rows=forged_rows)
    with pytest.raises(ValueError, match="origin"):
        replace(result, offset_empirical=(forged_scope,) + result.offset_empirical[1:])

    source = next(
        row
        for row in result.sample_receipts
        if row.half_label == "A" and row.half_component_index == 2
    )
    b_pair = next(
        row
        for row in result.sample_receipts
        if row.half_label == "B" and row.half_component_index == source.half_component_index
    )
    forged_receipt = replace(
        source,
        half_label="B",
        half_component_fingerprint=b_pair.half_component_fingerprint,
        matched_primary_component_index=b_pair.matched_primary_component_index,
        matched_primary_component_fingerprint=b_pair.matched_primary_component_fingerprint,
    )
    forged_receipts = tuple(
        forged_receipt if row.global_index == source.global_index else row
        for row in result.sample_receipts
    )
    with pytest.raises(ValueError, match="half receipt counts"):
        replace(result, sample_receipts=forged_receipts)


def test_drift_match_uses_primary_identity_even_when_winning_half_changes() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    modified_fit = _namespace_replace(
        primary_fit,
        means=primary_fit.means[:3] + ((0.0,) * 6,),
    )
    result = complete_frozen_k4_diagnosis(replay, modified_fit, vectors, decomposition)
    assert result.full_sample_empirical.maximum_drift_half_label == "A"
    assert result.full_sample_empirical.maximum_drift_primary_component_index == 2
    conclusion = next(
        row for row in result.offset_conclusions if (row.spacing_days, row.offset) == (3, 1)
    )
    assert conclusion.maximum_drift_half_label == "B"
    assert conclusion.maximum_drift_primary_component_index == 2
    assert conclusion.drift_component_matches_full_sample is True


def test_completion_rejects_offset_fingerprint_forged_consistently_within_scope() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    result = complete_frozen_k4_diagnosis(replay, primary_fit, vectors, decomposition)
    scope = result.offset_empirical[0]
    forged_fingerprint = "f" * 24
    centroids = tuple(
        replace(row, primary_component_fingerprint=forged_fingerprint)
        if row.primary_component_index == 0
        else row
        for row in scope.centroid_rows
    )
    features = tuple(
        replace(row, primary_component_fingerprint=forged_fingerprint)
        if row.primary_component_index == 0
        else row
        for row in scope.feature_rows
    )
    forged_scope = replace(scope, centroid_rows=centroids, feature_rows=features)
    with pytest.raises(ValueError, match="fingerprints"):
        replace(result, offset_empirical=(forged_scope,) + result.offset_empirical[1:])


def test_conclusion_can_record_true_false_false_true_flags_independently() -> None:
    replay, primary_fit, vectors, decomposition = _completion_fixture()
    modified_vectors = tuple(
        _empirical_vector(
            index,
            (0.0, -0.5 if index % 7 == 3 else 0.5, 0.0, 0.0, 0.0, 0.0),
        )
        if component == 3 and index % 7 in (3, 4)
        else vector
        for index, (vector, component) in enumerate(zip(vectors, replay.primary_assignments))
    )
    promoted = {
        index
        for index, component in enumerate(replay.primary_assignments)
        if component == 1 and index % 7 == 3
    }
    promoted = set(sorted(promoted)[:4])
    ood_rows = tuple(
        _namespace_replace(
            row,
            squared_mahalanobis=1.0,
            exceeds=True,
        )
        if index in promoted
        else row
        for index, row in enumerate(replay.primary_ood_rows)
    )
    modified_replay = replace(replay, primary_ood_rows=ood_rows)
    result = complete_frozen_k4_diagnosis(
        modified_replay, primary_fit, modified_vectors, decomposition
    )
    conclusion = next(
        row for row in result.offset_conclusions if (row.spacing_days, row.offset) == (7, 3)
    )
    assert (
        conclusion.drift_component_matches_full_sample,
        conclusion.ood_component_matches_full_sample,
        conclusion.ordered_top5_matches_full_sample,
        conclusion.top5_set_matches_full_sample,
    ) == (True, False, False, True)


def test_full_sample_empirical_reference_uses_frozen_half_membership_and_primary_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay, primary_fit, vectors = _empirical_fixture()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("fit, matching, and rematching are forbidden")

    monkeypatch.setattr(
        "src.application.services.frozen_k4_failure_replay.SklearnClusterDiagnostic.fit",
        forbidden,
    )
    monkeypatch.setattr(
        "src.application.services.frozen_k4_failure_replay.linear_sum_assignment",
        forbidden,
    )
    monkeypatch.setattr("sklearn.preprocessing.RobustScaler.fit", forbidden)

    result = build_full_sample_empirical_reference(replay, primary_fit, vectors)

    assert isinstance(result, EmpiricalScopeSummary)
    assert result.sample_scope == "full_sample"
    assert result.spacing_days is None and result.offset is None
    assert result.selected_sample_count == 7
    assert result.maximum_drift_half_label == "B"
    assert result.maximum_drift_primary_component_index == 0
    assert result.maximum_drift_half_component_index == 0
    assert result.maximum_drift_primary_component_fingerprint == "1" * 24
    assert result.maximum_drift_half_component_fingerprint == "5" * 24
    assert result.maximum_drift_distance == pytest.approx(math.sqrt(128.0 / 3.0))
    assert result.top_five_drift_features == EMPIRICAL_NAMES[:5]

    rows = {(row.half_label, row.half_component_index): row for row in result.centroid_rows}
    assert rows[("A", 0)].sample_count == 1
    assert rows[("A", 0)].sample_share == pytest.approx(0.25)
    assert rows[("A", 0)].empirical_centroid == (3.0, 3.0, 0.0, 0.0, 0.0, 0.0)
    assert rows[("A", 0)].distance == pytest.approx(math.sqrt(12.0))
    assert rows[("A", 1)].sample_count == 3
    assert rows[("A", 1)].sample_share == pytest.approx(0.75)
    assert rows[("A", 1)].distance == 0.0
    assert rows[("B", 1)].sample_count == 0
    assert rows[("B", 1)].sample_share == 0.0
    assert rows[("B", 1)].centroid_status == "insufficient_sample"
    assert rows[("B", 1)].empirical_centroid is None and rows[("B", 1)].distance is None
    assert all(
        row.metric_name == "full_sample_empirical_centroid_distance"
        and row.assignment_source == "frozen_reproduced_half_assignment"
        and row.refit_performed is False
        and row.rematch_performed is False
        and row.diagnostic_only is True
        for row in rows.values()
    )
    assert sum(row.sample_count for row in rows.values()) == 7

    winner_features = tuple(
        row for row in result.feature_rows if row.half_label == "B" and row.half_component_index == 0
    )
    assert tuple(row.feature_name for row in winner_features) == EMPIRICAL_NAMES
    assert tuple(row.rank for row in winner_features) == (1, 2, 3, 4, 5, 6)
    assert tuple(row.squared_distance for row in winner_features) == pytest.approx((64.0 / 9.0,) * 6)
    assert tuple(row.contribution_ratio for row in winner_features) == pytest.approx((1 / 6,) * 6)
    zero_features = tuple(
        row for row in result.feature_rows if row.half_label == "A" and row.half_component_index == 1
    )
    assert all(row.contribution_ratio == 0.0 for row in zero_features)
    assert all(isinstance(row, EmpiricalFeatureContributionRow) for row in result.feature_rows)
    with pytest.raises(FrozenInstanceError):
        result.selected_sample_count = 1  # type: ignore[misc]


def test_empirical_contract_rejects_forged_rows_and_summary() -> None:
    replay, primary_fit, vectors = _empirical_fixture()
    result = build_full_sample_empirical_reference(replay, primary_fit, vectors)
    computed = result.centroid_rows[0]
    empty = result.centroid_rows[-1]
    feature = result.feature_rows[0]

    with pytest.raises(ValueError, match="full-sample"):
        replace(computed, spacing_days=3)
    with pytest.raises(ValueError, match="status"):
        replace(computed, centroid_status="insufficient_sample")
    with pytest.raises(ValueError, match="status"):
        replace(empty, distance=0.0)
    with pytest.raises(ValueError, match="centroid"):
        replace(computed, empirical_centroid=(True,) + computed.empirical_centroid[1:])
    with pytest.raises(ValueError, match="fingerprint"):
        replace(computed, primary_component_fingerprint="BAD")
    with pytest.raises(ValueError, match="finite and nonnegative"):
        replace(feature, squared_distance=float("nan"))
    with pytest.raises(ValueError, match="rank"):
        replace(feature, rank=0)
    with pytest.raises(ValueError, match="maximum"):
        replace(result, maximum_drift_distance=0.0)
    with pytest.raises(ValueError, match="top-five"):
        replace(result, top_five_drift_features=tuple(reversed(result.top_five_drift_features)))
    with pytest.raises(ValueError, match="feature"):
        replace(result, feature_rows=result.feature_rows[:-1])
    missing_zero_feature = tuple(
        row for row in result.feature_rows if row.feature_name != "rv_4h"
    )
    with pytest.raises(ValueError, match="feature"):
        replace(
            result,
            feature_rows=missing_zero_feature,
            top_five_drift_features=result.top_five_drift_features,
        )
    mixed_origin = replace(result.centroid_rows[0], offset_origin_anchor="2021-01-02T00:00:00Z")
    with pytest.raises(ValueError, match="origin"):
        replace(result, centroid_rows=(mixed_origin,) + result.centroid_rows[1:])
    forged_share = replace(result.centroid_rows[0], sample_share=0.5)
    with pytest.raises(ValueError, match="share"):
        replace(result, centroid_rows=(forged_share,) + result.centroid_rows[1:])
    duplicate_identity = replace(
        result.centroid_rows[1],
        primary_component_index=result.centroid_rows[0].primary_component_index,
        half_component_index=result.centroid_rows[0].half_component_index,
        primary_component_fingerprint=result.centroid_rows[0].primary_component_fingerprint,
        half_component_fingerprint=result.centroid_rows[0].half_component_fingerprint,
    )
    with pytest.raises(ValueError, match="unique"):
        replace(result, centroid_rows=(result.centroid_rows[0], duplicate_identity) + result.centroid_rows[2:])
    orphan = replace(
        result.feature_rows[0],
        half_component_index=9,
        half_component_fingerprint="f" * 24,
    )
    with pytest.raises(ValueError, match="group identities"):
        replace(result, feature_rows=result.feature_rows + (orphan,))
    first_group = (
        result.feature_rows[0].half_label,
        result.feature_rows[0].primary_component_index,
        result.feature_rows[0].half_component_index,
    )
    missing_group = tuple(
        row
        for row in result.feature_rows
        if (row.half_label, row.primary_component_index, row.half_component_index) != first_group
    )
    with pytest.raises(ValueError, match="group identities"):
        replace(result, feature_rows=missing_group)
    insufficient = result.centroid_rows[-1]
    insufficient_feature = replace(
        result.feature_rows[0],
        half_label=insufficient.half_label,
        primary_component_index=insufficient.primary_component_index,
        half_component_index=insufficient.half_component_index,
        primary_component_fingerprint=insufficient.primary_component_fingerprint,
        half_component_fingerprint=insufficient.half_component_fingerprint,
    )
    with pytest.raises(ValueError, match="group identities"):
        replace(result, feature_rows=result.feature_rows + (insufficient_feature,))


def test_empirical_summary_rejects_incomplete_or_inconsistent_component_graph() -> None:
    replay, primary_fit, vectors = _empirical_fixture()
    result = build_full_sample_empirical_reference(replay, primary_fit, vectors)

    only_a_centroids = tuple(row for row in result.centroid_rows if row.half_label == "A")
    only_a_features = tuple(row for row in result.feature_rows if row.half_label == "A")
    a_winner = max(
        (row for row in only_a_centroids if row.centroid_status == "computed"),
        key=lambda row: row.distance,
    )
    a_winner_features = tuple(
        row
        for row in only_a_features
        if row.primary_component_index == a_winner.primary_component_index
        and row.half_component_index == a_winner.half_component_index
    )
    with pytest.raises(ValueError, match="A and B"):
        replace(
            result,
            selected_sample_count=sum(row.sample_count for row in only_a_centroids),
            centroid_rows=only_a_centroids,
            feature_rows=only_a_features,
            maximum_drift_half_label="A",
            maximum_drift_primary_component_index=a_winner.primary_component_index,
            maximum_drift_half_component_index=a_winner.half_component_index,
            maximum_drift_primary_component_fingerprint=a_winner.primary_component_fingerprint,
            maximum_drift_half_component_fingerprint=a_winner.half_component_fingerprint,
            maximum_drift_distance=a_winner.distance,
            top_five_drift_features=tuple(row.feature_name for row in a_winner_features[:5]),
        )

    missing_empty_pair = tuple(
        row
        for row in result.centroid_rows
        if not (row.half_label == "B" and row.half_component_index == 1)
    )
    with pytest.raises(ValueError, match="complete"):
        replace(result, centroid_rows=missing_empty_pair)

    forged_fingerprint = "e" * 24
    forged_centroids = tuple(
        replace(row, primary_component_fingerprint=forged_fingerprint)
        if row.half_label == "B" and row.primary_component_index == 0
        else row
        for row in result.centroid_rows
    )
    forged_features = tuple(
        replace(row, primary_component_fingerprint=forged_fingerprint)
        if row.half_label == "B" and row.primary_component_index == 0
        else row
        for row in result.feature_rows
    )
    with pytest.raises(ValueError, match="primary fingerprint"):
        replace(
            result,
            centroid_rows=forged_centroids,
            feature_rows=forged_features,
            maximum_drift_primary_component_fingerprint=forged_fingerprint,
        )


def test_empirical_maximum_ties_use_half_then_primary_then_half_component_order() -> None:
    replay, primary_fit, vectors = _empirical_fixture()
    half_tie_vectors = vectors[:4] + tuple(
        _empirical_vector(index, (2.0, 2.0, 1.0, 1.0, 1.0, 1.0))
        for index in range(4, 7)
    )
    half_tie = build_full_sample_empirical_reference(replay, primary_fit, half_tie_vectors)
    assert half_tie.maximum_drift_half_label == "A"
    assert half_tie.maximum_drift_primary_component_index == 1
    assert half_tie.maximum_drift_half_component_index == 0

    component_tie_vectors = (
        _empirical_vector(0, (2.0, 1.0, 1.0, 1.0, 1.0, 1.0)),
        _empirical_vector(1, (1.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        _empirical_vector(2, (1.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        _empirical_vector(3, (1.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
    ) + tuple(_empirical_vector(index, (0.0,) * 6) for index in range(4, 7))
    component_tie = build_full_sample_empirical_reference(replay, primary_fit, component_tie_vectors)
    assert component_tie.maximum_drift_half_label == "A"
    assert component_tie.maximum_drift_primary_component_index == 0
    assert component_tie.maximum_drift_half_component_index == 1


def test_full_sample_empirical_reference_rejects_reversed_halves_and_receipt_interval_mismatch() -> None:
    replay, primary_fit, vectors = _empirical_fixture()
    reversed_halves = replace(replay, half_replays=tuple(reversed(replay.half_replays)))
    with pytest.raises(ValueError, match="A then B"):
        build_full_sample_empirical_reference(reversed_halves, primary_fit, vectors)

    bad_receipt = SimpleNamespace(
        half_label="A",
        anchor_count=4,
        anchor_range=("2021-01-02T00:00:00Z", "2021-01-05T00:00:00Z"),
    )
    bad_boundary = replace(
        replay,
        half_replays=(replace(replay.half_replays[0], receipt=bad_receipt), replay.half_replays[1]),
    )
    with pytest.raises(ValueError, match="receipt interval"):
        build_full_sample_empirical_reference(bad_boundary, primary_fit, vectors)

    unsorted_vectors = (vectors[1], vectors[0]) + vectors[2:]
    unsorted_replay = replace(
        replay,
        primary_ood_rows=(replay.primary_ood_rows[1], replay.primary_ood_rows[0])
        + replay.primary_ood_rows[2:],
    )
    with pytest.raises(ValueError, match="chronological"):
        build_full_sample_empirical_reference(unsorted_replay, primary_fit, unsorted_vectors)


@pytest.mark.parametrize("target", ("replay", "half", "receipt", "fit"))
def test_full_sample_empirical_reference_rejects_laundered_diagnostic_provenance(
    target: str,
) -> None:
    replay, primary_fit, vectors = _empirical_fixture()
    if target == "replay":
        forged = replace(replay, diagnostic_only=False)
    elif target == "half":
        forged = replace(
            replay,
            half_replays=(
                replace(replay.half_replays[0], primary_replacement_allowed=True),
                replay.half_replays[1],
            ),
        )
    elif target == "receipt":
        receipt = _namespace_replace(replay.half_replays[0].receipt, diagnostic_only=False)
        forged = replace(
            replay,
            half_replays=(replace(replay.half_replays[0], receipt=receipt), replay.half_replays[1]),
        )
    else:
        fit = _namespace_replace(replay.half_replays[0].fit, primary_replacement_allowed=True)
        forged = replace(
            replay,
            half_replays=(replace(replay.half_replays[0], fit=fit), replay.half_replays[1]),
        )
    with pytest.raises(ValueError, match="diagnostic provenance"):
        build_full_sample_empirical_reference(forged, primary_fit, vectors)


def _extreme_empirical_fixture(
    *,
    primary_mean: float,
    vector_value: float = 1e308,
) -> tuple[FrozenK4Replay, SimpleNamespace, tuple[SimpleNamespace, ...]]:
    name = EMPIRICAL_NAMES[0]
    primary_fit = SimpleNamespace(
        feature_names=(name,),
        lower_bounds=(-1e308,),
        upper_bounds=(1e308,),
        medians=(0.0,),
        scales=(1.0,),
        fingerprints=("1" * 24,),
        means=((primary_mean,),),
    )
    vectors = tuple(
        SimpleNamespace(
            anchor_at=datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
            values=MappingProxyType({name: vector_value}),
        )
        for index in range(3)
    )

    def half(label: str, start: int, count: int) -> FrozenK4HalfReplay:
        half_fit = SimpleNamespace(
            feature_names=(name,),
            fingerprints=(("2" if label == "A" else "3") * 24,),
            means=((0.0,),),
            diagnostic_only=True,
            primary_replacement_allowed=False,
        )
        boundary_start = vectors[start].anchor_at.isoformat().replace("+00:00", "Z")
        boundary_end = (vectors[start + count - 1].anchor_at + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        return FrozenK4HalfReplay(
            receipt=SimpleNamespace(
                half_label=label,
                anchor_count=count,
                anchor_range=(boundary_start, boundary_end),
                diagnostic_only=True,
                primary_replacement_allowed=False,
            ),
            fit=half_fit,
            assignments=(0,) * count,
            posterior_probabilities=(),
            projected_centroids=(),
            projected_covariances=(),
            precisions=(),
            precisions_cholesky=(),
            cost_matrix=(),
            hungarian_assignment=(),
            matched_pairs=(
                MatchedPair(
                    half_label=label,
                    primary_component_fingerprint="1" * 24,
                    half_component_fingerprint=half_fit.fingerprints[0],
                    primary_component_index=0,
                    half_component_index=0,
                    matching_cost=0.0,
                    euclidean_distance=0.0,
                ),
            ),
            pair_euclidean_distances=(),
            component_weights=(),
        )

    replay = FrozenK4Replay(
        input_identity=SimpleNamespace(),
        dependency_metadata={},
        status=SimpleNamespace(status="reproduced"),
        half_replays=(half("A", 0, 2), half("B", 2, 1)),
        primary_assignments=(0, 0, 0),
        primary_ood_rows=tuple(
            SimpleNamespace(
                anchor_at=vector.anchor_at.isoformat().replace("+00:00", "Z"),
                assigned_component_index=0,
                assigned_component_fingerprint="1" * 24,
            )
            for vector in vectors
        ),
    )
    return replay, primary_fit, vectors


def test_empirical_mean_is_overflow_safe_and_extreme_delta_rejects_without_warning() -> None:
    replay, primary_fit, vectors = _extreme_empirical_fixture(primary_mean=1e308)
    result = build_full_sample_empirical_reference(replay, primary_fit, vectors)
    assert all(row.empirical_centroid == (1e308,) for row in result.centroid_rows)
    assert all(row.distance == 0.0 for row in result.centroid_rows)

    replay, primary_fit, vectors = _extreme_empirical_fixture(primary_mean=-1e308)
    with warnings.catch_warnings(record=True) as warning_record:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match="representable range"):
            build_full_sample_empirical_reference(replay, primary_fit, vectors)
    assert not warning_record

    replay, primary_fit, vectors = _extreme_empirical_fixture(
        primary_mean=0.0,
        vector_value=1e-320,
    )
    underflow = build_full_sample_empirical_reference(replay, primary_fit, vectors)
    assert all(row.empirical_centroid == (1e-320,) for row in underflow.centroid_rows)
    assert all(row.distance == 0.0 for row in underflow.centroid_rows)
    assert all(row.squared_distance == 0.0 for row in underflow.feature_rows)
    assert all(row.contribution_ratio == 0.0 for row in underflow.feature_rows)


def _namespace_replace(value: SimpleNamespace, **changes) -> SimpleNamespace:
    return SimpleNamespace(**(vars(value) | changes))


def _forge_replay_status(replay: FrozenK4Replay, status: str) -> FrozenK4Replay:
    object.__setattr__(replay, "status", SimpleNamespace(status=status))
    return replay


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda replay, fit, vectors: (replay, fit, list(vectors)), "immutable"),
        (lambda replay, fit, vectors: (replay, fit, vectors[:-1]), "length"),
        (lambda replay, fit, vectors: (_forge_replay_status(replay, "mismatch"), fit, vectors), "reproduced"),
        (lambda replay, fit, vectors: (replace(replay, primary_ood_rows=replay.primary_ood_rows[:-1]), fit, vectors), "length"),
        (lambda replay, fit, vectors: (replace(replay, primary_ood_rows=(SimpleNamespace(**(vars(replay.primary_ood_rows[0]) | {"assigned_component_index": 1})),) + replay.primary_ood_rows[1:]), fit, vectors), "OOD"),
        (lambda replay, fit, vectors: (replay, _namespace_replace(fit, scales=(1.0, 0.0, 1.0, 2.0, 1.0, 2.0)), vectors), "scales"),
        (lambda replay, fit, vectors: (replay, _namespace_replace(fit, lower_bounds=(11.0,) + fit.lower_bounds[1:]), vectors), "bounds"),
        (lambda replay, fit, vectors: (replay, _namespace_replace(fit, means=((0.0,), fit.means[1])), vectors), "dimensions"),
        (lambda replay, fit, vectors: (replay, fit, vectors[:1] + (_empirical_vector(1, (float("nan"),) * 6),) + vectors[2:]), "finite"),
        (lambda replay, fit, vectors: (replace(replay, half_replays=(replace(replay.half_replays[0], matched_pairs=replay.half_replays[0].matched_pairs[:1]), replay.half_replays[1])), fit, vectors), "complete"),
        (lambda replay, fit, vectors: (replace(replay, half_replays=(replace(replay.half_replays[0], matched_pairs=(replay.half_replays[0].matched_pairs[0], replay.half_replays[0].matched_pairs[0])), replay.half_replays[1])), fit, vectors), "one-to-one"),
        (lambda replay, fit, vectors: (replace(replay, half_replays=(replace(replay.half_replays[0], matched_pairs=(replace(replay.half_replays[0].matched_pairs[0], primary_component_fingerprint="1" * 24), replay.half_replays[0].matched_pairs[1])), replay.half_replays[1])), fit, vectors), "index-fingerprint"),
        (lambda replay, fit, vectors: (replace(replay, half_replays=(replace(replay.half_replays[0], assignments=(9,) + replay.half_replays[0].assignments[1:]), replay.half_replays[1])), fit, vectors), "assignment index"),
        (lambda replay, fit, vectors: (replace(replay, half_replays=(replace(replay.half_replays[0], receipt=SimpleNamespace(half_label="A", anchor_count=3, anchor_range=("2021-01-01T00:00:00Z", "2021-01-05T00:00:00Z"))), replay.half_replays[1])), fit, vectors), "receipt count"),
    ],
)
def test_full_sample_empirical_reference_rejects_invalid_frozen_inputs(mutate, message: str) -> None:
    replay, primary_fit, vectors = _empirical_fixture()
    bad_replay, bad_fit, bad_vectors = mutate(replay, primary_fit, vectors)
    with pytest.raises(ValueError, match=message):
        build_full_sample_empirical_reference(bad_replay, bad_fit, bad_vectors)
