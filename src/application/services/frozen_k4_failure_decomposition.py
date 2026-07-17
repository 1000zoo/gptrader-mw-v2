"""Pure decomposition of the reproduced frozen K4 diagnostic failures."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from src.application.services.frozen_k4_failure_replay import FrozenK4Replay
from src.domain.regime.frozen_k4_failure_diagnostics import SensitivityRow

_ASSIGNMENT_SOURCE = "frozen_reproduced_half_assignment"
_VARIANCE_FLOOR = 1e-6
_MAPPING_BOUNDARY = datetime(2025, 6, 30, tzinfo=timezone.utc)
_FORBIDDEN_TERMS = frozenset(
    ("strategy", "mapping", "validation", "evidence", "test")
)


@dataclass(frozen=True)
class FeatureContributionRow:
    half_label: str
    primary_component_index: int
    half_component_index: int
    feature_name: str
    squared_distance: float
    contribution_ratio: float


@dataclass(frozen=True)
class LocationDistanceRow:
    half_label: str
    primary_component_index: int
    half_component_index: int
    statistic: str
    centroid_distance: float
    assignment_source: str = _ASSIGNMENT_SOURCE
    refit_after_exclusion: bool = False
    diagnostic_only: bool = True


@dataclass(frozen=True)
class ClippedSampleRow:
    anchor_at: str
    half_label: str
    feature_name: str
    direction: str
    raw_value: float
    clipped_value: float


@dataclass(frozen=True)
class PooledMahalanobisRow:
    half_label: str
    primary_component_index: int
    half_component_index: int
    squared_distance: float
    feature_contributions: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "feature_contributions",
            MappingProxyType(dict(self.feature_contributions)),
        )


@dataclass(frozen=True)
class ComponentDistanceRow:
    half_label: str
    primary_component_index: int
    half_component_index: int
    metric: str
    distance: float


@dataclass(frozen=True)
class OODComponentRow:
    component_index: int
    component_fingerprint: str
    sample_count: int
    exceedance_count: int
    exceedance_rate: float


@dataclass(frozen=True)
class OODSampleContributionRow:
    anchor_at: str
    component_index: int
    component_fingerprint: str
    squared_mahalanobis: float
    threshold: float
    feature_contributions: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "feature_contributions",
            MappingProxyType(dict(self.feature_contributions)),
        )


@dataclass(frozen=True)
class ClusterSummaryRow:
    half_label: str
    primary_component_index: int
    half_component_index: int
    primary_component_fingerprint: str
    half_component_fingerprint: str
    sample_count: int
    exceedance_count: int
    euclidean_distance: float
    top_drift_features: tuple[str, ...]
    diagnostic_only: bool = True


@dataclass(frozen=True)
class CauseClassification:
    causes: tuple[str, ...]
    signals: Mapping[str, float | str] = field(repr=False)
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals", MappingProxyType(dict(self.signals)))


@dataclass(frozen=True)
class OffsetSubsampleRow:
    spacing_days: int
    offset: int
    sample_count: int
    component_counts: Mapping[int, int]
    assignment_source: str = _ASSIGNMENT_SOURCE
    refit_after_exclusion: bool = False
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_counts",
            MappingProxyType(dict(self.component_counts)),
        )


@dataclass(frozen=True)
class FrozenK4Decomposition:
    cluster_summaries: tuple[ClusterSummaryRow, ...]
    cause_classification: CauseClassification
    feature_contributions: tuple[FeatureContributionRow, ...]
    top_drift_features: Mapping[tuple[str, int], tuple[str, ...]]
    location_distances: tuple[LocationDistanceRow, ...]
    clipped_samples: tuple[ClippedSampleRow, ...]
    exclusion_sensitivity: tuple[SensitivityRow, ...]
    pooled_mahalanobis: tuple[PooledMahalanobisRow, ...]
    component_distances: tuple[ComponentDistanceRow, ...]
    ood_by_component: tuple[OODComponentRow, ...]
    ood_samples: tuple[OODSampleContributionRow, ...]
    offset_subsamples: tuple[OffsetSubsampleRow, ...]
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "top_drift_features",
            MappingProxyType(dict(self.top_drift_features)),
        )


def decompose_frozen_k4_failure(
    replay: FrozenK4Replay,
    primary_fit: object,
    vectors: Sequence[object],
    *,
    source_context: object | None = None,
) -> FrozenK4Decomposition:
    if not isinstance(replay, FrozenK4Replay):
        raise ValueError("decomposition requires a FrozenK4Replay")
    if not isinstance(vectors, tuple):
        raise ValueError("decomposition requires immutable input vectors")
    _isolation_guard(primary_fit, "primary_fit")
    _isolation_guard(vectors, "vectors")
    _isolation_guard(source_context, "source_context")

    status = getattr(replay, "status", None)
    if (
        getattr(status, "status", None) != "reproduced"
        or getattr(status, "decomposition_allowed", None) is not True
    ):
        raise ValueError("decomposition requires reproduced replay")
    _validate_replay_lengths(replay, vectors)

    feature_names = tuple(primary_fit.feature_names)
    raw = _raw_matrix(vectors, feature_names)
    primary_clipped = _clip_and_scale(raw, primary_fit)
    primary_assignments = np.asarray(tuple(replay.primary_assignments), dtype=int)

    feature_rows: list[FeatureContributionRow] = []
    summary_rows: list[ClusterSummaryRow] = []
    location_rows: list[LocationDistanceRow] = []
    clipped_rows: list[ClippedSampleRow] = []
    sensitivity_rows: list[SensitivityRow] = []
    pooled_rows: list[PooledMahalanobisRow] = []
    component_distance_rows: list[ComponentDistanceRow] = []

    for half in replay.half_replays:
        half_label = half.receipt.half_label
        half_fit = half.fit
        half_raw = _raw_matrix(vectors, tuple(half_fit.feature_names))
        half_clipped = _clip_and_scale(half_raw, half_fit)
        clipped_rows.extend(_clipped_rows(half_label, vectors, half_fit, half_raw))
        half_assignments = np.asarray(tuple(half.assignments), dtype=int)

        for pair in half.matched_pairs:
            primary_index = int(pair.primary_component_index)
            half_index = int(pair.half_component_index)
            primary_mean = np.asarray(primary_fit.means[primary_index], dtype=float)
            half_mean = np.asarray(half.projected_centroids[half_index], dtype=float)
            delta = half_mean - primary_mean
            squared = delta * delta
            total = float(squared.sum())
            ordered = sorted(
                zip(feature_names, squared),
                key=lambda item: (-float(item[1]), item[0]),
            )
            for name, value in ordered:
                feature_rows.append(
                    FeatureContributionRow(
                        half_label,
                        primary_index,
                        half_index,
                        name,
                        float(value),
                        0.0 if total == 0.0 else float(value) / total,
                    )
                )

            member_mask = half_assignments == half_index
            members = half_clipped[member_mask]
            anchors = [
                vector.anchor_at
                for keep, vector in zip(member_mask, vectors)
                if keep
            ]
            location_rows.extend(
                _location_rows(
                    half_label, primary_index, half_index, primary_mean, members
                )
            )
            sensitivity_rows.extend(
                _exclusion_rows(
                    half_label,
                    pair.primary_component_fingerprint,
                    primary_mean,
                    members,
                    anchors,
                )
            )
            pooled_rows.append(
                _pooled_mahalanobis_row(
                    half_label,
                    primary_index,
                    half_index,
                    feature_names,
                    primary_mean,
                    half_mean,
                    np.asarray(primary_fit.covariances[primary_index], dtype=float),
                    members,
                )
            )
            component_distance_rows.extend(
                _component_distance_rows(
                    half_label,
                    primary_index,
                    half_index,
                    primary_mean,
                    half_mean,
                    np.asarray(primary_fit.covariances[primary_index], dtype=float),
                    np.asarray(half.projected_covariances[half_index], dtype=float),
                )
            )
            exceeded = sum(
                1
                for row in replay.primary_ood_rows
                if int(row.assigned_component_index) == primary_index and row.exceeds
            )
            summary_rows.append(
                ClusterSummaryRow(
                    half_label,
                    primary_index,
                    half_index,
                    pair.primary_component_fingerprint,
                    pair.half_component_fingerprint,
                    int(np.count_nonzero(member_mask)),
                    exceeded,
                    float(pair.euclidean_distance),
                    tuple(name for name, _ in ordered[:5]),
                )
            )

    ood_by_component, ood_samples = _ood_rows(
        replay, primary_fit, feature_names, primary_clipped, primary_assignments
    )
    offsets = _offset_rows(primary_assignments)
    top = _top_features(feature_rows)
    result = FrozenK4Decomposition(
        tuple(summary_rows),
        _classify_causes(
            tuple(summary_rows),
            tuple(feature_rows),
            tuple(location_rows),
            tuple(pooled_rows),
            tuple(ood_by_component),
        ),
        tuple(feature_rows),
        top,
        tuple(location_rows),
        tuple(sorted(clipped_rows, key=lambda row: (row.anchor_at, row.feature_name))),
        tuple(sensitivity_rows),
        tuple(pooled_rows),
        tuple(component_distance_rows),
        tuple(ood_by_component),
        tuple(ood_samples),
        tuple(offsets),
    )
    _isolation_guard(result, "decomposition_result")
    return result


def _isolation_guard(value: object, path: str) -> None:
    if value is None:
        return
    if isinstance(value, datetime):
        parsed = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if parsed >= _MAPPING_BOUNDARY:
            raise ValueError(f"isolation guard rejected date at {path}")
        return
    if isinstance(value, str):
        lowered = value.lower()
        if any(term in lowered for term in _FORBIDDEN_TERMS):
            raise ValueError(f"isolation guard rejected forbidden text at {path}")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return
        if parsed >= _MAPPING_BOUNDARY:
            raise ValueError(f"isolation guard rejected date at {path}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _isolation_guard(str(key), f"{path}.key")
            _isolation_guard(item, f"{path}.{key}")
        return
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            _isolation_guard(getattr(value, field.name), f"{path}.{field.name}")
        return
    if isinstance(value, (tuple, list, frozenset, set)):
        for index, item in enumerate(value):
            _isolation_guard(item, f"{path}[{index}]")
        return
    if hasattr(value, "__dict__"):
        for key, item in vars(value).items():
            _isolation_guard(str(key), f"{path}.key")
            _isolation_guard(item, f"{path}.{key}")


def _validate_replay_lengths(replay: FrozenK4Replay, vectors: tuple[object, ...]) -> None:
    expected = len(vectors)
    if len(replay.primary_assignments) != expected:
        raise ValueError("primary assignment length must match input vectors")
    if len(replay.primary_ood_rows) != expected:
        raise ValueError("primary OOD row length must match input vectors")
    for half in replay.half_replays:
        if len(half.assignments) != expected:
            raise ValueError("half assignment length must match input vectors")


def _raw_matrix(vectors: Sequence[object], feature_names: tuple[str, ...]) -> np.ndarray:
    return np.asarray(
        [[float(vector.values[name]) for name in feature_names] for vector in vectors],
        dtype=float,
    )


def _clip_and_scale(raw: np.ndarray, fit: object) -> np.ndarray:
    clipped = np.clip(
        raw,
        np.asarray(fit.lower_bounds, dtype=float),
        np.asarray(fit.upper_bounds, dtype=float),
    )
    return (clipped - np.asarray(fit.medians, dtype=float)) / np.asarray(
        fit.scales, dtype=float
    )


def _canonical_timestamp(value: object) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _clipped_rows(
    half_label: str, vectors: Sequence[object], fit: object, raw: np.ndarray
) -> list[ClippedSampleRow]:
    lower = np.asarray(fit.lower_bounds, dtype=float)
    upper = np.asarray(fit.upper_bounds, dtype=float)
    feature_names = tuple(fit.feature_names)
    rows: list[ClippedSampleRow] = []
    for row_index, vector in enumerate(vectors):
        for feature_index, feature_name in enumerate(feature_names):
            value = float(raw[row_index, feature_index])
            if value < lower[feature_index]:
                rows.append(
                    ClippedSampleRow(
                        _canonical_timestamp(vector.anchor_at),
                        half_label,
                        feature_name,
                        "lower",
                        value,
                        float(lower[feature_index]),
                    )
                )
            elif value > upper[feature_index]:
                rows.append(
                    ClippedSampleRow(
                        _canonical_timestamp(vector.anchor_at),
                        half_label,
                        feature_name,
                        "upper",
                        value,
                        float(upper[feature_index]),
                    )
                )
    return rows


def _location_rows(
    half_label: str,
    primary_index: int,
    half_index: int,
    primary_mean: np.ndarray,
    members: np.ndarray,
) -> list[LocationDistanceRow]:
    if len(members) == 0:
        return []
    statistics = {
        "mean": members.mean(axis=0),
        "coordinate_median": np.median(members, axis=0),
        "trimmed_mean_10pct": _trimmed_mean(members, 0.10),
        "medoid": _medoid(members),
    }
    return [
        LocationDistanceRow(
            half_label,
            primary_index,
            half_index,
            statistic,
            float(np.linalg.norm(location - primary_mean)),
        )
        for statistic, location in statistics.items()
    ]


def _trimmed_mean(values: np.ndarray, proportion: float) -> np.ndarray:
    trim = int(np.floor(len(values) * proportion))
    if trim == 0 or len(values) <= trim * 2:
        return values.mean(axis=0)
    ordered = np.sort(values, axis=0)
    return ordered[trim:-trim].mean(axis=0)


def _medoid(values: np.ndarray) -> np.ndarray:
    distances = np.linalg.norm(values[:, None, :] - values[None, :, :], axis=2)
    return values[int(np.argmin(distances.sum(axis=1)))]


def _exclusion_rows(
    half_label: str,
    primary_fingerprint: str,
    primary_mean: np.ndarray,
    members: np.ndarray,
    anchors: Sequence[object],
) -> list[SensitivityRow]:
    if len(members) == 0:
        return []
    distances = np.linalg.norm(members - primary_mean, axis=1)
    order = sorted(
        range(len(members)),
        key=lambda index: (-float(distances[index]), _canonical_timestamp(anchors[index])),
    )
    requests = (
        ("exclude_farthest_1", 1),
        ("exclude_farthest_3", 3),
        ("exclude_farthest_5", 5),
        ("exclude_farthest_1pct", max(1, int(np.ceil(len(members) * 0.01)))),
    )
    rows: list[SensitivityRow] = []
    for statistic, requested in requests:
        excluded = min(requested, len(members))
        keep = np.ones(len(members), dtype=bool)
        keep[order[:excluded]] = False
        remaining = members[keep]
        location = primary_mean if len(remaining) == 0 else remaining.mean(axis=0)
        rows.append(
            SensitivityRow(
                half_label,
                primary_fingerprint,
                statistic,
                excluded,
                float(np.linalg.norm(location - primary_mean)),
            )
        )
    return rows


def _pooled_mahalanobis_row(
    half_label: str,
    primary_index: int,
    half_index: int,
    feature_names: tuple[str, ...],
    primary_mean: np.ndarray,
    half_mean: np.ndarray,
    primary_variance: np.ndarray,
    members: np.ndarray,
) -> PooledMahalanobisRow:
    empirical = (
        np.zeros_like(primary_variance)
        if len(members) <= 1
        else np.var(members, axis=0, ddof=1)
    )
    pooled = np.maximum((primary_variance + empirical) / 2.0, _VARIANCE_FLOOR)
    contributions = (half_mean - primary_mean) ** 2 / pooled
    return PooledMahalanobisRow(
        half_label,
        primary_index,
        half_index,
        float(contributions.sum()),
        {
            name: float(value)
            for name, value in sorted(
                zip(feature_names, contributions),
                key=lambda item: (-float(item[1]), item[0]),
            )
        },
    )


def _component_distance_rows(
    half_label: str,
    primary_index: int,
    half_index: int,
    primary_mean: np.ndarray,
    half_mean: np.ndarray,
    primary_variance: np.ndarray,
    half_variance: np.ndarray,
) -> list[ComponentDistanceRow]:
    primary_variance = np.maximum(primary_variance, _VARIANCE_FLOOR)
    half_variance = np.maximum(half_variance, _VARIANCE_FLOOR)
    delta = half_mean - primary_mean
    euclidean = float(np.linalg.norm(delta))
    kl_primary_half = 0.5 * float(
        np.sum(
            np.log(half_variance / primary_variance)
            + (primary_variance + delta**2) / half_variance
            - 1.0
        )
    )
    kl_half_primary = 0.5 * float(
        np.sum(
            np.log(primary_variance / half_variance)
            + (half_variance + delta**2) / primary_variance
            - 1.0
        )
    )
    average = (primary_variance + half_variance) / 2.0
    bhattacharyya = 0.125 * float(np.sum(delta**2 / average)) + 0.5 * float(
        np.sum(np.log(average / np.sqrt(primary_variance * half_variance)))
    )
    wasserstein_2 = float(
        np.sum(
            delta**2
            + primary_variance
            + half_variance
            - 2.0 * np.sqrt(primary_variance * half_variance)
        )
    )
    metrics = {
        "euclidean": euclidean,
        "symmetric_kl": (kl_primary_half + kl_half_primary) / 2.0,
        "bhattacharyya": bhattacharyya,
        "diagonal_wasserstein_2": wasserstein_2,
    }
    return [
        ComponentDistanceRow(half_label, primary_index, half_index, metric, value)
        for metric, value in metrics.items()
    ]


def _ood_rows(
    replay: object,
    primary_fit: object,
    feature_names: tuple[str, ...],
    primary_clipped: np.ndarray,
    primary_assignments: np.ndarray,
) -> tuple[list[OODComponentRow], list[OODSampleContributionRow]]:
    rows = tuple(replay.primary_ood_rows)
    by_component: list[OODComponentRow] = []
    sample_rows: list[OODSampleContributionRow] = []
    for component_index, fingerprint in enumerate(primary_fit.fingerprints):
        component_rows = [
            row for row in rows if int(row.assigned_component_index) == component_index
        ]
        exceeded = [row for row in component_rows if row.exceeds]
        by_component.append(
            OODComponentRow(
                component_index,
                fingerprint,
                len(component_rows),
                len(exceeded),
                0.0 if not component_rows else len(exceeded) / len(component_rows),
            )
        )
    for index, row in enumerate(rows):
        if not row.exceeds:
            continue
        component = int(primary_assignments[index])
        mean = np.asarray(primary_fit.means[component], dtype=float)
        variance = np.maximum(
            np.asarray(primary_fit.covariances[component], dtype=float), _VARIANCE_FLOOR
        )
        contributions = (primary_clipped[index] - mean) ** 2 / variance
        sample_rows.append(
            OODSampleContributionRow(
                row.anchor_at,
                component,
                row.assigned_component_fingerprint,
                float(row.squared_mahalanobis),
                float(row.threshold),
                {
                    name: float(value)
                    for name, value in sorted(
                        zip(feature_names, contributions),
                        key=lambda item: (-float(item[1]), item[0]),
                    )
                },
            )
        )
    return by_component, sample_rows


def _classify_causes(
    summaries: tuple[ClusterSummaryRow, ...],
    features: tuple[FeatureContributionRow, ...],
    locations: tuple[LocationDistanceRow, ...],
    pooled: tuple[PooledMahalanobisRow, ...],
    ood: tuple[OODComponentRow, ...],
) -> CauseClassification:
    causes: set[str] = set()
    signals: dict[str, float | str] = {}
    if summaries:
        largest = max(summaries, key=lambda row: row.euclidean_distance)
        signals["largest_centroid_half"] = largest.half_label
        signals["largest_centroid_component"] = float(largest.primary_component_index)
        signals["largest_centroid_distance"] = largest.euclidean_distance
        if largest.euclidean_distance > 0.0:
            causes.add("specific-cluster-drift")
    if features:
        largest_feature = max(features, key=lambda row: row.squared_distance)
        signals["largest_feature_squared_distance"] = largest_feature.squared_distance
        signals["largest_feature_component"] = float(largest_feature.primary_component_index)
        if largest_feature.contribution_ratio >= 0.5:
            causes.add("specific-feature-drift")
    mean_by_key = {
        (row.half_label, row.primary_component_index): row.centroid_distance
        for row in locations
        if row.statistic == "mean"
    }
    median_by_key = {
        (row.half_label, row.primary_component_index): row.centroid_distance
        for row in locations
        if row.statistic == "coordinate_median"
    }
    for key, mean_distance in mean_by_key.items():
        median_distance = median_by_key.get(key)
        if median_distance is not None and mean_distance > median_distance * 1.25:
            causes.add("tail-sensitive-drift")
            signals["largest_mean_median_gap"] = max(
                float(signals.get("largest_mean_median_gap", 0.0)),
                mean_distance - median_distance,
            )
    if pooled:
        largest_pooled = max(pooled, key=lambda row: row.squared_distance)
        signals["largest_pooled_mahalanobis"] = largest_pooled.squared_distance
        if largest_pooled.squared_distance > 1.0:
            causes.add("covariance-aware-drift")
    if ood:
        largest_ood = max(ood, key=lambda row: row.exceedance_rate)
        signals["largest_ood_rate"] = largest_ood.exceedance_rate
        signals["largest_ood_component"] = float(largest_ood.component_index)
        if largest_ood.exceedance_count > 0:
            causes.add("component-ood-concentration")
    return CauseClassification(tuple(sorted(causes)), signals)


def _offset_rows(assignments: np.ndarray) -> list[OffsetSubsampleRow]:
    rows: list[OffsetSubsampleRow] = []
    for spacing in (3, 7):
        for offset in range(spacing):
            selected = assignments[offset::spacing]
            counts = {
                int(component): int(np.count_nonzero(selected == component))
                for component in sorted(set(int(value) for value in assignments))
            }
            rows.append(OffsetSubsampleRow(spacing, offset, int(len(selected)), counts))
    return rows


def _top_features(
    rows: Sequence[FeatureContributionRow],
) -> dict[tuple[str, int], tuple[str, ...]]:
    grouped: dict[tuple[str, int], list[FeatureContributionRow]] = {}
    for row in rows:
        grouped.setdefault((row.half_label, row.primary_component_index), []).append(row)
    return {
        key: tuple(
            row.feature_name
            for row in sorted(
                value, key=lambda item: (-item.squared_distance, item.feature_name)
            )[:5]
        )
        for key, value in grouped.items()
    }


__all__ = [
    "CauseClassification",
    "ClippedSampleRow",
    "ClusterSummaryRow",
    "ComponentDistanceRow",
    "FeatureContributionRow",
    "FrozenK4Decomposition",
    "LocationDistanceRow",
    "OODComponentRow",
    "OODSampleContributionRow",
    "OffsetSubsampleRow",
    "PooledMahalanobisRow",
    "decompose_frozen_k4_failure",
]
