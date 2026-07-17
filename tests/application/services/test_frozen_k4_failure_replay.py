from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from src.application.services.frozen_k4_failure_replay import (
    EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE,
    EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE,
    _classify_strict_ood,
    _match_projected_centroids,
    _mismatch_classification,
    _project_half_centroids,
)
from src.domain.regime.frozen_k4_failure_diagnostics import MetricReproduction


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
def test_reproduction_mutations_have_distinct_terminal_classifications(
    monkeypatch: pytest.MonkeyPatch, mutation: str, expected: str
) -> None:
    import src.application.services.frozen_k4_failure_replay as module

    a_start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    split = datetime(2023, 4, 1, tzinfo=timezone.utc)
    b_end = datetime(2025, 6, 30, tzinfo=timezone.utc)
    halves = {
        "A": tuple(
            [SimpleNamespace(anchor_at=a_start)] * 819
            + [SimpleNamespace(anchor_at=split - timedelta(days=1))]
        ),
        "B": tuple(
            [SimpleNamespace(anchor_at=split)] * 820
            + [SimpleNamespace(anchor_at=b_end - timedelta(days=1))]
        ),
    }
    if mutation == "split":
        halves["A"] = halves["A"][:-1]
    gates = {
        "maximum_matched_centroid_distance": EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE,
        "maximum_distance_exceedance_rate": EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE,
        "distance_threshold_policy": "maximum_chi_square_995_squared_mahalanobis",
    }
    if mutation == "provenance":
        gates.pop("distance_threshold_policy")
    source = SimpleNamespace(
        vectors=(),
        primary_fit=object(),
        dependency_metadata={},
        attempt_payload={"model_gates": gates},
        identity=SimpleNamespace(
            feature_vectors_sha256="vectors",
            scaler_sha256="scaler",
            clipping_bounds_sha256="clipping",
            dependency_metadata_sha256="dependencies",
        ),
    )
    monkeypatch.setattr(
        module,
        "_vector_sha256",
        lambda _: "changed" if mutation == "vector" else "vectors",
    )
    monkeypatch.setattr(
        module,
        "_preprocessing_hashes",
        lambda _: (
            ("changed", "clipping")
            if mutation == "preprocessing"
            else ("scaler", "clipping")
        ),
    )
    monkeypatch.setattr(
        module,
        "_sha256",
        lambda _: "changed" if mutation == "dependency" else "dependencies",
    )
    expected_hashes = {"A": "a", "B": "b"}
    fit_hashes = dict(expected_hashes)
    if mutation == "fit":
        fit_hashes["B"] = "changed"
    temporal = MetricReproduction.compare(
        EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE,
        EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE,
    )
    ood = MetricReproduction.compare(
        EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE,
        EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE,
    )

    actual = _mismatch_classification(
        source=source,
        halves=halves,
        fit_hashes=fit_hashes,
        expected_fit_hashes=expected_hashes,
        projection_ok=mutation != "projection",
        matching_ok=mutation != "matching",
        temporal=temporal,
        ood=ood,
    )

    assert actual == expected
