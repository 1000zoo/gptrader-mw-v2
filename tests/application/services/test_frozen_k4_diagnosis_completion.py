from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType, SimpleNamespace

import pytest

from src.application.services.frozen_k4_failure_decomposition import (
    CauseClassification,
    FrozenK4Decomposition,
    OODComponentRow,
    OODSampleContributionRow,
)
from src.application.services.frozen_k4_diagnosis_completion import (
    ComponentZeroOODAnalysis,
    EmpiricalCentroidRow,
    EmpiricalFeatureContributionRow,
    EmpiricalScopeSummary,
    OODFamilySummaryRow,
    OODFeatureSummaryRow,
    _canonical_registry_payload,
    _canonical_registry_sha256,
    _meets_threshold,
    build_full_sample_empirical_reference,
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
            )
            for row, component in zip(vectors, (0, 0, 0, 0, 1, 1, 1))
        ),
    )
    return replay, primary_fit, vectors


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
