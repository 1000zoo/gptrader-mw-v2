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
_STAGE_ORDER = (
    "input",
    "split",
    "preprocessing",
    "dependency",
    "fit_a",
    "fit_b",
    "projection",
    "matching",
    "metric_provenance",
)
_STAGE_CLASSIFICATION = MappingProxyType({
    "input": "input-data-mismatch",
    "split": "split-boundary-mismatch",
    "preprocessing": "preprocessing-mismatch",
    "dependency": "dependency-version-nondeterminism",
    "fit_a": "gmm-fitting-nondeterminism",
    "fit_b": "gmm-fitting-nondeterminism",
    "projection": "projection-mismatch",
    "matching": "matching-mismatch",
    "metric_provenance": "original-metric-provenance-incomplete",
})
# Diagnostic-only receipts pinned from the verified local production replay.
_PINNED_STAGE_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "input": "1618860cffdc7808825a09070cf6820f70ce5a0ad89b1b5028270105a91540ac",
        "split": "3650eae7ea692826d4d76472571a2e6ab7e3b183b74a1b4930347d8c4a279598",
        "preprocessing": "d7085939f4ea2b56962745045a97f4753ad4c7fdf305657002b6a514418c19ad",
        "dependency": "c22138a9988945d686bdaa961c9f3a1580d0241244c62884310e156ed729f863",
        "fit_a": "41d5d824a13ac5469e9145e8eecdcb99780fa7aa2184e12b1be6e378797ce888",
        "fit_b": "d6c7ed9414541f9de8fae09769952741b9b7b2694ad7b72064c41bdceccfef56",
        "projection": "310dd7f6a9abda6c74727d302f995ae2121c2e366748bb62220d2b57e3691656",
        "matching": "cc3e6aba32ce09c8ffdc2aa1dd82e75767a4eb9eee00a9ff87728fa664e5acf0",
        "metric_provenance": "45bccfd26f8d06adb37f3589c44da79ad5218b0d2a003ace033faf617307f53b",
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
        if self.status.status != "reproduced" and (
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
    fits: dict[str, ClusterDiagnosticFit] = {}
    fit_errors: dict[str, Exception] = {}
    for label in ("A", "B"):
        try:
            fits[label] = fitter.fit(
                primary.config,
                halves[label],
                THREE_DAY_CHART_FEATURE_REGISTRY_V1,
                retained_feature_names=primary.feature_names,
            )
        except Exception as error:  # terminal diagnostic receipt, never a retry
            fit_errors[label] = error
    if fit_errors:
        return _terminal_fit_error_replay(source, fit_errors)

    projector = seams.projector or _project_half_centroids
    matcher = seams.matcher or _match_projected_centroids
    primary_means = np.asarray(primary.means, dtype=float)
    detailed_halves: list[FrozenK4HalfReplay] = []
    maximum_distance = 0.0
    fit_hashes: dict[str, str] = {}
    projected_by_half: dict[str, np.ndarray] = {}
    matches_by_half: dict[str, CentroidMatch] = {}

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
        matched = matcher(primary_means, projected)
        projected_by_half[label] = projected
        matches_by_half[label] = matched
        maximum_distance = max(maximum_distance, *matched.pair_distances)

        matrix = _scaled_matrix(fit, halves[label])
        probabilities, assignments, _ = _gmm_assignment(fit, matrix)
        projected_covariances = (
            np.asarray(fit.covariances, dtype=float)
            * np.square(np.asarray(fit.scales, dtype=float))[None, :]
            / np.square(np.asarray(primary.scales, dtype=float))[None, :]
        )
        precisions = np.asarray(fit.precisions, dtype=float)
        precisions_cholesky = np.asarray(fit.precisions_cholesky, dtype=float)
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
    observed_stages = _observed_stage_sha256(
        source, halves, fits, projected_by_half, matches_by_half
    )
    pinned_stages = dict(_PINNED_STAGE_SHA256)
    if seams.expected_half_fit_sha256 is not None:
        pinned_stages["fit_a"] = seams.expected_half_fit_sha256["A"]
        pinned_stages["fit_b"] = seams.expected_half_fit_sha256["B"]
    classification, causal_evidence = _classify_stage_mismatch(
        observed_stages, pinned_stages, temporal_receipt, ood_receipt
    )
    if classification is not None:
        status = DiagnosisStatus.causal_mismatch(
            temporal_receipt,
            ood_receipt,
            numerator,
            denominator,
            classification,
            causal_evidence,
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


def _classify_stage_mismatch(
    observed: Mapping[str, str],
    pinned: Mapping[str, str],
    temporal: MetricReproduction,
    ood: MetricReproduction,
) -> tuple[str | None, str]:
    for stage in _STAGE_ORDER:
        if observed.get(stage) != pinned.get(stage):
            evidence = _sha256({
                "stage": stage,
                "expected_sha256": pinned.get(stage),
                "observed_sha256": observed.get(stage),
            })
            return _STAGE_CLASSIFICATION[stage], evidence
    if not temporal.numeric_tolerance_match or not ood.numeric_tolerance_match:
        evidence = _sha256({
            "stage": "metric_reproduction",
            "temporal": temporal.canonical_payload(),
            "ood": ood.canonical_payload(),
        })
        return "original-metric-provenance-incomplete", evidence
    return None, ""


def _terminal_fit_error_replay(
    source: FrozenK4DiagnosticSource,
    errors: Mapping[str, Exception],
) -> FrozenK4Replay:
    observed_prefit = {
        "input": _input_data_sha256(source.vectors),
        "split": _sha256(_split_payload(source)),
        "dependency": _sha256(_dependency_stage_payload(source.dependency_metadata)),
    }
    stage = next(
        (
            name
            for name in ("input", "split", "dependency")
            if observed_prefit[name] != _PINNED_STAGE_SHA256[name]
        ),
        "fit_a" if "A" in errors else "fit_b",
    )
    evidence = _sha256({
        "stage": stage,
        "expected_sha256": _PINNED_STAGE_SHA256[stage],
        "observed_sha256": observed_prefit.get(stage),
        "fit_errors": {
            label: {"type": type(error).__name__, "message": str(error)}
            for label, error in sorted(errors.items())
        },
    })
    status = DiagnosisStatus.causal_mismatch_unavailable(
        _STAGE_CLASSIFICATION[stage],
        evidence,
    )
    return FrozenK4Replay(
        source.identity,
        source.dependency_metadata,
        status,
    )


def _observed_stage_sha256(
    source: FrozenK4DiagnosticSource,
    halves: Mapping[str, tuple[ThreeDayChartFeatureVector, ...]],
    fits: Mapping[str, ClusterDiagnosticFit],
    projected: Mapping[str, np.ndarray],
    matches: Mapping[str, CentroidMatch],
) -> dict[str, str]:
    primary = source.primary_fit
    return {
        "input": _input_data_sha256(source.vectors),
        "split": _sha256(_split_payload(source, halves)),
        "preprocessing": _sha256({
            "primary": _preprocessing_payload(primary),
            "halves": {
                label: {
                    "raw_selected_vectors": _raw_selected_values(fits[label], halves[label]),
                    "preprocessing": _preprocessing_payload(fits[label]),
                }
                for label in ("A", "B")
            },
        }),
        "dependency": _sha256(_dependency_stage_payload(source.dependency_metadata)),
        "fit_a": _fit_sha256(fits["A"]),
        "fit_b": _fit_sha256(fits["B"]),
        "projection": _sha256({
            label: _matrix_tuple(projected[label]) for label in ("A", "B")
        }),
        "matching": _sha256({
            label: {
                "cost_matrix": matches[label].cost_matrix,
                "assignment": matches[label].assignment,
                "pair_distances": matches[label].pair_distances,
            }
            for label in ("A", "B")
        }),
        "metric_provenance": _sha256(_metric_provenance_payload(source)),
    }


def _split_payload(
    source: FrozenK4DiagnosticSource,
    halves: Mapping[str, tuple[ThreeDayChartFeatureVector, ...]] | None = None,
) -> dict[str, object]:
    if halves is None:
        halves = {
            label: tuple(
                vector
                for vector in source.vectors
                if start <= vector.anchor_at < end
            )
            for label, (start, end) in _HALF_RANGES.items()
        }
    return {
        "split_at": source.identity.split_at,
        "half_a_range": list(source.identity.half_a_range),
        "half_b_range": list(source.identity.half_b_range),
        "counts": {label: len(halves[label]) for label in ("A", "B")},
        "ordered_anchors": [
            _canonical_timestamp(vector.anchor_at) for vector in source.vectors
        ],
    }


def _validate_exact_split(source: FrozenK4DiagnosticSource) -> bool:
    identity = source.identity
    if (
        identity.split_at != "2023-04-01T00:00:00Z"
        or identity.half_a_range
        != ("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z")
        or identity.half_b_range
        != ("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z")
        or len(source.vectors) != 1641
    ):
        return False
    expected = datetime(2021, 1, 1, tzinfo=timezone.utc)
    for vector in source.vectors:
        if vector.anchor_at != expected:
            return False
        expected += timedelta(days=1)
    return expected == datetime(2025, 6, 30, tzinfo=timezone.utc)


def _metric_provenance_payload(source: FrozenK4DiagnosticSource) -> object:
    try:
        gates = source.attempt_payload["model_gates"]
        return {
            "maximum_matched_centroid_distance": gates[
                "maximum_matched_centroid_distance"
            ],
            "maximum_distance_exceedance_rate": gates[
                "maximum_distance_exceedance_rate"
            ],
            "distance_threshold": gates["distance_threshold"],
            "distance_threshold_policy": gates["distance_threshold_policy"],
        }
    except (KeyError, TypeError):
        return {"incomplete": True}


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
        "precisions": [list(row) for row in fit.precisions],
        "precisions_cholesky": [list(row) for row in fit.precisions_cholesky],
    })


def _input_data_sha256(vectors: tuple[ThreeDayChartFeatureVector, ...]) -> str:
    """Hash numeric source data separately from temporal split membership."""
    return _sha256({
        "schema_version": vectors[0].schema_version if vectors else None,
        "registry_names": [spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1],
        "vectors": [
            {
                "symbol": vector.symbol,
                "values": list(vector.values.items()),
            }
            for vector in vectors
        ],
    })


def _preprocessing_payload(fit: ClusterDiagnosticFit) -> dict[str, object]:
    return {
        "feature_names": list(fit.feature_names),
        "lower_bounds": list(fit.lower_bounds),
        "upper_bounds": list(fit.upper_bounds),
        "medians": list(fit.medians),
        "scales": list(fit.scales),
    }


def _raw_selected_values(
    fit: ClusterDiagnosticFit,
    vectors: tuple[ThreeDayChartFeatureVector, ...],
) -> list[list[float]]:
    registry_names = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    indices = tuple(registry_names.index(name) for name in fit.feature_names)
    return [
        [float(tuple(vector.values.values())[index]) for index in indices]
        for vector in vectors
    ]


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dependency_stage_payload(metadata: Mapping[str, object]) -> object:
    payload = _thaw(metadata)
    if not isinstance(payload, dict):
        raise ValueError("dependency metadata must be a mapping")
    return {
        key: value
        for key, value in sorted(payload.items())
        if key != "thread_environment"
    }


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
