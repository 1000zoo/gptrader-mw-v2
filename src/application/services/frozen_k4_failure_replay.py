"""Exact, diagnostic-only replay of the published frozen K4 gate failures.

The replay consumes an already verified source.  It neither loads data nor
creates a runtime model artifact; its two newly fitted models are receipts for
the two frozen temporal halves only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import struct
from types import MappingProxyType
from typing import Callable, Mapping

import numpy as np
from scipy.optimize import linear_sum_assignment

from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.frozen_k4_failure_diagnostics import (
    DiagnosisStatus,
    FrozenK4InputIdentity,
    HalfFitReceipt,
    MatchedPair,
    MetricReproduction,
    OODRow,
)
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    ThreeDayChartFeatureVector,
)
from src.infrastructure.regime.frozen_k4_diagnostic_source import (
    FrozenK4DiagnosticSource,
)
from src.infrastructure.regime.sklearn_cluster_diagnostic import (
    SklearnClusterDiagnostic,
)


EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE = 2.3526219570607076
EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE = 0.04631322364411944
_SPLIT_AT = datetime(2023, 4, 1, tzinfo=timezone.utc)
_HALF_RANGES = {
    "A": (datetime(2021, 1, 1, tzinfo=timezone.utc), _SPLIT_AT),
    "B": (_SPLIT_AT, datetime(2025, 6, 30, tzinfo=timezone.utc)),
}
_HALF_COUNTS = {"A": 820, "B": 821}
_FROZEN_HALF_FIT_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "A": "784383b2a4d3325bf0c1fd763111cb9342d1830203db33da1143c58c316e68bf",
        "B": "d4993ce76ac54d46bdb71f7f39245ec52ef995851b13e85d16369a22c795a6a4",
    }
)


@dataclass(frozen=True)
class CentroidMatch:
    cost_matrix: tuple[tuple[float, ...], ...]
    assignment: tuple[tuple[int, int], ...]
    pair_distances: tuple[float, ...]


@dataclass(frozen=True)
class FrozenK4HalfReplay:
    receipt: HalfFitReceipt
    fit: ClusterDiagnosticFit
    assignments: tuple[int, ...]
    posterior_probabilities: tuple[tuple[float, ...], ...]
    projected_centroids: tuple[tuple[float, ...], ...]
    projected_covariances: tuple[tuple[float, ...], ...]
    precisions: tuple[tuple[float, ...], ...]
    precisions_cholesky: tuple[tuple[float, ...], ...]
    cost_matrix: tuple[tuple[float, ...], ...]
    hungarian_assignment: tuple[tuple[int, int], ...]
    matched_pairs: tuple[MatchedPair, ...]
    pair_euclidean_distances: tuple[float, ...]
    component_weights: tuple[float, ...]
    diagnostic_only: bool = True
    primary_replacement_allowed: bool = False


@dataclass(frozen=True)
class FrozenK4Replay:
    input_identity: FrozenK4InputIdentity
    dependency_metadata: Mapping[str, object]
    status: DiagnosisStatus
    half_replays: tuple[FrozenK4HalfReplay, ...] = ()
    primary_assignments: tuple[int, ...] = ()
    primary_posterior_probabilities: tuple[tuple[float, ...], ...] = ()
    primary_ood_rows: tuple[OODRow, ...] = ()
    metric_ieee_float_bits: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    diagnostic_only: bool = True
    primary_replacement_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "dependency_metadata", _deep_freeze(self.dependency_metadata))
        bits = dict(self.metric_ieee_float_bits)
        object.__setattr__(self, "metric_ieee_float_bits", MappingProxyType(bits))
        if self.status.status == "reproduction_mismatch" and (
            self.half_replays
            or self.primary_assignments
            or self.primary_posterior_probabilities
            or self.primary_ood_rows
        ):
            raise ValueError("terminal mismatch replay cannot expose decomposition payloads")


@dataclass(frozen=True)
class _ReplaySeams:
    fitter: object | None = None
    projector: Callable[..., np.ndarray] | None = None
    matcher: Callable[[np.ndarray, np.ndarray], CentroidMatch] | None = None
    expected_half_fit_sha256: Mapping[str, str] | None = None


def replay_frozen_k4_failures(source: FrozenK4DiagnosticSource) -> FrozenK4Replay:
    """Replay the two frozen failures without refitting the primary model."""
    return _replay_frozen_k4_failures(source, _ReplaySeams())


def _replay_frozen_k4_failures(
    source: FrozenK4DiagnosticSource,
    seams: _ReplaySeams,
) -> FrozenK4Replay:
    if not isinstance(source, FrozenK4DiagnosticSource):
        raise ValueError("replay source must be a frozen K4 diagnostic source")
    primary = source.primary_fit
    halves = {
        label: tuple(
            vector for vector in source.vectors if start <= vector.anchor_at < end
        )
        for label, (start, end) in _HALF_RANGES.items()
    }

    # Exactly two calls through the low-level diagnostic fitter.  There is no
    # primary refit and no sensitivity/subsampling fit.
    fitter = seams.fitter or SklearnClusterDiagnostic()
    fits = {
        label: fitter.fit(
            primary.config,
            halves[label],
            THREE_DAY_CHART_FEATURE_REGISTRY_V1,
            retained_feature_names=primary.feature_names,
        )
        for label in ("A", "B")
    }

    projector = seams.projector or _project_half_centroids
    matcher = seams.matcher or _match_projected_centroids
    primary_means = np.asarray(primary.means, dtype=float)
    detailed_halves: list[FrozenK4HalfReplay] = []
    projection_ok = True
    matching_ok = True
    maximum_distance = 0.0
    fit_hashes: dict[str, str] = {}

    for label in ("A", "B"):
        fit = fits[label]
        fit_hash = _fit_sha256(fit)
        fit_hashes[label] = fit_hash
        projection_arguments = dict(
            half_means=np.asarray(fit.means, dtype=float),
            half_medians=np.asarray(fit.medians, dtype=float),
            half_scales=np.asarray(fit.scales, dtype=float),
            primary_lower=np.asarray(primary.lower_bounds, dtype=float),
            primary_upper=np.asarray(primary.upper_bounds, dtype=float),
            primary_medians=np.asarray(primary.medians, dtype=float),
            primary_scales=np.asarray(primary.scales, dtype=float),
        )
        projected = np.asarray(projector(**projection_arguments), dtype=float)
        reference_projection = _project_half_centroids(**projection_arguments)
        projection_ok &= np.array_equal(projected, reference_projection)
        matched = matcher(primary_means, projected)
        reference_match = _match_projected_centroids(primary_means, projected)
        matching_ok &= matched == reference_match
        maximum_distance = max(maximum_distance, *matched.pair_distances)

        matrix = _scaled_matrix(fit, halves[label])
        probabilities, assignments, _ = _gmm_assignment(fit, matrix)
        projected_covariances = (
            np.asarray(fit.covariances, dtype=float)
            * np.square(np.asarray(fit.scales, dtype=float))[None, :]
            / np.square(np.asarray(primary.scales, dtype=float))[None, :]
        )
        covariances = np.asarray(fit.covariances, dtype=float)
        precisions = 1.0 / covariances
        precisions_cholesky = 1.0 / np.sqrt(covariances)
        pairs = tuple(
            MatchedPair(
                label,
                primary.fingerprints[primary_index],
                fit.fingerprints[half_index],
                primary_index,
                half_index,
                matched.cost_matrix[primary_index][half_index],
                distance,
            )
            for (primary_index, half_index), distance in zip(
                matched.assignment, matched.pair_distances
            )
        )
        if len(halves[label]) == _HALF_COUNTS[label]:
            detailed_halves.append(
                FrozenK4HalfReplay(
                    receipt=HalfFitReceipt(label, len(halves[label]), fit_hash),
                    fit=fit,
                    assignments=tuple(int(value) for value in assignments),
                    posterior_probabilities=_matrix_tuple(probabilities),
                    projected_centroids=_matrix_tuple(projected),
                    projected_covariances=_matrix_tuple(projected_covariances),
                    precisions=_matrix_tuple(precisions),
                    precisions_cholesky=_matrix_tuple(precisions_cholesky),
                    cost_matrix=matched.cost_matrix,
                    hungarian_assignment=matched.assignment,
                    matched_pairs=pairs,
                    pair_euclidean_distances=matched.pair_distances,
                    component_weights=fit.weights,
                )
            )

    primary_matrix = _scaled_matrix(primary, source.vectors)
    primary_probabilities, primary_assignments, all_distances = _gmm_assignment(
        primary, primary_matrix
    )
    assigned_distances = all_distances[
        np.arange(len(primary_assignments)), primary_assignments
    ]
    threshold = float(source.attempt_payload["model_gates"]["distance_threshold"])
    flags, numerator, denominator, ood_rate = _classify_strict_ood(
        assigned_distances, threshold
    )
    ood_rows = tuple(
        OODRow.classify(
            anchor_at=_canonical_timestamp(vector.anchor_at),
            assigned_component_index=int(component),
            assigned_component_fingerprint=primary.fingerprints[int(component)],
            squared_mahalanobis=float(distance),
            threshold=threshold,
        )
        for vector, component, distance in zip(
            source.vectors, primary_assignments, assigned_distances
        )
    )
    assert tuple(row.exceeds for row in ood_rows) == tuple(bool(value) for value in flags)

    temporal_receipt = MetricReproduction.compare(
        EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE, maximum_distance
    )
    ood_receipt = MetricReproduction.compare(
        EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE, ood_rate
    )
    classification = _mismatch_classification(
        source=source,
        halves=halves,
        fit_hashes=fit_hashes,
        expected_fit_hashes=seams.expected_half_fit_sha256 or _FROZEN_HALF_FIT_SHA256,
        projection_ok=projection_ok,
        matching_ok=matching_ok,
        temporal=temporal_receipt,
        ood=ood_receipt,
    )
    if classification is not None:
        status = DiagnosisStatus.mismatch(
            temporal_receipt, ood_receipt, numerator, denominator, classification
        )
        return FrozenK4Replay(
            source.identity, source.dependency_metadata, status,
            metric_ieee_float_bits=_metric_bits(temporal_receipt, ood_receipt),
        )

    status = DiagnosisStatus.reproduced(
        temporal_receipt, ood_receipt, numerator, denominator
    )
    return FrozenK4Replay(
        source.identity,
        source.dependency_metadata,
        status,
        tuple(detailed_halves),
        tuple(int(value) for value in primary_assignments),
        _matrix_tuple(primary_probabilities),
        ood_rows,
        _metric_bits(temporal_receipt, ood_receipt),
    )


def _project_half_centroids(
    *,
    half_means: np.ndarray,
    half_medians: np.ndarray,
    half_scales: np.ndarray,
    primary_lower: np.ndarray,
    primary_upper: np.ndarray,
    primary_medians: np.ndarray,
    primary_scales: np.ndarray,
) -> np.ndarray:
    raw = np.asarray(half_means, dtype=float) * half_scales + half_medians
    clipped = np.clip(raw, primary_lower, primary_upper)
    return (clipped - primary_medians) / primary_scales


def _match_projected_centroids(
    primary_centroids: np.ndarray,
    projected_half_centroids: np.ndarray,
) -> CentroidMatch:
    primary = np.asarray(primary_centroids, dtype=float)
    half = np.asarray(projected_half_centroids, dtype=float)
    costs = np.linalg.norm(primary[:, None, :] - half[None, :, :], axis=2)
    primary_indices, half_indices = linear_sum_assignment(costs)
    assignment = tuple(
        (int(primary_index), int(half_index))
        for primary_index, half_index in zip(primary_indices, half_indices)
    )
    return CentroidMatch(
        _matrix_tuple(costs),
        assignment,
        tuple(float(costs[p, h]) for p, h in assignment),
    )


def _classify_strict_ood(
    squared_distances: np.ndarray, threshold: float
) -> tuple[np.ndarray, int, int, float]:
    flags = np.asarray(squared_distances, dtype=float) > float(threshold)
    numerator = int(np.count_nonzero(flags))
    denominator = int(flags.size)
    return flags, numerator, denominator, numerator / denominator


def _gmm_assignment(
    fit: ClusterDiagnosticFit, matrix: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    means = np.asarray(fit.means, dtype=float)
    covariances = np.asarray(fit.covariances, dtype=float)
    delta = matrix[:, None, :] - means[None, :, :]
    distances = np.sum(delta * delta / covariances[None, :, :], axis=2)
    dimensions = matrix.shape[1]
    log_probabilities = (
        np.log(np.asarray(fit.weights, dtype=float))[None, :]
        - 0.5
        * (
            dimensions * math.log(2.0 * math.pi)
            + np.log(covariances).sum(axis=1)[None, :]
            + distances
        )
    )
    maxima = np.max(log_probabilities, axis=1, keepdims=True)
    exponentials = np.exp(log_probabilities - maxima)
    probabilities = exponentials / exponentials.sum(axis=1, keepdims=True)
    assignments = np.argmax(probabilities, axis=1)
    return probabilities, assignments, distances


def _scaled_matrix(
    fit: ClusterDiagnosticFit,
    vectors: tuple[ThreeDayChartFeatureVector, ...],
) -> np.ndarray:
    registry_names = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    indices = tuple(registry_names.index(name) for name in fit.feature_names)
    raw = np.asarray([tuple(vector.values.values()) for vector in vectors], dtype=float)
    selected = raw[:, indices]
    clipped = np.clip(selected, fit.lower_bounds, fit.upper_bounds)
    return (clipped - np.asarray(fit.medians)) / np.asarray(fit.scales)


def _mismatch_classification(
    *,
    source: FrozenK4DiagnosticSource,
    halves: Mapping[str, tuple[ThreeDayChartFeatureVector, ...]],
    fit_hashes: Mapping[str, str],
    expected_fit_hashes: Mapping[str, str],
    projection_ok: bool,
    matching_ok: bool,
    temporal: MetricReproduction,
    ood: MetricReproduction,
) -> str | None:
    if _vector_sha256(source.vectors) != source.identity.feature_vectors_sha256:
        return "input-data-mismatch"
    if any(
        len(halves[label]) != _HALF_COUNTS[label]
        or not halves[label]
        or halves[label][0].anchor_at != _HALF_RANGES[label][0]
        or halves[label][-1].anchor_at != _HALF_RANGES[label][1] - timedelta(days=1)
        for label in ("A", "B")
    ):
        return "split-boundary-mismatch"
    scaler_hash, clipping_hash = _preprocessing_hashes(source.primary_fit)
    if (
        scaler_hash != source.identity.scaler_sha256
        or clipping_hash != source.identity.clipping_bounds_sha256
    ):
        return "preprocessing-mismatch"
    if _sha256(_thaw(source.dependency_metadata)) != source.identity.dependency_metadata_sha256:
        return "dependency-version-nondeterminism"
    if any(fit_hashes.get(label) != expected_fit_hashes.get(label) for label in ("A", "B")):
        return "gmm-fitting-nondeterminism"
    if not projection_ok:
        return "projection-mismatch"
    if not matching_ok:
        return "matching-mismatch"
    if not _original_metric_provenance_complete(source):
        return "original-metric-provenance-incomplete"
    if not temporal.numeric_tolerance_match or not ood.numeric_tolerance_match:
        return "original-metric-provenance-incomplete"
    return None


def _original_metric_provenance_complete(source: FrozenK4DiagnosticSource) -> bool:
    try:
        gates = source.attempt_payload["model_gates"]
        return (
            gates["maximum_matched_centroid_distance"]
            == EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE
            and gates["maximum_distance_exceedance_rate"]
            == EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE
            and gates["distance_threshold_policy"]
            == "maximum_chi_square_995_squared_mahalanobis"
        )
    except (KeyError, TypeError):
        return False


def _fit_sha256(fit: ClusterDiagnosticFit) -> str:
    return _sha256({
        "schema_version": fit.schema_version,
        "symbol": fit.symbol,
        "config": {
            "model_type": fit.config.model_type,
            "cluster_count": fit.config.cluster_count,
            "random_seed": fit.config.random_seed,
            "covariance_type": fit.config.covariance_type,
            "regularization": fit.config.regularization,
        },
        "feature_names": list(fit.feature_names),
        "lower_bounds": list(fit.lower_bounds),
        "upper_bounds": list(fit.upper_bounds),
        "medians": list(fit.medians),
        "scales": list(fit.scales),
        "fingerprints": list(fit.fingerprints),
        "means": [list(row) for row in fit.means],
        "weights": list(fit.weights),
        "covariances": [list(row) for row in fit.covariances],
        "converged": fit.converged,
        "iterations": fit.iterations,
        "lower_bound": fit.lower_bound,
    })


def _vector_sha256(vectors: tuple[ThreeDayChartFeatureVector, ...]) -> str:
    return _sha256({
        "schema_version": vectors[0].schema_version if vectors else None,
        "registry_names": [spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1],
        "vectors": [
            {
                "symbol": vector.symbol,
                "anchor_at": vector.anchor_at.isoformat(),
                "window_start_at": vector.window_start_at.isoformat(),
                "values": list(vector.values.items()),
            }
            for vector in vectors
        ],
    })


def _preprocessing_hashes(fit: ClusterDiagnosticFit) -> tuple[str, str]:
    clipping = {
        "lower_bounds": list(fit.lower_bounds),
        "upper_bounds": list(fit.upper_bounds),
    }
    scaler = {
        "feature_names": list(fit.feature_names),
        "scaler": {"medians": list(fit.medians), "scales": list(fit.scales)},
        "clipping": clipping,
    }
    return _sha256(scaler), _sha256(clipping)


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _matrix_tuple(values: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in np.asarray(values))


def _canonical_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _metric_bits(
    temporal: MetricReproduction, ood: MetricReproduction
) -> Mapping[str, tuple[str, str]]:
    return {
        "maximum_matched_centroid_distance": (
            struct.pack(">d", temporal.expected_value).hex(),
            struct.pack(">d", temporal.reproduced_value).hex(),
        ),
        "maximum_distance_exceedance_rate": (
            struct.pack(">d", ood.expected_value).hex(),
            struct.pack(">d", ood.reproduced_value).hex(),
        ),
    }


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


__all__ = [
    "EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE",
    "EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE",
    "FrozenK4HalfReplay",
    "FrozenK4Replay",
    "replay_frozen_k4_failures",
]
