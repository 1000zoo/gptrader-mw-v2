"""Pure decomposition of the reproduced frozen K4 diagnostic failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from src.domain.regime.frozen_k4_failure_diagnostics import SensitivityRow

_ASSIGNMENT_SOURCE = "frozen_reproduced_half_assignment"
_VARIANCE_FLOOR = 1e-6


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


@dataclass(frozen=True)
class OffsetSubsampleRow:
    spacing_days: int
    offset: int
    sample_count: int
    component_counts: Mapping[int, int]
    assignment_source: str = _ASSIGNMENT_SOURCE
    refit_after_exclusion: bool = False
    diagnostic_only: bool = True


@dataclass(frozen=True)
class FrozenK4Decomposition:
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


def decompose_frozen_k4_failure(
    replay: object,
    primary_fit: object,
    vectors: Sequence[object],
) -> FrozenK4Decomposition:
    status = getattr(replay, "status", None)
    if (
        getattr(status, "status", None) != "reproduced"
        or getattr(status, "decomposition_allowed", None) is not True
    ):
        raise ValueError("decomposition requires reproduced replay")

    feature_names = tuple(primary_fit.feature_names)
    raw = _raw_matrix(vectors, feature_names)
    primary_clipped = _clip_and_scale(raw, primary_fit)
    primary_assignments = np.asarray(tuple(replay.primary_assignments), dtype=int)

    feature_rows: list[FeatureContributionRow] = []
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

    ood_by_component, ood_samples = _ood_rows(
        replay, primary_fit, feature_names, primary_clipped, primary_assignments
    )
    offsets = _offset_rows(primary_assignments)
    top = _top_features(feature_rows)
    return FrozenK4Decomposition(
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
    "ClippedSampleRow",
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
