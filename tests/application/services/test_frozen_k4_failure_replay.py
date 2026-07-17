from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.application.services.frozen_k4_failure_replay import (
    EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE,
    EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE,
    _classify_strict_ood,
    _match_projected_centroids,
    _project_half_centroids,
    _validate_exact_split,
    replay_frozen_k4_failures,
)
from src.domain.regime.frozen_k4_failure_diagnostics import FrozenK4InputIdentity
from src.domain.regime.model import RegimeModelConfig
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    ThreeDayChartFeatureVector,
)
from src.infrastructure.regime.frozen_k4_diagnostic_source import (
    FrozenK4DiagnosticSource,
    load_frozen_k4_diagnostic_source,
)
from src.infrastructure.regime.sklearn_cluster_diagnostic import (
    SklearnClusterDiagnostic,
)


def test_projection_inverts_half_scaler_clips_in_primary_units_then_scales() -> None:
    projected = _project_half_centroids(
        half_means=np.asarray(((2.0, -3.0),)),
        half_medians=np.asarray((10.0, 20.0)),
        half_scales=np.asarray((4.0, 5.0)),
        primary_lower=np.asarray((0.0, 8.0)),
        primary_upper=np.asarray((16.0, 30.0)),
        primary_medians=np.asarray((4.0, 10.0)),
        primary_scales=np.asarray((2.0, 4.0)),
    )

    # raw=(18,5), clipped=(16,8), projected=(6,-.5)
    np.testing.assert_array_equal(projected, np.asarray(((6.0, -0.5),)))


def test_primary_clipping_can_change_the_hungarian_pairing() -> None:
    primary = np.asarray(((0.0,), (4.0,)))
    half_means = np.asarray(((10.0,), (3.0,)))
    clipped = _project_half_centroids(
        half_means=half_means,
        half_medians=np.asarray((0.0,)),
        half_scales=np.asarray((1.0,)),
        primary_lower=np.asarray((-100.0,)),
        primary_upper=np.asarray((2.0,)),
        primary_medians=np.asarray((0.0,)),
        primary_scales=np.asarray((1.0,)),
    )
    unclipped = half_means

    clipped_match = _match_projected_centroids(primary, clipped)
    unclipped_match = _match_projected_centroids(primary, unclipped)

    assert clipped_match.assignment == ((0, 0), (1, 1))
    assert unclipped_match.assignment == ((0, 1), (1, 0))


def test_matching_identity_is_stable_under_display_component_permutations() -> None:
    primary = np.asarray(((0.0, 0.0), (4.0, 0.0), (0.0, 7.0), (9.0, 9.0)))
    half = np.asarray(((8.0, 9.0), (0.0, 6.0), (3.0, 0.0), (0.0, 1.0)))
    primary_ids = ("p0", "p1", "p2", "p3")
    half_ids = ("h3", "h2", "h1", "h0")
    expected = {("p0", "h0"), ("p1", "h1"), ("p2", "h2"), ("p3", "h3")}

    for primary_order, half_order in (
        ((0, 1, 2, 3), (0, 1, 2, 3)),
        ((2, 0, 3, 1), (3, 1, 0, 2)),
    ):
        result = _match_projected_centroids(
            primary[list(primary_order)], half[list(half_order)]
        )
        identity = {
            (primary_ids[primary_order[p]], half_ids[half_order[h]])
            for p, h in result.assignment
        }
        assert identity == expected


def test_matching_cost_matrix_and_distances_use_euclidean_distance() -> None:
    primary = np.asarray(((0.0, 0.0), (10.0, 0.0)))
    half = np.asarray(((7.0, 4.0), (3.0, 4.0)))

    result = _match_projected_centroids(primary, half)

    np.testing.assert_allclose(
        result.cost_matrix, ((np.sqrt(65), 5.0), (5.0, np.sqrt(65)))
    )
    assert result.assignment == ((0, 1), (1, 0))
    assert result.pair_distances == (5.0, 5.0)


def test_ood_uses_strict_greater_than_and_integer_fraction() -> None:
    distances = np.asarray((4.0, np.nextafter(4.0, np.inf), 3.0))

    flags, numerator, denominator, rate = _classify_strict_ood(distances, 4.0)

    assert flags.tolist() == [False, True, False]
    assert type(numerator) is int and numerator == 1
    assert type(denominator) is int and denominator == 3
    assert rate == numerator / denominator


@pytest.mark.parametrize("mutation", ("missing", "duplicate"))
def test_exact_split_rejects_interior_missing_or_duplicate_anchor(mutation: str) -> None:
    anchors = [
        datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
        for index in range(1641)
    ]
    if mutation == "missing":
        del anchors[400]
    else:
        anchors[400] = anchors[399]
    source = SimpleNamespace(
        vectors=tuple(SimpleNamespace(anchor_at=value) for value in anchors),
        identity=SimpleNamespace(
            split_at="2023-04-01T00:00:00Z",
            half_a_range=("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
            half_b_range=("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z"),
        ),
    )

    assert _validate_exact_split(source) is False


def _compact_case():
    import src.application.services.frozen_k4_failure_replay as module

    registry = THREE_DAY_CHART_FEATURE_REGISTRY_V1
    names = tuple(spec.name for spec in registry)
    retained = tuple(names[index] for index in (0, 5, 9, 11))
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    vectors = tuple(
        ThreeDayChartFeatureVector(
            "BTCUSDT",
            start + timedelta(days=index),
            start + timedelta(days=index - 3),
            {
                name: float(
                    (index % 4) * (column + 1) * 0.2
                    + np.sin((index + 1) * (column + 2) * 0.017)
                )
                for column, name in enumerate(names)
            },
        )
        for index in range(1641)
    )
    config = RegimeModelConfig("gmm", 4, covariance_type="diag")
    fit = SklearnClusterDiagnostic().fit(
        config, vectors[:60], registry, retained_feature_names=retained
    )
    fits = {"A": fit, "B": fit}
    identity = FrozenK4InputIdentity(
        *("a" * 64 for _ in range(10)),
        split_at="2023-04-01T00:00:00Z",
        half_a_range=("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
        half_b_range=("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z"),
    )
    halves = {"A": vectors[:820], "B": vectors[820:]}
    projected = {
        label: module._project_half_centroids(
            half_means=np.asarray(fit.means),
            half_medians=np.asarray(fit.medians),
            half_scales=np.asarray(fit.scales),
            primary_lower=np.asarray(fit.lower_bounds),
            primary_upper=np.asarray(fit.upper_bounds),
            primary_medians=np.asarray(fit.medians),
            primary_scales=np.asarray(fit.scales),
        )
        for label in ("A", "B")
    }
    matches = {
        label: module._match_projected_centroids(
            np.asarray(fit.means), projected[label]
        )
        for label in ("A", "B")
    }
    maximum = max(
        distance
        for match in matches.values()
        for distance in match.pair_distances
    )
    matrix = module._scaled_matrix(fit, vectors)
    _, assignments, distances = module._gmm_assignment(fit, matrix)
    threshold = 10.0
    _, numerator, denominator, rate = module._classify_strict_ood(
        distances[np.arange(len(assignments)), assignments], threshold
    )
    attempt = {
        "model_gates": {
            "maximum_matched_centroid_distance": maximum,
            "maximum_distance_exceedance_rate": rate,
            "distance_threshold": threshold,
            "distance_threshold_policy": "maximum_chi_square_995_squared_mahalanobis",
        }
    }
    source = FrozenK4DiagnosticSource(
        attempt, fit, vectors, identity, {"runtime": "compact-test"}
    )
    pins = module._observed_stage_sha256(
        source, halves, fits, projected, matches
    )
    return source, fits, pins, maximum, rate, numerator, denominator


def _install_compact_replay(
    monkeypatch: pytest.MonkeyPatch,
    source: FrozenK4DiagnosticSource,
    fits: dict[str, object],
    pins: dict[str, str],
    maximum: float,
    rate: float,
):
    import src.application.services.frozen_k4_failure_replay as module

    calls = []

    class CountedFitter:
        def fit(self, config, vectors, registry, *, retained_feature_names):
            label = ("A", "B")[len(calls)]
            calls.append((config, len(vectors), registry, retained_feature_names))
            return fits[label]

    monkeypatch.setattr(module, "SklearnClusterDiagnostic", CountedFitter)
    monkeypatch.setattr(module, "_PINNED_STAGE_SHA256", pins)
    monkeypatch.setattr(module, "EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE", maximum)
    monkeypatch.setattr(module, "EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE", rate)
    return calls


def test_public_replay_executes_exactly_two_half_fits_and_exposes_complete_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, fits, pins, maximum, rate, numerator, denominator = _compact_case()
    calls = _install_compact_replay(monkeypatch, source, fits, pins, maximum, rate)

    result = replay_frozen_k4_failures(source)

    assert [item[1] for item in calls] == [820, 821]
    assert all(item[0] is source.primary_fit.config for item in calls)
    assert all(item[2] == THREE_DAY_CHART_FEATURE_REGISTRY_V1 for item in calls)
    assert all(item[3] == source.primary_fit.feature_names for item in calls)
    assert result.status.status == "reproduced"
    assert len(result.half_replays) == 2
    assert len(result.primary_assignments) == 1641
    assert len(result.primary_posterior_probabilities) == 1641
    assert len(result.primary_ood_rows) == 1641
    assert result.status.ood_exceedance_numerator == numerator
    assert result.status.ood_denominator == denominator
    assert all(half.precisions == half.fit.precisions for half in result.half_replays)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("vector", "input-data-mismatch"),
        ("split", "split-boundary-mismatch"),
        ("preprocessing", "preprocessing-mismatch"),
        ("dependency", "dependency-version-nondeterminism"),
        ("fit", "gmm-fitting-nondeterminism"),
        ("projection", "projection-mismatch"),
        ("matching", "matching-mismatch"),
        ("provenance", "original-metric-provenance-incomplete"),
    ),
)
def test_public_replay_classifies_each_mutated_stage_and_closes_payloads(
    monkeypatch: pytest.MonkeyPatch, mutation: str, expected: str
) -> None:
    import src.application.services.frozen_k4_failure_replay as module

    source, fits, pins, maximum, rate, _, _ = _compact_case()
    if mutation == "vector":
        changed = dict(source.vectors[10].values)
        changed[next(iter(changed))] += 0.01
        vectors = list(source.vectors)
        vectors[10] = replace(vectors[10], values=changed)
        source = replace(source, vectors=tuple(vectors))
    elif mutation == "split":
        vectors = list(source.vectors)
        vectors[400] = replace(
            vectors[400],
            anchor_at=vectors[399].anchor_at,
            window_start_at=vectors[399].window_start_at,
        )
        source = replace(source, vectors=tuple(vectors))
    elif mutation == "preprocessing":
        medians = list(source.primary_fit.medians)
        medians[0] += 0.01
        source = replace(source, primary_fit=replace(source.primary_fit, medians=tuple(medians)))
    elif mutation == "dependency":
        source = replace(source, dependency_metadata={"runtime": "changed"})
    elif mutation == "fit":
        fits = dict(fits)
        fits["B"] = replace(fits["B"], lower_bound=fits["B"].lower_bound + 0.01)
    elif mutation == "projection":
        original = module._project_half_centroids

        def changed_projection(**kwargs):
            values = original(**kwargs).copy()
            values[0, 0] += 0.01
            return values

        monkeypatch.setattr(module, "_project_half_centroids", changed_projection)
    elif mutation == "matching":
        original_match = module._match_projected_centroids

        def changed_match(primary, half):
            match = original_match(primary, half)
            costs = [list(row) for row in match.cost_matrix]
            matched_half = dict(match.assignment)[0]
            costs[0][(matched_half + 1) % len(costs)] += 0.01
            return replace(
                match, cost_matrix=tuple(tuple(row) for row in costs)
            )

        monkeypatch.setattr(module, "_match_projected_centroids", changed_match)
    else:
        attempt = {"model_gates": dict(source.attempt_payload["model_gates"])}
        attempt["model_gates"]["maximum_matched_centroid_distance"] += 0.01
        source = replace(source, attempt_payload=attempt)
    calls = _install_compact_replay(monkeypatch, source, fits, pins, maximum, rate)

    result = replay_frozen_k4_failures(source)

    assert len(calls) == 2
    assert result.status.status == "causal_reproduction_mismatch"
    assert result.status.mismatch_classification == expected
    assert len(result.status.causal_evidence_sha256) == 64
    assert result.status.decomposition_allowed is False
    if mutation == "matching":
        assert result.status.temporal_half_refit_stability_reproduction.numeric_tolerance_match
        assert result.status.primary_model_ood_reproduction.numeric_tolerance_match
    assert result.half_replays == ()
    assert result.primary_assignments == ()
    assert result.primary_posterior_probabilities == ()
    assert result.primary_ood_rows == ()


def test_public_replay_reports_earliest_stage_when_multiple_stages_mutate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.application.services.frozen_k4_failure_replay as module

    source, fits, pins, maximum, rate, _, _ = _compact_case()
    changed = dict(source.vectors[10].values)
    changed[next(iter(changed))] += 0.01
    vectors = list(source.vectors)
    vectors[10] = replace(vectors[10], values=changed)
    source = replace(source, vectors=tuple(vectors))
    original = module._project_half_centroids

    def changed_projection(**kwargs):
        values = original(**kwargs).copy()
        values[0, 0] += 0.01
        return values

    monkeypatch.setattr(module, "_project_half_centroids", changed_projection)
    _install_compact_replay(monkeypatch, source, fits, pins, maximum, rate)

    result = replay_frozen_k4_failures(source)

    assert result.status.mismatch_classification == "input-data-mismatch"


def test_public_replay_returns_terminal_and_still_attempts_both_fits_when_one_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.application.services.frozen_k4_failure_replay as module

    source, fits, pins, maximum, rate, _, _ = _compact_case()
    calls = []

    class FailingFitter:
        def fit(self, config, vectors, registry, *, retained_feature_names):
            calls.append(len(vectors))
            if len(calls) == 1:
                raise ValueError("mutated split is not chronological")
            return fits["B"]

    monkeypatch.setattr(module, "SklearnClusterDiagnostic", FailingFitter)
    monkeypatch.setattr(module, "_PINNED_STAGE_SHA256", pins)
    monkeypatch.setattr(module, "EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE", maximum)
    monkeypatch.setattr(module, "EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE", rate)

    result = replay_frozen_k4_failures(source)

    assert calls == [820, 821]
    assert result.status.status == "causal_reproduction_mismatch"
    assert result.status.mismatch_classification == "gmm-fitting-nondeterminism"
    assert result.status.temporal_half_refit_stability_reproduction is None
    assert result.status.primary_model_ood_reproduction is None
    assert result.status.ood_exceedance_numerator is None
    assert result.status.ood_denominator is None
    assert result.status.decomposition_allowed is False
    assert result.half_replays == ()
    assert result.primary_assignments == ()
    assert result.primary_posterior_probabilities == ()
    assert result.primary_ood_rows == ()
    assert result.metric_ieee_float_bits == {}


@pytest.fixture(scope="session")
def production_replay():
    root = Path(__file__).resolve().parents[3]
    source = load_frozen_k4_diagnostic_source(
        root / ".agents" / "backtest-cache" / "task9-omp1-model.json",
        root / ".research-data" / "binance-usdm" / "raw" / "klines",
    )
    return replay_frozen_k4_failures(source)


def test_real_production_replay_matches_every_pinned_receipt(production_replay) -> None:
    result = production_replay

    assert result.status.status == "reproduced"
    assert [half.receipt.anchor_count for half in result.half_replays] == [820, 821]
    assert [half.receipt.fit_sha256 for half in result.half_replays] == [
        "41d5d824a13ac5469e9145e8eecdcb99780fa7aa2184e12b1be6e378797ce888",
        "d6c7ed9414541f9de8fae09769952741b9b7b2694ad7b72064c41bdceccfef56",
    ]
    assert [half.hungarian_assignment for half in result.half_replays] == [
        ((0, 3), (1, 0), (2, 1), (3, 2)),
        ((0, 2), (1, 0), (2, 3), (3, 1)),
    ]
    assert [
        tuple(
            (
                pair.primary_component_fingerprint,
                pair.half_component_fingerprint,
                pair.euclidean_distance,
            )
            for pair in half.matched_pairs
        )
        for half in result.half_replays
    ] == [
        (
            ("39e3bacf11776871a5ff8111", "a40802651dda625eef950cfd", 0.8529894900962631),
            ("b03e2a19935047396af5f0d5", "15d3fc436752e80fbf377325", 0.7603084939869658),
            ("dddf565fe433ec33a8d07106", "3de9bb954a2c15cb4492c426", 1.1092161649469547),
            ("e37692350fa4ad4230e3336e", "5ae28957385af58ebee4cf8e", 1.9133522641135228),
        ),
        (
            ("39e3bacf11776871a5ff8111", "9511ccf67a32c14786b9505f", 1.0327644857936529),
            ("b03e2a19935047396af5f0d5", "17afd0fca04b61ad4cb40d66", 0.31333104455106625),
            ("dddf565fe433ec33a8d07106", "bb123c373acaf6526349830a", 0.9269997788282354),
            ("e37692350fa4ad4230e3336e", "79a3672f5b2e02b1cc6b62e6", 2.3526219570607076),
        ),
    ]
    assert result.status.temporal_half_refit_stability_reproduction.reproduced_value == 2.3526219570607076
    assert result.status.primary_model_ood_reproduction.reproduced_value == 0.04631322364411944
    assert result.status.ood_exceedance_numerator == 76
    assert result.status.ood_denominator == 1641
    assert result.metric_ieee_float_bits == {
        "maximum_matched_centroid_distance": ("4002d22b75eb6b05", "4002d22b75eb6b05"),
        "maximum_distance_exceedance_rate": ("3fa7b65de9d8ffd8", "3fa7b65de9d8ffd8"),
    }
    assert all(half.precisions == half.fit.precisions for half in result.half_replays)
