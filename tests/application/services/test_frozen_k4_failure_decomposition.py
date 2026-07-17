from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from src.application.services.frozen_k4_failure_decomposition import (
    decompose_frozen_k4_failure,
)
from src.application.services.frozen_k4_failure_replay import (
    FrozenK4HalfReplay,
    FrozenK4Replay,
)
from src.domain.regime.frozen_k4_failure_diagnostics import (
    DiagnosisStatus,
    FrozenK4InputIdentity,
    HalfFitReceipt,
    MatchedPair,
    MetricReproduction,
    OODRow,
)


def _ts(index: int) -> datetime:
    return datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)


def _vector(index: int, x: float, y: float):
    return SimpleNamespace(anchor_at=_ts(index), values={"x": x, "y": y})


def _fixture():
    primary_fit = SimpleNamespace(
        feature_names=("x", "y"),
        fingerprints=("a" * 24, "b" * 24),
        means=((0.0, 0.0), (10.0, 0.0)),
        covariances=((1.0, 4.0), (9.0, 16.0)),
        lower_bounds=(0.0, 0.0),
        upper_bounds=(10.0, 10.0),
        medians=(0.0, 0.0),
        scales=(1.0, 1.0),
    )
    half_fit = SimpleNamespace(
        feature_names=("x", "y"),
        fingerprints=("c" * 24, "d" * 24),
        means=((3.0, 4.0), (9.0, 0.0)),
        covariances=((2.0, 2.0), (1.0, 1.0)),
        lower_bounds=(0.0, 0.0),
        upper_bounds=(10.0, 10.0),
        medians=(0.0, 0.0),
        scales=(1.0, 1.0),
    )
    half = FrozenK4HalfReplay(
        receipt=HalfFitReceipt("A", 820, "f" * 64),
        fit=half_fit,
        assignments=(0, 0, 0, 0, 1, 1),
        posterior_probabilities=(),
        projected_centroids=((3.0, 4.0), (9.0, 0.0)),
        projected_covariances=((2.0, 2.0), (1.0, 1.0)),
        precisions=(),
        precisions_cholesky=(),
        cost_matrix=(),
        hungarian_assignment=((0, 0), (1, 1)),
        matched_pairs=(
            MatchedPair(
                half_label="A",
                primary_component_fingerprint="a" * 24,
                half_component_fingerprint="c" * 24,
                primary_component_index=0,
                half_component_index=0,
                matching_cost=5.0,
                euclidean_distance=5.0,
            ),
            MatchedPair(
                half_label="A",
                primary_component_fingerprint="b" * 24,
                half_component_fingerprint="d" * 24,
                primary_component_index=1,
                half_component_index=1,
                matching_cost=1.0,
                euclidean_distance=1.0,
            ),
        ),
        pair_euclidean_distances=(5.0, 1.0),
        component_weights=(0.6, 0.4),
    )
    identity = FrozenK4InputIdentity(
        *("a" * 64 for _ in range(10)),
        split_at="2023-04-01T00:00:00Z",
        half_a_range=("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
        half_b_range=("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z"),
    )
    replay = FrozenK4Replay(
        input_identity=identity,
        dependency_metadata={"runtime": "unit"},
        status=DiagnosisStatus.reproduced(
            MetricReproduction.compare(1.0, 1.0),
            MetricReproduction.compare(0.5, 0.5),
            3,
            6,
        ),
        half_replays=(half,),
        primary_assignments=(0, 0, 0, 0, 1, 1),
        primary_posterior_probabilities=(),
        primary_ood_rows=(
            OODRow(
                anchor_at="2021-01-01T00:00:00Z",
                assigned_component_index=0,
                assigned_component_fingerprint="a" * 24,
                squared_mahalanobis=1.0,
                threshold=9.0,
                exceeds=False,
            ),
            OODRow(
                anchor_at="2021-01-02T00:00:00Z",
                assigned_component_index=0,
                assigned_component_fingerprint="a" * 24,
                squared_mahalanobis=10.0,
                threshold=9.0,
                exceeds=True,
            ),
            OODRow(
                anchor_at="2021-01-03T00:00:00Z",
                assigned_component_index=0,
                assigned_component_fingerprint="a" * 24,
                squared_mahalanobis=20.0,
                threshold=9.0,
                exceeds=True,
            ),
            OODRow(
                anchor_at="2021-01-04T00:00:00Z",
                assigned_component_index=0,
                assigned_component_fingerprint="a" * 24,
                squared_mahalanobis=5.0,
                threshold=9.0,
                exceeds=False,
            ),
            OODRow(
                anchor_at="2021-01-05T00:00:00Z",
                assigned_component_index=1,
                assigned_component_fingerprint="b" * 24,
                squared_mahalanobis=12.0,
                threshold=9.0,
                exceeds=True,
            ),
            OODRow(
                anchor_at="2021-01-06T00:00:00Z",
                assigned_component_index=1,
                assigned_component_fingerprint="b" * 24,
                squared_mahalanobis=2.0,
                threshold=9.0,
                exceeds=False,
            ),
        ),
    )
    vectors = (
        _vector(0, -1.0, 0.0),
        _vector(1, 3.0, 12.0),
        _vector(2, 3.0, 4.0),
        _vector(3, 9.0, 0.0),
        _vector(4, 9.0, 0.0),
        _vector(5, 10.0, 0.0),
    )
    return replay, primary_fit, vectors


def test_feature_contributions_rank_squared_euclidean_drift() -> None:
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)

    pair0 = [
        row for row in result.feature_contributions
        if row.half_label == "A" and row.primary_component_index == 0
    ]
    assert [(row.feature_name, row.squared_distance) for row in pair0] == [
        ("y", 16.0),
        ("x", 9.0),
    ]
    assert pair0[0].contribution_ratio == pytest.approx(16.0 / 25.0)
    assert result.top_drift_features[("A", 0)][:2] == ("y", "x")


def test_cluster_summary_and_cause_classification_are_populated_from_decomposition() -> None:
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)

    summary = {
        (row.half_label, row.primary_component_index): row
        for row in result.cluster_summaries
    }
    assert summary[("A", 0)].half_component_index == 0
    assert summary[("A", 0)].sample_count == 4
    assert summary[("A", 0)].exceedance_count == 2
    assert summary[("A", 0)].euclidean_distance == pytest.approx(5.0)
    assert set(result.cause_classification.causes) >= {
        "specific-feature-drift",
        "component-ood-concentration",
        "covariance-aware-drift",
    }
    assert result.cause_classification.diagnostic_only is True


def test_robust_locations_compare_mean_median_trimmed_mean_and_medoid() -> None:
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)

    distances = {
        row.statistic: row.centroid_distance
        for row in result.location_distances
        if row.half_label == "A" and row.primary_component_index == 0
    }
    component_samples = np.asarray(
        ((0.0, 0.0), (3.0, 10.0), (3.0, 4.0), (9.0, 0.0))
    )
    assert distances["mean"] == pytest.approx(
        np.linalg.norm(component_samples.mean(axis=0))
    )
    assert distances["coordinate_median"] == pytest.approx(
        np.linalg.norm(np.median(component_samples, axis=0))
    )
    assert distances["trimmed_mean_10pct"] == pytest.approx(
        np.linalg.norm(component_samples.mean(axis=0))
    )
    assert distances["medoid"] == pytest.approx(5.0)


def test_clipped_samples_record_feature_and_direction() -> None:
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)

    assert [
        (row.anchor_at, row.feature_name, row.direction, row.raw_value, row.clipped_value)
        for row in result.clipped_samples
    ] == [
        ("2021-01-01T00:00:00Z", "x", "lower", -1.0, 0.0),
        ("2021-01-02T00:00:00Z", "y", "upper", 12.0, 10.0),
    ]


def test_exclusion_sensitivity_uses_fixed_assignments_and_stable_anchor_ties() -> None:
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)

    rows = [
        row for row in result.exclusion_sensitivity
        if row.half_label == "A" and row.component_fingerprint == "a" * 24
    ]
    assert [(row.statistic, row.excluded_count) for row in rows] == [
        ("exclude_farthest_1", 1),
        ("exclude_farthest_3", 3),
        ("exclude_farthest_5", 4),
        ("exclude_farthest_1pct", 1),
    ]
    remaining_after_farthest = np.asarray(((0.0, 0.0), (3.0, 4.0), (9.0, 0.0)))
    assert rows[0].centroid_distance == pytest.approx(
        np.linalg.norm(remaining_after_farthest.mean(axis=0))
    )
    assert all(row.assignment_source == "frozen_reproduced_half_assignment" for row in rows)
    assert all(row.refit_after_exclusion is False for row in rows)
    assert all(row.diagnostic_only is True for row in rows)


def test_pooled_mahalanobis_uses_empirical_half_variance_and_feature_contributions() -> None:
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)

    row = next(
        row for row in result.pooled_mahalanobis
        if row.half_label == "A" and row.primary_component_index == 0
    )
    component_samples = np.asarray(
        ((0.0, 0.0), (3.0, 10.0), (3.0, 4.0), (9.0, 0.0))
    )
    empirical = np.var(component_samples, axis=0, ddof=1)
    pooled = (np.asarray((1.0, 4.0)) + empirical) / 2.0
    expected = np.asarray((9.0, 16.0)) / pooled
    assert row.squared_distance == pytest.approx(expected.sum())
    assert row.feature_contributions["x"] == pytest.approx(expected[0])
    assert row.feature_contributions["y"] == pytest.approx(expected[1])


def test_component_distance_formulas_cover_symmetric_kl_bhattacharyya_and_wasserstein() -> None:
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)

    rows = {
        row.metric: row.distance
        for row in result.component_distances
        if row.half_label == "A" and row.primary_component_index == 0
    }
    assert rows["euclidean"] == pytest.approx(5.0)
    primary_variance = np.asarray((1.0, 4.0))
    half_variance = np.asarray((2.0, 2.0))
    delta = np.asarray((3.0, 4.0))
    kl_primary_half = 0.5 * np.sum(
        np.log(half_variance / primary_variance)
        + (primary_variance + delta**2) / half_variance
        - 1.0
    )
    kl_half_primary = 0.5 * np.sum(
        np.log(primary_variance / half_variance)
        + (half_variance + delta**2) / primary_variance
        - 1.0
    )
    average = (primary_variance + half_variance) / 2.0
    bhattacharyya = 0.125 * np.sum(delta**2 / average) + 0.5 * np.sum(
        np.log(average / np.sqrt(primary_variance * half_variance))
    )
    assert rows["symmetric_kl"] == pytest.approx(
        (kl_primary_half + kl_half_primary) / 2.0
    )
    assert rows["bhattacharyya"] == pytest.approx(bhattacharyya)
    assert rows["diagonal_wasserstein_2"] == pytest.approx(
        25.0 + (1.0 - np.sqrt(2.0)) ** 2 + (2.0 - np.sqrt(2.0)) ** 2
    )


def test_ood_counts_and_top_mahalanobis_features_are_component_scoped() -> None:
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)

    counts = {row.component_index: row for row in result.ood_by_component}
    assert counts[0].sample_count == 4
    assert counts[0].exceedance_count == 2
    assert counts[0].exceedance_rate == pytest.approx(0.5)
    assert counts[1].sample_count == 2
    assert counts[1].exceedance_count == 1
    sample = next(
        row
        for row in result.ood_samples
        if row.anchor_at == "2021-01-02T00:00:00Z"
    )
    assert sample.feature_contributions == {"y": 25.0, "x": 9.0}


def test_offsets_use_fixed_assignments_without_refit(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure.regime.sklearn_cluster_diagnostic import SklearnClusterDiagnostic

    def explode(*args, **kwargs):
        raise AssertionError("decomposition must not fit")

    monkeypatch.setattr(SklearnClusterDiagnostic, "fit", explode)
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)

    assert {(row.spacing_days, row.offset) for row in result.offset_subsamples} == {
        (3, 0), (3, 1), (3, 2), (7, 0), (7, 1), (7, 2), (7, 3), (7, 4), (7, 5), (7, 6)
    }
    assert all(
        row.assignment_source == "frozen_reproduced_half_assignment"
        for row in result.offset_subsamples
    )
    assert all(row.refit_after_exclusion is False for row in result.offset_subsamples)
    assert all(row.diagnostic_only is True for row in result.offset_subsamples)


def test_outputs_do_not_expose_forbidden_later_stage_terms_or_dates() -> None:
    replay, primary_fit, vectors = _fixture()

    result = decompose_frozen_k4_failure(replay, primary_fit, vectors)
    text = repr(result).lower()

    for forbidden in ("strategy", "mapping", "evidence", "validation", "test"):
        assert forbidden not in text
    assert "2025-06-30" not in text


@pytest.mark.parametrize(
    "payload",
    (
        {"Mapping": "leak"},
        {"safe": "strategy leak"},
        {"safe": ["Validation leak"]},
        {"safe": {"nested": datetime(2025, 6, 30, tzinfo=timezone.utc)}},
    ),
)
def test_recursive_guard_rejects_forbidden_input_context(payload: object) -> None:
    replay, primary_fit, vectors = _fixture()

    with pytest.raises(ValueError, match="isolation guard"):
        decompose_frozen_k4_failure(
            replay,
            primary_fit,
            vectors,
            source_context=payload,
        )


def test_recursive_guard_rejects_forbidden_primary_or_vector_inputs() -> None:
    replay, primary_fit, vectors = _fixture()
    forbidden_fit = SimpleNamespace(
        **{**primary_fit.__dict__, "feature_names": ("x", "strategy_signal")}
    )
    with pytest.raises(ValueError, match="isolation guard"):
        decompose_frozen_k4_failure(replay, forbidden_fit, vectors)

    late_vector = SimpleNamespace(
        **{
            **vectors[-1].__dict__,
            "anchor_at": datetime(2025, 6, 30, tzinfo=timezone.utc),
        }
    )
    late_vectors = tuple(vectors[:-1]) + (
        late_vector,
    )
    with pytest.raises(ValueError, match="isolation guard"):
        decompose_frozen_k4_failure(replay, primary_fit, late_vectors)


def test_rejects_ad_hoc_mutable_replay_object() -> None:
    replay, primary_fit, vectors = _fixture()
    fake = SimpleNamespace(**replay.__dict__)

    with pytest.raises(ValueError, match="FrozenK4Replay"):
        decompose_frozen_k4_failure(fake, primary_fit, vectors)


def test_rejects_non_reproduced_replay() -> None:
    replay, primary_fit, vectors = _fixture()
    mismatch = FrozenK4Replay(
        input_identity=replay.input_identity,
        dependency_metadata={"runtime": "unit"},
        status=DiagnosisStatus.causal_mismatch_unavailable(
            "input-data-mismatch",
            "b" * 64,
        ),
    )

    with pytest.raises(ValueError, match="requires reproduced replay"):
        decompose_frozen_k4_failure(mismatch, primary_fit, vectors)
