"""Descriptive Component 0 OOD cause summary for the frozen K4 diagnosis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from statistics import median
import sys
from typing import Sequence

import numpy as np

from src.application.services.frozen_k4_failure_decomposition import FrozenK4Decomposition
from src.application.services.frozen_k4_failure_replay import FrozenK4Replay
from src.domain.regime import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)


_ANALYSIS_SCOPE = "primary-component-0-ood-exceedances"
_COMPONENT_INDEX = 0
_ASSIGNED_SAMPLE_COUNT = 409
_OOD_SAMPLE_COUNT = 24
_SINGLE_FEATURE_THRESHOLD = 0.50
_VOLATILITY_FAMILY_THRESHOLD = 0.70
_RECURRENT_FEATURE_THRESHOLD = 0.50
_FULL_SAMPLE_SCOPE = "full_sample"
_FULL_SAMPLE_METRIC = "full_sample_empirical_centroid_distance"
_ASSIGNMENT_SOURCE = "frozen_reproduced_half_assignment"
_COMPLETION_SCOPE = "frozen-k4-diagnosis-completion"
_OFFSET_SPACINGS = (3, 7)
_OOD_DISTANCE_SOURCE = "existing_primary_ood_row"
_OOD_THRESHOLD_SOURCE = "frozen_component_chi_square_threshold"
_RECEIPT_ASSIGNMENT_SOURCE = "existing_reproduced_assignments"


def _is_finite_nonnegative(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _meets_threshold(value: float, threshold: float) -> bool:
    return value >= threshold


def _validate_scope_identity(scope: str, component_index: int, fingerprint: str) -> None:
    if scope != _ANALYSIS_SCOPE or component_index != _COMPONENT_INDEX:
        raise ValueError("Component 0 OOD analysis identity is not canonical")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 24
        or fingerprint != fingerprint.lower()
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ValueError("component fingerprint is not canonical")


def _validate_registry_identity(schema_version: str, registry_sha256: str) -> None:
    if schema_version != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION:
        raise ValueError("registry schema version is not canonical")
    if (
        not isinstance(registry_sha256, str)
        or len(registry_sha256) != 64
        or registry_sha256 != registry_sha256.lower()
        or any(character not in "0123456789abcdef" for character in registry_sha256)
    ):
        raise ValueError("registry hash is not canonical")


def _canonical_fingerprint(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 24
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} fingerprint is not canonical")


def _canonical_anchor(value: object) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("offset origin anchor must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("offset origin anchor must be canonical UTC") from exc
    if parsed.tzinfo is not timezone.utc or parsed.isoformat().replace("+00:00", "Z") != value:
        raise ValueError("offset origin anchor must be canonical UTC")


def _component_index(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a nonnegative integer")


def _validate_empirical_scope(
    sample_scope: str,
    spacing_days: int | None,
    offset: int | None,
) -> None:
    if sample_scope == _FULL_SAMPLE_SCOPE:
        if spacing_days is not None or offset is not None:
            raise ValueError("full-sample scope cannot carry spacing or offset")
        return
    if (
        sample_scope != "offset_subsample"
        or not isinstance(spacing_days, int)
        or isinstance(spacing_days, bool)
        or spacing_days <= 0
        or not isinstance(offset, int)
        or isinstance(offset, bool)
        or not 0 <= offset < spacing_days
    ):
        raise ValueError("empirical sample scope is not canonical")


def _global_offset_indices(
    sample_count: int, spacing_days: int, offset: int
) -> tuple[int, ...]:
    """Select a descriptive subsample by immutable global array position."""
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count < 0
        or spacing_days not in _OFFSET_SPACINGS
        or not isinstance(offset, int)
        or isinstance(offset, bool)
        or not 0 <= offset < spacing_days
    ):
        raise ValueError("global offset selection is not canonical")
    return tuple(range(offset, sample_count, spacing_days))


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
    distance_source: str = _OOD_DISTANCE_SOURCE
    threshold_source: str = _OOD_THRESHOLD_SOURCE

    def __post_init__(self) -> None:
        if self.sample_scope == _FULL_SAMPLE_SCOPE:
            if self.spacing_days is not None or self.offset is not None:
                raise ValueError("full-sample OOD row cannot carry an offset")
        elif (
            self.sample_scope != "offset_subsample"
            or self.spacing_days not in _OFFSET_SPACINGS
            or not isinstance(self.offset, int)
            or isinstance(self.offset, bool)
            or not 0 <= self.offset < self.spacing_days
        ):
            raise ValueError("OOD sample scope is not canonical")
        _component_index(self.primary_component_index, "primary component index")
        _canonical_fingerprint(self.primary_component_fingerprint, "primary component")
        if (
            not isinstance(self.numerator, int)
            or isinstance(self.numerator, bool)
            or not isinstance(self.denominator, int)
            or isinstance(self.denominator, bool)
            or not 0 <= self.numerator <= self.denominator
        ):
            raise ValueError("OOD numerator and denominator are incoherent")
        expected = None if self.denominator == 0 else self.numerator / self.denominator
        if (expected is None and self.rate is not None) or (
            expected is not None
            and (
                not isinstance(self.rate, float)
                or not math.isfinite(self.rate)
                or self.rate != expected
            )
        ):
            raise ValueError("OOD rate does not reconcile with counts")
        if (
            self.distance_source != _OOD_DISTANCE_SOURCE
            or self.threshold_source != _OOD_THRESHOLD_SOURCE
        ):
            raise ValueError("OOD provenance is not frozen")


@dataclass(frozen=True)
class FixedSampleReceipt:
    global_index: int
    anchor_at: str
    half_label: str
    half_component_index: int
    half_component_fingerprint: str
    matched_primary_component_index: int
    matched_primary_component_fingerprint: str
    primary_component_index: int
    primary_component_fingerprint: str
    squared_mahalanobis: float
    ood_threshold: float
    ood_exceeds: bool
    assignment_source: str = _RECEIPT_ASSIGNMENT_SOURCE

    def __post_init__(self) -> None:
        _component_index(self.global_index, "global index")
        _canonical_anchor(self.anchor_at)
        if self.half_label not in ("A", "B"):
            raise ValueError("half label is not canonical")
        for name in (
            "half_component_index",
            "matched_primary_component_index",
            "primary_component_index",
        ):
            _component_index(getattr(self, name), name)
        for name in (
            "half_component_fingerprint",
            "matched_primary_component_fingerprint",
            "primary_component_fingerprint",
        ):
            _canonical_fingerprint(getattr(self, name), name)
        if not _is_finite_nonnegative(self.squared_mahalanobis) or not _is_finite_nonnegative(
            self.ood_threshold
        ):
            raise ValueError("OOD receipt distance and threshold must be finite")
        if (
            not isinstance(self.ood_exceeds, bool)
            or self.ood_exceeds is not (self.squared_mahalanobis > self.ood_threshold)
        ):
            raise ValueError("OOD receipt must use the strict > flag")
        if self.assignment_source != _RECEIPT_ASSIGNMENT_SOURCE:
            raise ValueError("sample receipt assignment provenance is not frozen")


@dataclass(frozen=True)
class OffsetConclusion:
    spacing_days: int
    offset: int
    maximum_drift_half_label: str
    maximum_drift_primary_component_index: int
    maximum_drift_primary_component_fingerprint: str
    maximum_drift_half_component_index: int
    maximum_drift_half_component_fingerprint: str
    maximum_ood_primary_component_index: int
    maximum_ood_primary_component_fingerprint: str
    top_five_drift_features: tuple[str, ...]
    drift_component_matches_full_sample: bool
    ood_component_matches_full_sample: bool
    ordered_top5_matches_full_sample: bool
    top5_set_matches_full_sample: bool

    def __post_init__(self) -> None:
        if (
            self.spacing_days not in _OFFSET_SPACINGS
            or not isinstance(self.offset, int)
            or isinstance(self.offset, bool)
            or not 0 <= self.offset < self.spacing_days
        ):
            raise ValueError("offset conclusion key is not canonical")
        if self.maximum_drift_half_label not in ("A", "B"):
            raise ValueError("offset conclusion half is not canonical")
        for name in (
            "maximum_drift_primary_component_index",
            "maximum_drift_half_component_index",
            "maximum_ood_primary_component_index",
        ):
            _component_index(getattr(self, name), name)
        for name in (
            "maximum_drift_primary_component_fingerprint",
            "maximum_drift_half_component_fingerprint",
            "maximum_ood_primary_component_fingerprint",
        ):
            _canonical_fingerprint(getattr(self, name), name)
        if (
            not isinstance(self.top_five_drift_features, tuple)
            or not self.top_five_drift_features
            or len(set(self.top_five_drift_features)) != len(self.top_five_drift_features)
            or any(not isinstance(value, bool) for value in (
                self.drift_component_matches_full_sample,
                self.ood_component_matches_full_sample,
                self.ordered_top5_matches_full_sample,
                self.top5_set_matches_full_sample,
            ))
        ):
            raise ValueError("offset conclusion fields are not canonical")


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
    half_component_fingerprint: str
    sample_count: int
    sample_share: float
    centroid_status: str
    metric_name: str
    empirical_centroid: tuple[float, ...] | None
    distance: float | None
    assignment_source: str = _ASSIGNMENT_SOURCE
    refit_performed: bool = False
    rematch_performed: bool = False
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        _validate_empirical_scope(self.sample_scope, self.spacing_days, self.offset)
        _canonical_anchor(self.offset_origin_anchor)
        if self.half_label not in ("A", "B"):
            raise ValueError("half label is not canonical")
        _component_index(self.primary_component_index, "primary component index")
        _component_index(self.half_component_index, "half component index")
        _canonical_fingerprint(self.primary_component_fingerprint, "primary component")
        _canonical_fingerprint(self.half_component_fingerprint, "half component")
        if (
            not isinstance(self.sample_count, int)
            or isinstance(self.sample_count, bool)
            or self.sample_count < 0
            or not _is_finite_nonnegative(self.sample_share)
            or self.sample_share > 1
        ):
            raise ValueError("sample count and share must be finite and nonnegative")
        expected_metric = (
            _FULL_SAMPLE_METRIC
            if self.sample_scope == _FULL_SAMPLE_SCOPE
            else "offset_empirical_centroid_distance"
        )
        if self.metric_name != expected_metric:
            raise ValueError("empirical centroid metric name is not canonical")
        if (
            self.assignment_source != _ASSIGNMENT_SOURCE
            or self.refit_performed is not False
            or self.rematch_performed is not False
            or self.diagnostic_only is not True
        ):
            raise ValueError("empirical centroid provenance is not frozen diagnostic-only")
        if self.sample_count == 0:
            if (
                self.sample_share != 0
                or self.centroid_status != "insufficient_sample"
                or self.empirical_centroid is not None
                or self.distance is not None
            ):
                raise ValueError("centroid status and null fields are inconsistent")
            return
        if (
            self.centroid_status != "computed"
            or not isinstance(self.empirical_centroid, tuple)
            or not self.empirical_centroid
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in self.empirical_centroid
            )
            or not _is_finite_nonnegative(self.distance)
        ):
            raise ValueError("centroid status and computed fields are inconsistent")


@dataclass(frozen=True)
class EmpiricalFeatureContributionRow:
    sample_scope: str
    spacing_days: int | None
    offset: int | None
    half_label: str
    primary_component_index: int
    half_component_index: int
    primary_component_fingerprint: str
    half_component_fingerprint: str
    feature_name: str
    registry_family: str
    squared_distance: float
    contribution_ratio: float
    rank: int

    def __post_init__(self) -> None:
        _validate_empirical_scope(self.sample_scope, self.spacing_days, self.offset)
        if self.half_label not in ("A", "B"):
            raise ValueError("half label is not canonical")
        _component_index(self.primary_component_index, "primary component index")
        _component_index(self.half_component_index, "half component index")
        _canonical_fingerprint(self.primary_component_fingerprint, "primary component")
        _canonical_fingerprint(self.half_component_fingerprint, "half component")
        if not self.feature_name or not self.registry_family:
            raise ValueError("feature registry identity must be nonblank")
        if not _is_finite_nonnegative(self.squared_distance):
            raise ValueError("squared distance must be finite and nonnegative")
        if not _is_finite_nonnegative(self.contribution_ratio) or self.contribution_ratio > 1:
            raise ValueError("contribution ratio must be finite and nonnegative and at most one")
        if not isinstance(self.rank, int) or isinstance(self.rank, bool) or self.rank < 1:
            raise ValueError("feature contribution rank must be positive")


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
    maximum_drift_primary_component_fingerprint: str
    maximum_drift_half_component_fingerprint: str
    maximum_drift_distance: float
    top_five_drift_features: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_empirical_scope(self.sample_scope, self.spacing_days, self.offset)
        if (
            not isinstance(self.selected_sample_count, int)
            or isinstance(self.selected_sample_count, bool)
            or self.selected_sample_count < 1
            or not isinstance(self.centroid_rows, tuple)
            or not self.centroid_rows
            or not isinstance(self.feature_rows, tuple)
        ):
            raise ValueError("empirical summary contents must be immutable and nonempty")
        if any(
            row.sample_scope != self.sample_scope
            or row.spacing_days != self.spacing_days
            or row.offset != self.offset
            for row in (*self.centroid_rows, *self.feature_rows)
        ):
            raise ValueError("nested empirical scope provenance is inconsistent")
        origins = {row.offset_origin_anchor for row in self.centroid_rows}
        if len(origins) != 1:
            raise ValueError("empirical centroid rows must share one offset origin anchor")
        if sum(row.sample_count for row in self.centroid_rows) != self.selected_sample_count:
            raise ValueError("selected sample count does not reconcile")
        centroid_identities = tuple(
            (row.half_label, row.primary_component_index, row.half_component_index)
            for row in self.centroid_rows
        )
        if len(set(centroid_identities)) != len(centroid_identities):
            raise ValueError("empirical centroid identities must be unique")
        if {row.half_label for row in self.centroid_rows} != {"A", "B"}:
            raise ValueError("empirical centroid graph must cover exactly halves A and B")
        primary_indices_by_half: dict[str, tuple[int, ...]] = {}
        primary_fingerprints: dict[int, str] = {}
        for half_label in ("A", "B"):
            half_rows = tuple(row for row in self.centroid_rows if row.half_label == half_label)
            primary_indices = tuple(row.primary_component_index for row in half_rows)
            half_indices = tuple(row.half_component_index for row in half_rows)
            half_fingerprints = tuple(row.half_component_fingerprint for row in half_rows)
            if (
                len(set(primary_indices)) != len(primary_indices)
                or len(set(half_indices)) != len(half_indices)
                or len(set(half_fingerprints)) != len(half_fingerprints)
            ):
                raise ValueError("empirical centroid graph must be complete and one-to-one per half")
            primary_indices_by_half[half_label] = primary_indices
            for row in half_rows:
                prior = primary_fingerprints.setdefault(
                    row.primary_component_index, row.primary_component_fingerprint
                )
                if prior != row.primary_component_fingerprint:
                    raise ValueError(
                        "primary fingerprint must be consistent for each component across halves"
                    )
        if set(primary_indices_by_half["A"]) != set(primary_indices_by_half["B"]):
            raise ValueError("empirical centroid graph must contain a complete primary pair set in each half")
        for half_label in {row.half_label for row in self.centroid_rows}:
            half_rows = tuple(row for row in self.centroid_rows if row.half_label == half_label)
            half_count = sum(row.sample_count for row in half_rows)
            for row in half_rows:
                expected_share = row.sample_count / half_count if half_count else 0.0
                if not math.isclose(row.sample_share, expected_share, rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError("empirical centroid sample shares do not reconcile within half")
        valid = tuple(row for row in self.centroid_rows if row.centroid_status == "computed")
        if not valid:
            raise ValueError("empirical summary has no computed centroid")
        winner = min(
            valid,
            key=lambda row: (
                -float(row.distance),
                row.half_label,
                row.primary_component_index,
                row.half_component_index,
            ),
        )
        maximum_identity = (
            self.maximum_drift_half_label,
            self.maximum_drift_primary_component_index,
            self.maximum_drift_half_component_index,
            self.maximum_drift_primary_component_fingerprint,
            self.maximum_drift_half_component_fingerprint,
        )
        winner_identity = (
            winner.half_label,
            winner.primary_component_index,
            winner.half_component_index,
            winner.primary_component_fingerprint,
            winner.half_component_fingerprint,
        )
        if maximum_identity != winner_identity or not math.isclose(
            self.maximum_drift_distance,
            float(winner.distance),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("maximum drift fields do not identify the valid maximum row")

        feature_names = {spec.name: spec for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
        retained_position = {name: index for index, name in enumerate(feature_names)}
        by_centroid: dict[tuple[str, int, int], list[EmpiricalFeatureContributionRow]] = {}
        for row in self.feature_rows:
            identity = (row.half_label, row.primary_component_index, row.half_component_index)
            by_centroid.setdefault(identity, []).append(row)
            if row.feature_name not in feature_names or row.registry_family != feature_names[row.feature_name].family:
                raise ValueError("feature contribution registry identity is not canonical")
        computed_identities = {
            (row.half_label, row.primary_component_index, row.half_component_index)
            for row in self.centroid_rows
            if row.centroid_status == "computed"
        }
        if set(by_centroid) != computed_identities:
            raise ValueError(
                "feature-row group identities must exactly equal computed centroid identities"
            )
        computed_feature_sets: list[set[str]] = []
        for centroid in self.centroid_rows:
            identity = (centroid.half_label, centroid.primary_component_index, centroid.half_component_index)
            rows = tuple(by_centroid.get(identity, ()))
            if centroid.centroid_status == "insufficient_sample":
                if rows:
                    raise ValueError("insufficient centroid cannot carry feature rows")
                continue
            if not rows or len({row.feature_name for row in rows}) != len(rows):
                raise ValueError("computed centroid feature rows are incomplete")
            computed_feature_sets.append({row.feature_name for row in rows})
            expected = tuple(
                sorted(rows, key=lambda row: (-row.squared_distance, retained_position[row.feature_name]))
            )
            if rows != expected or tuple(row.rank for row in rows) != tuple(range(1, len(rows) + 1)):
                raise ValueError("feature rows have incoherent rank or order")
            if any(
                row.primary_component_fingerprint != centroid.primary_component_fingerprint
                or row.half_component_fingerprint != centroid.half_component_fingerprint
                for row in rows
            ):
                raise ValueError("feature and centroid fingerprints disagree")
            squared_total = math.fsum(row.squared_distance for row in rows)
            if not math.isclose(squared_total, float(centroid.distance) ** 2, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("feature squared distances do not reconcile")
            ratio_total = math.fsum(row.contribution_ratio for row in rows)
            expected_ratio_total = 0.0 if squared_total == 0 else 1.0
            if not math.isclose(ratio_total, expected_ratio_total, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("feature contribution ratios do not reconcile")
            if any(
                not math.isclose(
                    row.contribution_ratio,
                    0.0 if squared_total == 0 else row.squared_distance / squared_total,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
                for row in rows
            ):
                raise ValueError("feature contribution ratios do not match squared distances")
        if any(names != computed_feature_sets[0] for names in computed_feature_sets[1:]):
            raise ValueError("computed centroid feature sets must be complete and identical")
        retained_names = tuple(
            name for name in feature_names if name in computed_feature_sets[0]
        )
        if set(retained_names) != computed_feature_sets[0] or any(
            len(row.empirical_centroid or ()) != len(retained_names)
            for row in valid
        ):
            raise ValueError("computed centroid feature dimensions are inconsistent")
        winner_features = tuple(
            by_centroid[(winner.half_label, winner.primary_component_index, winner.half_component_index)]
        )
        expected_top_five = tuple(row.feature_name for row in winner_features[:5])
        if self.top_five_drift_features != expected_top_five:
            raise ValueError("top-five drift features do not reproduce the maximum row")


def _primary_scaled_matrix(primary_fit: object, vectors: tuple[object, ...]) -> np.ndarray:
    if not isinstance(vectors, tuple):
        raise ValueError("feature vectors must be an immutable tuple")
    feature_names = getattr(primary_fit, "feature_names", None)
    if (
        not isinstance(feature_names, tuple)
        or not feature_names
        or len(set(feature_names)) != len(feature_names)
    ):
        raise ValueError("primary feature names must be a unique immutable tuple")
    registry_names = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    if tuple(name for name in registry_names if name in set(feature_names)) != feature_names:
        raise ValueError("primary feature order must be a retained registry subsequence")
    parameters = {}
    for name in ("lower_bounds", "upper_bounds", "medians", "scales"):
        values = getattr(primary_fit, name, None)
        if not isinstance(values, tuple) or len(values) != len(feature_names):
            raise ValueError("primary preprocessing array dimensions are inconsistent")
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in values
        ):
            raise ValueError("primary preprocessing arrays must contain finite values")
        parameters[name] = np.asarray(values, dtype=np.float64)
    if np.any(parameters["lower_bounds"] > parameters["upper_bounds"]):
        raise ValueError("primary clipping bounds must satisfy lower <= upper")
    if np.any(parameters["scales"] <= 0):
        raise ValueError("primary scales must be finite and strictly positive")

    matrix: list[list[float]] = []
    for vector in vectors:
        values = getattr(vector, "values", None)
        vector_names = tuple(values) if values is not None else ()
        if vector_names not in (feature_names, registry_names):
            raise ValueError("feature vector count/order does not match primary features")
        row = []
        for name in feature_names:
            value = values[name]
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise ValueError("feature vector values must be finite")
            row.append(float(value))
        matrix.append(row)
    raw = np.asarray(matrix, dtype=np.float64)
    if raw.ndim != 2 or raw.shape != (len(vectors), len(feature_names)):
        raise ValueError("feature vector matrix dimensions are inconsistent")
    clipped = np.clip(raw, parameters["lower_bounds"], parameters["upper_bounds"])
    scaled = (clipped - parameters["medians"]) / parameters["scales"]
    if not np.isfinite(scaled).all():
        raise ValueError("primary scaled matrix must be finite")
    scaled.setflags(write=False)
    return scaled


def _anchor_string(anchor: object) -> str:
    if not isinstance(anchor, datetime) or anchor.tzinfo is not timezone.utc:
        raise ValueError("vector anchor must be canonical UTC")
    result = anchor.isoformat().replace("+00:00", "Z")
    _canonical_anchor(result)
    return result


def _validate_diagnostic_provenance(replay: FrozenK4Replay) -> None:
    if replay.diagnostic_only is not True or replay.primary_replacement_allowed is not False:
        raise ValueError("replay diagnostic provenance forbids primary replacement")
    for half in replay.half_replays:
        if half.diagnostic_only is not True or half.primary_replacement_allowed is not False:
            raise ValueError("half replay diagnostic provenance forbids primary replacement")
        for source_name, source in (("receipt", half.receipt), ("fit", half.fit)):
            diagnostic_only = getattr(source, "diagnostic_only", True)
            replacement_allowed = getattr(source, "primary_replacement_allowed", False)
            if diagnostic_only is not True or replacement_allowed is not False:
                raise ValueError(
                    f"half {source_name} diagnostic provenance forbids primary replacement"
                )


def _safe_empirical_mean(values: np.ndarray) -> float:
    count = len(values)
    try:
        result = math.fsum(float(value) / count for value in values)
    except OverflowError as exc:
        raise ValueError("empirical centroid exceeds the finite representable range") from exc
    if not math.isfinite(result):
        raise ValueError("empirical centroid exceeds the finite representable range")
    return result


def _safe_squared_contributions(
    empirical: tuple[float, ...],
    target: tuple[float, ...],
) -> tuple[tuple[float, ...], float]:
    square_root_max = math.sqrt(sys.float_info.max)
    squared: list[float] = []
    for actual, expected in zip(empirical, target):
        delta = actual - expected
        if not math.isfinite(delta) or abs(delta) > square_root_max:
            raise ValueError("empirical squared distance exceeds the finite representable range")
        squared.append(delta * delta)
    try:
        total = math.fsum(squared)
    except OverflowError as exc:
        raise ValueError("empirical squared distance exceeds the finite representable range") from exc
    if not math.isfinite(total):
        raise ValueError("empirical squared distance exceeds the finite representable range")
    return tuple(squared), total


def _build_empirical_scope(
    replay: FrozenK4Replay,
    primary_fit: object,
    vectors: tuple[object, ...],
    primary_scaled: np.ndarray,
    selected_indices: tuple[int, ...],
    sample_scope: str,
    spacing_days: int | None,
    offset: int | None,
) -> EmpiricalScopeSummary:
    _validate_empirical_scope(sample_scope, spacing_days, offset)
    _validate_diagnostic_provenance(replay)
    if not selected_indices or tuple(sorted(set(selected_indices))) != selected_indices:
        raise ValueError("selected indices must be a nonempty ordered unique tuple")
    if selected_indices[0] < 0 or selected_indices[-1] >= len(vectors):
        raise ValueError("selected indices are outside the global vector range")
    feature_names = primary_fit.feature_names
    means = getattr(primary_fit, "means", None)
    fingerprints = getattr(primary_fit, "fingerprints", None)
    if (
        not isinstance(means, tuple)
        or not isinstance(fingerprints, tuple)
        or len(means) != len(fingerprints)
        or not means
        or any(not isinstance(row, tuple) or len(row) != len(feature_names) for row in means)
    ):
        raise ValueError("primary component array dimensions are inconsistent")
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        for row in means
        for value in row
    ):
        raise ValueError("primary component means must be finite")
    for fingerprint in fingerprints:
        _canonical_fingerprint(fingerprint, "primary component")

    registry_by_name = {spec.name: spec for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
    registry_position = {name: index for index, name in enumerate(feature_names)}
    selected = set(selected_indices)
    metric_name = (
        _FULL_SAMPLE_METRIC
        if sample_scope == _FULL_SAMPLE_SCOPE
        else "offset_empirical_centroid_distance"
    )
    origin = _anchor_string(vectors[0].anchor_at)
    centroid_rows: list[EmpiricalCentroidRow] = []
    feature_rows: list[EmpiricalFeatureContributionRow] = []
    cursor = 0
    seen_half_labels: set[str] = set()

    supplied_half_labels = tuple(
        getattr(half.receipt, "half_label", None) for half in replay.half_replays
    )
    if supplied_half_labels != ("A", "B"):
        raise ValueError("half replays must be supplied exactly in A then B order")
    receipt_ranges = tuple(
        getattr(half.receipt, "anchor_range", None) for half in replay.half_replays
    )
    if any(
        not isinstance(anchor_range, tuple) or len(anchor_range) != 2
        for anchor_range in receipt_ranges
    ):
        raise ValueError("half receipt interval must be an immutable start/end pair")
    for start_anchor, end_anchor in receipt_ranges:
        _canonical_anchor(start_anchor)
        _canonical_anchor(end_anchor)
        if start_anchor >= end_anchor:
            raise ValueError("half receipt interval must have positive chronological width")
    if receipt_ranges[0][1] != receipt_ranges[1][0]:
        raise ValueError("half receipt intervals must meet at the frozen split boundary")

    for half in replay.half_replays:
        label = getattr(half.receipt, "half_label", None)
        count = getattr(half.receipt, "anchor_count", None)
        if label not in ("A", "B") or label in seen_half_labels:
            raise ValueError("half replay labels must be unique and canonical")
        seen_half_labels.add(label)
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            or len(half.assignments) != count
        ):
            raise ValueError("half assignment length does not match its exact receipt count")
        start, stop = cursor, cursor + count
        if stop > len(vectors):
            raise ValueError("half receipt counts exceed the global vector length")
        receipt_start, receipt_end = half.receipt.anchor_range
        if any(
            not receipt_start <= _anchor_string(vectors[index].anchor_at) < receipt_end
            for index in range(start, stop)
        ):
            raise ValueError("chronological vector slice falls outside its half receipt interval")
        half_selected_local = tuple(
            local for local in range(count) if start + local in selected
        )
        selected_half_count = len(half_selected_local)

        half_fingerprints = getattr(half.fit, "fingerprints", None)
        half_means = getattr(half.fit, "means", None)
        if (
            getattr(half.fit, "feature_names", None) != feature_names
            or not isinstance(half_fingerprints, tuple)
            or not isinstance(half_means, tuple)
            or len(half_fingerprints) != len(half_means)
            or not half_fingerprints
        ):
            raise ValueError("half fit component dimensions or feature order are inconsistent")
        for fingerprint in half_fingerprints:
            _canonical_fingerprint(fingerprint, "half component")
        if any(
            not isinstance(assignment, int)
            or isinstance(assignment, bool)
            or not 0 <= assignment < len(half_fingerprints)
            for assignment in half.assignments
        ):
            raise ValueError("half assignment index is outside the frozen half fit")
        pairs = half.matched_pairs
        if not isinstance(pairs, tuple) or len(pairs) != len(fingerprints) or len(pairs) != len(half_fingerprints):
            raise ValueError("matched pairs must provide a complete component mapping")
        primary_pair_indices = tuple(pair.primary_component_index for pair in pairs)
        half_pair_indices = tuple(pair.half_component_index for pair in pairs)
        if (
            set(primary_pair_indices) != set(range(len(fingerprints)))
            or set(half_pair_indices) != set(range(len(half_fingerprints)))
            or len(set(primary_pair_indices)) != len(primary_pair_indices)
            or len(set(half_pair_indices)) != len(half_pair_indices)
        ):
            raise ValueError("matched pairs must be complete and one-to-one")
        for pair in pairs:
            if (
                pair.half_label != label
                or pair.primary_component_fingerprint != fingerprints[pair.primary_component_index]
                or pair.half_component_fingerprint != half_fingerprints[pair.half_component_index]
            ):
                raise ValueError("matched pair index-fingerprint provenance is inconsistent")

        for pair in pairs:
            member_globals = tuple(
                start + local
                for local in half_selected_local
                if half.assignments[local] == pair.half_component_index
            )
            sample_count = len(member_globals)
            share = sample_count / selected_half_count if selected_half_count else 0.0
            common = dict(
                sample_scope=sample_scope,
                spacing_days=spacing_days,
                offset=offset,
                offset_origin_anchor=origin,
                half_label=label,
                primary_component_index=pair.primary_component_index,
                half_component_index=pair.half_component_index,
                primary_component_fingerprint=pair.primary_component_fingerprint,
                half_component_fingerprint=pair.half_component_fingerprint,
                sample_count=sample_count,
                sample_share=share,
                metric_name=metric_name,
            )
            if not member_globals:
                centroid_rows.append(
                    EmpiricalCentroidRow(
                        **common,
                        centroid_status="insufficient_sample",
                        empirical_centroid=None,
                        distance=None,
                    )
                )
                continue
            member_matrix = primary_scaled[np.asarray(member_globals, dtype=np.int64)]
            empirical = tuple(
                _safe_empirical_mean(member_matrix[:, feature_index])
                for feature_index in range(len(feature_names))
            )
            squared, squared_total = _safe_squared_contributions(
                empirical, means[pair.primary_component_index]
            )
            distance = math.sqrt(squared_total)
            centroid_rows.append(
                EmpiricalCentroidRow(
                    **common,
                    centroid_status="computed",
                    empirical_centroid=empirical,
                    distance=distance,
                )
            )
            ordered_indices = sorted(
                range(len(feature_names)),
                key=lambda index: (-squared[index], registry_position[feature_names[index]]),
            )
            for rank, feature_index in enumerate(ordered_indices, start=1):
                name = feature_names[feature_index]
                value = squared[feature_index]
                feature_rows.append(
                    EmpiricalFeatureContributionRow(
                        sample_scope=sample_scope,
                        spacing_days=spacing_days,
                        offset=offset,
                        half_label=label,
                        primary_component_index=pair.primary_component_index,
                        half_component_index=pair.half_component_index,
                        primary_component_fingerprint=pair.primary_component_fingerprint,
                        half_component_fingerprint=pair.half_component_fingerprint,
                        feature_name=name,
                        registry_family=registry_by_name[name].family,
                        squared_distance=value,
                        contribution_ratio=0.0 if squared_total == 0 else value / squared_total,
                        rank=rank,
                    )
                )
        cursor = stop
    if cursor != len(vectors):
        raise ValueError("half receipt counts do not reconcile with global vector length")
    winner = min(
        (row for row in centroid_rows if row.centroid_status == "computed"),
        key=lambda row: (
            -float(row.distance),
            row.half_label,
            row.primary_component_index,
            row.half_component_index,
        ),
    )
    winner_features = tuple(
        row
        for row in feature_rows
        if row.half_label == winner.half_label
        and row.primary_component_index == winner.primary_component_index
        and row.half_component_index == winner.half_component_index
    )
    return EmpiricalScopeSummary(
        sample_scope=sample_scope,
        spacing_days=spacing_days,
        offset=offset,
        selected_sample_count=len(selected_indices),
        centroid_rows=tuple(centroid_rows),
        feature_rows=tuple(feature_rows),
        maximum_drift_half_label=winner.half_label,
        maximum_drift_primary_component_index=winner.primary_component_index,
        maximum_drift_half_component_index=winner.half_component_index,
        maximum_drift_primary_component_fingerprint=winner.primary_component_fingerprint,
        maximum_drift_half_component_fingerprint=winner.half_component_fingerprint,
        maximum_drift_distance=float(winner.distance),
        top_five_drift_features=tuple(row.feature_name for row in winner_features[:5]),
    )


def build_full_sample_empirical_reference(
    replay: FrozenK4Replay,
    primary_fit: object,
    vectors: tuple[object, ...],
) -> EmpiricalScopeSummary:
    if not isinstance(replay, FrozenK4Replay):
        raise ValueError("full-sample empirical reference requires FrozenK4Replay")
    _validate_diagnostic_provenance(replay)
    if getattr(replay.status, "status", None) != "reproduced":
        raise ValueError("full-sample empirical reference requires reproduced status")
    if not isinstance(vectors, tuple):
        raise ValueError("feature vectors must be an immutable tuple")
    if (
        not vectors
        or len(vectors) != len(replay.primary_assignments)
        or len(vectors) != len(replay.primary_ood_rows)
    ):
        raise ValueError("replay vectors, primary assignments, and OOD rows must have equal length")
    fingerprints = getattr(primary_fit, "fingerprints", None)
    if not isinstance(fingerprints, tuple):
        raise ValueError("primary component fingerprints must be immutable")
    vector_anchors: list[str] = []
    for index, (vector, assignment, ood_row) in enumerate(
        zip(vectors, replay.primary_assignments, replay.primary_ood_rows)
    ):
        if (
            not isinstance(assignment, int)
            or isinstance(assignment, bool)
            or not 0 <= assignment < len(fingerprints)
        ):
            raise ValueError("primary assignment index is invalid")
        expected_anchor = _anchor_string(getattr(vector, "anchor_at", None))
        vector_anchors.append(expected_anchor)
        if (
            getattr(ood_row, "anchor_at", None) != expected_anchor
            or getattr(ood_row, "assigned_component_index", None) != assignment
            or getattr(ood_row, "assigned_component_fingerprint", None) != fingerprints[assignment]
        ):
            raise ValueError(f"primary OOD row {index} is not one-to-one with its assignment")
    if vector_anchors != sorted(set(vector_anchors)):
        raise ValueError("global feature vectors must be in strict chronological order")
    primary_scaled = _primary_scaled_matrix(primary_fit, vectors)
    return _build_empirical_scope(
        replay,
        primary_fit,
        vectors,
        primary_scaled,
        tuple(range(len(vectors))),
        _FULL_SAMPLE_SCOPE,
        None,
        None,
    )


@dataclass(frozen=True)
class OODFeatureSummaryRow:
    analysis_scope: str
    primary_component_index: int
    primary_component_fingerprint: str
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

    def __post_init__(self) -> None:
        _validate_scope_identity(
            self.analysis_scope,
            self.primary_component_index,
            self.primary_component_fingerprint,
        )
        _validate_registry_identity(self.registry_schema_version, self.registry_sha256)
        if not self.feature_name or not self.registry_family:
            raise ValueError("feature row registry identity must be nonblank")
        for value in (
            self.contribution_sum,
            self.contribution_ratio,
            self.contribution_mean,
            self.contribution_median,
            self.top1_ratio,
            self.top5_ratio,
        ):
            if not _is_finite_nonnegative(value):
                raise ValueError("feature contribution statistics must be finite and nonnegative")
        if self.contribution_ratio > 1 or self.top1_ratio > 1 or self.top5_ratio > 1:
            raise ValueError("feature ratios must be at most one")
        if not math.isclose(
            self.contribution_mean,
            self.contribution_sum / _OOD_SAMPLE_COUNT,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("feature contribution mean does not reconcile with its sum")
        if (
            not isinstance(self.top1_count, int)
            or isinstance(self.top1_count, bool)
            or not 0 <= self.top1_count <= _OOD_SAMPLE_COUNT
            or not isinstance(self.top5_count, int)
            or isinstance(self.top5_count, bool)
            or not 0 <= self.top5_count <= _OOD_SAMPLE_COUNT
            or self.top1_count > self.top5_count
            or not math.isclose(self.top1_ratio, self.top1_count / _OOD_SAMPLE_COUNT, abs_tol=1e-15)
            or not math.isclose(self.top5_ratio, self.top5_count / _OOD_SAMPLE_COUNT, abs_tol=1e-15)
            or not isinstance(self.rank, int)
            or isinstance(self.rank, bool)
            or self.rank < 1
        ):
            raise ValueError("feature counts, ratios, or rank are inconsistent")


@dataclass(frozen=True)
class OODFamilySummaryRow:
    analysis_scope: str
    primary_component_index: int
    primary_component_fingerprint: str
    family_name: str
    family_feature_names: tuple[str, ...]
    registry_schema_version: str
    registry_sha256: str
    contribution_sum: float
    contribution_ratio: float
    concentration_threshold: float
    concentration_rule_applies: bool
    concentration_result: bool

    def __post_init__(self) -> None:
        _validate_scope_identity(
            self.analysis_scope,
            self.primary_component_index,
            self.primary_component_fingerprint,
        )
        _validate_registry_identity(self.registry_schema_version, self.registry_sha256)
        if (
            not self.family_name
            or not isinstance(self.family_feature_names, tuple)
            or not self.family_feature_names
            or len(set(self.family_feature_names)) != len(self.family_feature_names)
            or any(not name for name in self.family_feature_names)
        ):
            raise ValueError("family identity must contain unique feature names")
        if not _is_finite_nonnegative(self.contribution_sum):
            raise ValueError("family contribution must be finite and nonnegative")
        if not _is_finite_nonnegative(self.contribution_ratio) or self.contribution_ratio > 1:
            raise ValueError("family contribution ratio must be in [0, 1]")
        if self.concentration_threshold != _VOLATILITY_FAMILY_THRESHOLD:
            raise ValueError("family concentration threshold is not canonical")
        expected_applies = self.family_name == "volatility"
        expected_result = expected_applies and _meets_threshold(
            self.contribution_ratio, self.concentration_threshold
        )
        if self.concentration_rule_applies is not expected_applies or self.concentration_result is not expected_result:
            raise ValueError("family concentration flags are inconsistent")


@dataclass(frozen=True)
class ComponentZeroOODAnalysis:
    analysis_scope: str
    primary_component_index: int
    primary_component_fingerprint: str
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

    def __post_init__(self) -> None:
        _validate_scope_identity(
            self.analysis_scope,
            self.primary_component_index,
            self.primary_component_fingerprint,
        )
        _validate_registry_identity(self.registry_schema_version, self.registry_sha256)
        if self.assigned_sample_count != _ASSIGNED_SAMPLE_COUNT or self.ood_sample_count != _OOD_SAMPLE_COUNT:
            raise ValueError("Component 0 population receipt is not canonical")
        if (
            not isinstance(self.feature_rows, tuple)
            or not self.feature_rows
            or not isinstance(self.family_rows, tuple)
            or not self.family_rows
            or not isinstance(self.top_five_features, tuple)
            or self.diagnostic_only is not True
        ):
            raise ValueError("analysis contents must be immutable and diagnostic-only")
        feature_names = tuple(row.feature_name for row in self.feature_rows)
        family_names = tuple(row.family_name for row in self.family_rows)
        if len(set(feature_names)) != len(feature_names) or len(set(family_names)) != len(family_names):
            raise ValueError("analysis row identities must be unique")
        if tuple(row.rank for row in self.feature_rows) != tuple(range(1, len(self.feature_rows) + 1)):
            raise ValueError("feature rows must be in rank order")
        canonical_by_name = {
            spec.name: spec for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1
        }
        if any(name not in canonical_by_name for name in feature_names):
            raise ValueError("feature rows do not identify a canonical registry subset")
        retained_names = tuple(
            spec.name
            for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1
            if spec.name in set(feature_names)
        )
        retained_position = {name: index for index, name in enumerate(retained_names)}
        expected_feature_order = tuple(
            sorted(
                retained_names,
                key=lambda name: (
                    -next(
                        row.contribution_sum
                        for row in self.feature_rows
                        if row.feature_name == name
                    ),
                    retained_position[name],
                ),
            )
        )
        if feature_names != expected_feature_order:
            raise ValueError(
                "feature row order must be contribution descending with canonical registry tie order"
            )
        if any(
            row.registry_family != canonical_by_name[row.feature_name].family
            for row in self.feature_rows
        ):
            raise ValueError("feature row registry family is not canonical")
        if self.top_five_features != feature_names[:5]:
            raise ValueError("top-five features must reproduce feature rank order")
        if any(
            row.analysis_scope != self.analysis_scope
            or row.primary_component_fingerprint != self.primary_component_fingerprint
            or row.registry_schema_version != self.registry_schema_version
            or row.registry_sha256 != self.registry_sha256
            for row in (*self.feature_rows, *self.family_rows)
        ):
            raise ValueError("nested analysis provenance is inconsistent")
        expected_registry_hash = _canonical_registry_sha256(
            retained_names,
            THREE_DAY_CHART_FEATURE_REGISTRY_V1,
            self.registry_schema_version,
        )
        if self.registry_sha256 != expected_registry_hash:
            raise ValueError("analysis does not carry the canonical registry hash")
        if not math.isclose(sum(row.contribution_ratio for row in self.feature_rows), 1.0, abs_tol=1e-12):
            raise ValueError("feature contribution ratios do not reconcile")
        if not math.isclose(sum(row.contribution_ratio for row in self.family_rows), 1.0, abs_tol=1e-12):
            raise ValueError("family contribution ratios do not reconcile")
        if sum(row.top1_count for row in self.feature_rows) != self.ood_sample_count:
            raise ValueError("top-1 counts must select exactly one feature per OOD sample")
        expected_top5_total = self.ood_sample_count * min(5, len(self.feature_rows))
        if sum(row.top5_count for row in self.feature_rows) != expected_top5_total:
            raise ValueError("top-5 counts must select the canonical number of features per OOD sample")
        total_sum = sum(row.contribution_sum for row in self.feature_rows)
        if total_sum <= 0 or any(
            not math.isclose(
                row.contribution_ratio,
                row.contribution_sum / total_sum,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            for row in self.feature_rows
        ):
            raise ValueError("feature contribution sums and ratios do not reconcile")
        family_features = tuple(
            name for row in self.family_rows for name in row.family_feature_names
        )
        if len(family_features) != len(set(family_features)) or set(family_features) != set(feature_names):
            raise ValueError("family rows must partition all retained features")
        expected_family_names = tuple(
            dict.fromkeys(canonical_by_name[name].family for name in retained_names)
        )
        if family_names != expected_family_names:
            raise ValueError("family order must follow canonical registry first appearance")
        expected_family_features = {
            family: tuple(
                name
                for name in retained_names
                if canonical_by_name[name].family == family
            )
            for family in expected_family_names
        }
        if any(
            row.family_feature_names != expected_family_features[row.family_name]
            for row in self.family_rows
        ):
            raise ValueError("family feature partition must exactly reproduce the canonical registry")
        feature_by_name = {row.feature_name: row for row in self.feature_rows}
        for family in self.family_rows:
            family_sum = sum(
                feature_by_name[name].contribution_sum
                for name in family.family_feature_names
            )
            if (
                any(
                    feature_by_name[name].registry_family != family.family_name
                    for name in family.family_feature_names
                )
                or not math.isclose(
                    family.contribution_sum, family_sum, rel_tol=1e-12, abs_tol=1e-12
                )
                or not math.isclose(
                    family.contribution_ratio,
                    family_sum / total_sum,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError("family membership and contribution statistics do not reconcile")
        expected_single = _meets_threshold(
            max(row.contribution_ratio for row in self.feature_rows),
            _SINGLE_FEATURE_THRESHOLD,
        )
        volatility = next((row for row in self.family_rows if row.family_name == "volatility"), None)
        expected_volatility = volatility is not None and _meets_threshold(
            volatility.contribution_ratio, _VOLATILITY_FAMILY_THRESHOLD
        )
        expected_recurrent = any(
            _meets_threshold(row.top1_ratio, _RECURRENT_FEATURE_THRESHOLD)
            for row in self.feature_rows
        )
        if (
            self.single_feature_concentration is not expected_single
            or self.volatility_family_concentration is not expected_volatility
            or self.recurrent_feature_dominance is not expected_recurrent
        ):
            raise ValueError("analysis concentration flags are inconsistent")


def _canonical_registry_payload(
    retained_feature_names: Sequence[str],
    registry: Sequence[object],
    registry_schema_version: str,
) -> dict[str, object]:
    return {
        "registry_schema_version": registry_schema_version,
        "retained_feature_names": list(retained_feature_names),
        "registry": [
            {
                "name": spec.name,
                "family": spec.family,
                "aggregation_minutes": spec.aggregation_minutes,
                "lookback_minutes": spec.lookback_minutes,
                "formula": spec.formula,
            }
            for spec in registry
        ],
    }


def _canonical_registry_sha256(
    retained_feature_names: Sequence[str],
    registry: Sequence[object],
    registry_schema_version: str,
) -> str:
    payload = _canonical_registry_payload(
        retained_feature_names, registry, registry_schema_version
    )
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def summarize_component_zero_ood(
    decomposition: FrozenK4Decomposition,
    *,
    retained_feature_names: Sequence[str],
    registry: Sequence[object] = THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    registry_schema_version: str = THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
) -> ComponentZeroOODAnalysis:
    if not isinstance(decomposition, FrozenK4Decomposition):
        raise ValueError("Component 0 summary requires FrozenK4Decomposition")
    if tuple(registry) != THREE_DAY_CHART_FEATURE_REGISTRY_V1:
        raise ValueError("Component 0 summary requires the canonical V1 registry")
    if registry_schema_version != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION:
        raise ValueError("Component 0 summary requires the canonical registry schema")
    names = tuple(retained_feature_names)
    registry_names = tuple(spec.name for spec in registry)
    if (
        not names
        or len(set(names)) != len(names)
        or tuple(name for name in registry_names if name in set(names)) != names
        or any(name not in registry_names for name in names)
    ):
        raise ValueError("retained features must be a unique registry-order subsequence")

    component_rows = tuple(row for row in decomposition.ood_by_component if row.component_index == 0)
    if len(component_rows) != 1:
        raise ValueError("exactly one Component 0 OOD receipt is required")
    component = component_rows[0]
    if (
        component.sample_count != _ASSIGNED_SAMPLE_COUNT
        or component.exceedance_count != _OOD_SAMPLE_COUNT
        or not math.isclose(component.exceedance_rate, _OOD_SAMPLE_COUNT / _ASSIGNED_SAMPLE_COUNT, rel_tol=0, abs_tol=1e-15)
    ):
        raise ValueError("Component 0 OOD receipt must reproduce 24/409")
    _validate_scope_identity(_ANALYSIS_SCOPE, 0, component.component_fingerprint)

    samples = tuple(row for row in decomposition.ood_samples if row.component_index == 0)
    if len(samples) != _OOD_SAMPLE_COUNT or len({row.anchor_at for row in samples}) != len(samples):
        raise ValueError("exactly 24 uniquely identified Component 0 OOD samples are required")
    expected_keys = set(names)
    contributions_by_feature = {name: [] for name in names}
    top1_counts = dict.fromkeys(names, 0)
    top5_counts = dict.fromkeys(names, 0)
    registry_position = {name: index for index, name in enumerate(names)}
    for sample in samples:
        if sample.component_fingerprint != component.component_fingerprint:
            raise ValueError("Component 0 fingerprints do not agree")
        if not _is_finite_nonnegative(sample.squared_mahalanobis) or not _is_finite_nonnegative(sample.threshold):
            raise ValueError("OOD distances and thresholds must be finite and nonnegative")
        if sample.squared_mahalanobis <= sample.threshold:
            raise ValueError("Component 0 OOD sample is not a strict exceedance")
        contribution_map = sample.feature_contributions
        if len(contribution_map) != len(names) or set(contribution_map) != expected_keys:
            raise ValueError("sample contributions must exactly match retained features")
        values = []
        for name in names:
            value = contribution_map[name]
            if not _is_finite_nonnegative(value):
                raise ValueError("sample contributions must be finite and nonnegative")
            numeric = float(value)
            contributions_by_feature[name].append(numeric)
            values.append(numeric)
        if not math.isclose(sum(values), sample.squared_mahalanobis, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("sample contributions do not reproduce squared Mahalanobis distance")
        ordered = sorted(names, key=lambda name: (-float(contribution_map[name]), registry_position[name]))
        top1_counts[ordered[0]] += 1
        for name in ordered[:5]:
            top5_counts[name] += 1

    total = sum(sum(values) for values in contributions_by_feature.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("total OOD feature contribution must be positive and finite")
    totals = {name: sum(contributions_by_feature[name]) for name in names}
    ranked_names = tuple(sorted(names, key=lambda name: (-totals[name], registry_position[name])))
    registry_by_name = {spec.name: spec for spec in registry}
    registry_hash = _canonical_registry_sha256(names, registry, registry_schema_version)
    feature_rows = tuple(
        OODFeatureSummaryRow(
            _ANALYSIS_SCOPE,
            0,
            component.component_fingerprint,
            name,
            registry_by_name[name].family,
            registry_schema_version,
            registry_hash,
            totals[name],
            totals[name] / total,
            totals[name] / _OOD_SAMPLE_COUNT,
            median(contributions_by_feature[name]),
            top1_counts[name],
            top1_counts[name] / _OOD_SAMPLE_COUNT,
            top5_counts[name],
            top5_counts[name] / _OOD_SAMPLE_COUNT,
            rank,
        )
        for rank, name in enumerate(ranked_names, start=1)
    )

    family_names = tuple(dict.fromkeys(registry_by_name[name].family for name in names))
    family_rows = []
    for family_name in family_names:
        family_features = tuple(name for name in names if registry_by_name[name].family == family_name)
        family_total = sum(totals[name] for name in family_features)
        family_ratio = family_total / total
        family_rows.append(
            OODFamilySummaryRow(
                _ANALYSIS_SCOPE,
                0,
                component.component_fingerprint,
                family_name,
                family_features,
                registry_schema_version,
                registry_hash,
                family_total,
                family_ratio,
                _VOLATILITY_FAMILY_THRESHOLD,
                family_name == "volatility",
                family_name == "volatility"
                and _meets_threshold(family_ratio, _VOLATILITY_FAMILY_THRESHOLD),
            )
        )
    frozen_families = tuple(family_rows)
    volatility = next((row for row in frozen_families if row.family_name == "volatility"), None)
    return ComponentZeroOODAnalysis(
        _ANALYSIS_SCOPE,
        0,
        component.component_fingerprint,
        _ASSIGNED_SAMPLE_COUNT,
        _OOD_SAMPLE_COUNT,
        registry_schema_version,
        registry_hash,
        feature_rows,
        frozen_families,
        ranked_names[:5],
        _meets_threshold(feature_rows[0].contribution_ratio, _SINGLE_FEATURE_THRESHOLD),
        volatility is not None
        and _meets_threshold(volatility.contribution_ratio, _VOLATILITY_FAMILY_THRESHOLD),
        any(
            _meets_threshold(row.top1_ratio, _RECURRENT_FEATURE_THRESHOLD)
            for row in feature_rows
        ),
    )


def _maximum_ood(rows: Sequence[OffsetOODRow]) -> OffsetOODRow:
    represented = tuple(row for row in rows if row.denominator > 0)
    if not represented:
        raise ValueError("OOD maximum requires at least one represented component")
    return min(
        represented,
        key=lambda row: (
            -float(row.rate),
            -row.numerator,
            -row.denominator,
            row.primary_component_index,
        ),
    )


@dataclass(frozen=True)
class FrozenK4DiagnosisCompletion:
    completion_scope: str
    component_zero_ood: ComponentZeroOODAnalysis
    full_sample_empirical: EmpiricalScopeSummary
    full_sample_ood: tuple[OffsetOODRow, ...]
    offset_empirical: tuple[EmpiricalScopeSummary, ...]
    offset_ood: tuple[OffsetOODRow, ...]
    offset_conclusions: tuple[OffsetConclusion, ...]
    sample_receipts: tuple[FixedSampleReceipt, ...]
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        if self.completion_scope != _COMPLETION_SCOPE or self.diagnostic_only is not True:
            raise ValueError("completion scope must be canonical diagnostic-only")
        collections = (
            self.full_sample_ood,
            self.offset_empirical,
            self.offset_ood,
            self.offset_conclusions,
            self.sample_receipts,
        )
        if any(not isinstance(rows, tuple) for rows in collections):
            raise ValueError("completion collections must be immutable tuples")
        if self.full_sample_empirical.sample_scope != _FULL_SAMPLE_SCOPE:
            raise ValueError("full empirical scope is not canonical")
        expected_keys = tuple(
            (spacing, offset) for spacing in _OFFSET_SPACINGS for offset in range(spacing)
        )
        empirical_keys = tuple((row.spacing_days, row.offset) for row in self.offset_empirical)
        conclusion_keys = tuple((row.spacing_days, row.offset) for row in self.offset_conclusions)
        if empirical_keys != expected_keys or conclusion_keys != expected_keys:
            raise ValueError("completion must contain exactly the ten ordered offset keys")
        if len(self.sample_receipts) != 1641 or tuple(
            row.global_index for row in self.sample_receipts
        ) != tuple(range(1641)):
            raise ValueError("sample receipt global indices must be contiguous")
        anchors = tuple(row.anchor_at for row in self.sample_receipts)
        if tuple(sorted(set(anchors))) != anchors:
            raise ValueError("sample receipt anchors must be strictly chronological")
        if (
            sum(row.half_label == "A" for row in self.sample_receipts) != 820
            or sum(row.half_label == "B" for row in self.sample_receipts) != 821
        ):
            raise ValueError("frozen A/B half receipt counts must be exactly 820/821")
        origin = self.sample_receipts[0].anchor_at
        if any(
            row.offset_origin_anchor != origin
            for row in self.full_sample_empirical.centroid_rows
        ):
            raise ValueError("full empirical origin disagrees with first sample receipt anchor")
        component_fingerprints: dict[int, str] = {}
        for row in self.full_sample_ood:
            if row.sample_scope != _FULL_SAMPLE_SCOPE:
                raise ValueError("full OOD scope is not canonical")
            prior = component_fingerprints.setdefault(
                row.primary_component_index, row.primary_component_fingerprint
            )
            if prior != row.primary_component_fingerprint:
                raise ValueError("primary component fingerprint is inconsistent")
        component_indices = tuple(sorted(component_fingerprints))
        if component_indices != (0, 1, 2, 3):
            raise ValueError("full OOD rows must cover exact frozen K=4 components")
        if tuple(row.primary_component_index for row in self.full_sample_ood) != component_indices:
            raise ValueError("full OOD rows must be unique and component ordered")
        if sum(row.denominator for row in self.full_sample_ood) != len(self.sample_receipts):
            raise ValueError("full OOD denominators do not reconcile with receipts")
        if self.component_zero_ood.primary_component_fingerprint != component_fingerprints.get(0):
            raise ValueError("Component 0 analysis fingerprint disagrees with frozen primary fit")
        pair_fingerprints = {
            (row.half_label, row.half_component_index): (
                row.half_component_fingerprint,
                row.primary_component_index,
                row.primary_component_fingerprint,
            )
            for row in self.full_sample_empirical.centroid_rows
        }
        receipt_counts: dict[tuple[str, int], int] = {}
        for receipt in self.sample_receipts:
            expected_pair = pair_fingerprints.get(
                (receipt.half_label, receipt.half_component_index)
            )
            if expected_pair != (
                receipt.half_component_fingerprint,
                receipt.matched_primary_component_index,
                receipt.matched_primary_component_fingerprint,
            ) or component_fingerprints.get(receipt.primary_component_index) != (
                receipt.primary_component_fingerprint
            ):
                raise ValueError("sample receipt indices or fingerprints are forged")
            identity = (receipt.half_label, receipt.half_component_index)
            receipt_counts[identity] = receipt_counts.get(identity, 0) + 1
        if any(
            receipt_counts.get((row.half_label, row.half_component_index), 0)
            != row.sample_count
            for row in self.full_sample_empirical.centroid_rows
        ):
            raise ValueError("sample receipts do not reconcile with full empirical assignments")
        for full in self.full_sample_ood:
            receipts = tuple(
                row
                for row in self.sample_receipts
                if row.primary_component_index == full.primary_component_index
            )
            if len(receipts) != full.denominator or sum(row.ood_exceeds for row in receipts) != full.numerator:
                raise ValueError("sample receipts do not reconcile with full OOD counts")

        for spacing in _OFFSET_SPACINGS:
            scopes = tuple(row for row in self.offset_empirical if row.spacing_days == spacing)
            if sum(row.selected_sample_count for row in scopes) != len(self.sample_receipts):
                raise ValueError("offset empirical samples do not partition the full sample")
            rows = tuple(row for row in self.offset_ood if row.spacing_days == spacing)
            expected_ood_keys = tuple(
                (offset, component) for offset in range(spacing) for component in component_indices
            )
            if tuple((row.offset, row.primary_component_index) for row in rows) != expected_ood_keys:
                raise ValueError("offset OOD rows are missing, duplicate, or unordered")
            for scope in scopes:
                selected_receipts = tuple(
                    receipt
                    for receipt in self.sample_receipts
                    if receipt.global_index % spacing == scope.offset
                )
                if scope.selected_sample_count != len(selected_receipts):
                    raise ValueError("offset empirical count disagrees with receipt ledger")
                full_identities = {
                    (
                        row.half_label,
                        row.primary_component_index,
                        row.half_component_index,
                    ): (
                        row.primary_component_fingerprint,
                        row.half_component_fingerprint,
                    )
                    for row in self.full_sample_empirical.centroid_rows
                }
                scoped_identities = {
                    (
                        row.half_label,
                        row.primary_component_index,
                        row.half_component_index,
                    )
                    for row in scope.centroid_rows
                }
                if scoped_identities != set(full_identities):
                    raise ValueError("offset empirical rows do not cover canonical full pairs")
                for centroid in scope.centroid_rows:
                    identity = (
                        centroid.half_label,
                        centroid.primary_component_index,
                        centroid.half_component_index,
                    )
                    selected_half = tuple(
                        receipt
                        for receipt in selected_receipts
                        if receipt.half_label == centroid.half_label
                    )
                    expected_count = sum(
                        receipt.half_component_index == centroid.half_component_index
                        and receipt.matched_primary_component_index
                        == centroid.primary_component_index
                        for receipt in selected_half
                    )
                    expected_share = expected_count / len(selected_half) if selected_half else 0.0
                    if (
                        centroid.offset_origin_anchor != origin
                        or centroid.spacing_days != spacing
                        or centroid.offset != scope.offset
                        or centroid.sample_count != expected_count
                        or not math.isclose(
                            centroid.sample_share,
                            expected_share,
                            rel_tol=1e-15,
                            abs_tol=1e-15,
                        )
                        or (
                            centroid.primary_component_fingerprint,
                            centroid.half_component_fingerprint,
                        )
                        != full_identities[identity]
                    ):
                        raise ValueError(
                            "offset empirical origin, counts, shares, or fingerprints disagree with receipt ledger"
                        )
                scope_ood = tuple(
                    row for row in rows if row.offset == scope.offset
                )
                for ood in scope_ood:
                    selected_component = tuple(
                        receipt
                        for receipt in selected_receipts
                        if receipt.primary_component_index == ood.primary_component_index
                    )
                    expected_numerator = sum(
                        receipt.ood_exceeds for receipt in selected_component
                    )
                    expected_denominator = len(selected_component)
                    expected_rate = (
                        None
                        if expected_denominator == 0
                        else expected_numerator / expected_denominator
                    )
                    if (
                        ood.primary_component_fingerprint
                        != component_fingerprints[ood.primary_component_index]
                        or ood.numerator != expected_numerator
                        or ood.denominator != expected_denominator
                        or ood.rate != expected_rate
                    ):
                        raise ValueError("offset OOD row disagrees with receipt ledger")
            for component in component_indices:
                full = next(row for row in self.full_sample_ood if row.primary_component_index == component)
                partitions = tuple(row for row in rows if row.primary_component_index == component)
                if (
                    sum(row.numerator for row in partitions) != full.numerator
                    or sum(row.denominator for row in partitions) != full.denominator
                    or any(row.primary_component_fingerprint != full.primary_component_fingerprint for row in partitions)
                ):
                    raise ValueError("offset OOD partitions do not reconcile with full OOD")
            for full_centroid in self.full_sample_empirical.centroid_rows:
                count = sum(
                    centroid.sample_count
                    for scope in scopes
                    for centroid in scope.centroid_rows
                    if (
                        centroid.half_label,
                        centroid.primary_component_index,
                        centroid.half_component_index,
                    )
                    == (
                        full_centroid.half_label,
                        full_centroid.primary_component_index,
                        full_centroid.half_component_index,
                    )
                )
                if count != full_centroid.sample_count:
                    raise ValueError("offset empirical component counts do not partition full counts")

        full_ood_winner = _maximum_ood(self.full_sample_ood)
        for scope, conclusion in zip(self.offset_empirical, self.offset_conclusions):
            key = (scope.spacing_days, scope.offset)
            offset_rows = tuple(
                row for row in self.offset_ood if (row.spacing_days, row.offset) == key
            )
            ood_winner = _maximum_ood(offset_rows)
            expected = (
                scope.maximum_drift_half_label,
                scope.maximum_drift_primary_component_index,
                scope.maximum_drift_primary_component_fingerprint,
                scope.maximum_drift_half_component_index,
                scope.maximum_drift_half_component_fingerprint,
                ood_winner.primary_component_index,
                ood_winner.primary_component_fingerprint,
                scope.top_five_drift_features,
                (
                    scope.maximum_drift_primary_component_index,
                    scope.maximum_drift_primary_component_fingerprint,
                )
                == (
                    self.full_sample_empirical.maximum_drift_primary_component_index,
                    self.full_sample_empirical.maximum_drift_primary_component_fingerprint,
                ),
                ood_winner.primary_component_index == full_ood_winner.primary_component_index,
                scope.top_five_drift_features == self.full_sample_empirical.top_five_drift_features,
                set(scope.top_five_drift_features) == set(self.full_sample_empirical.top_five_drift_features),
            )
            actual = (
                conclusion.maximum_drift_half_label,
                conclusion.maximum_drift_primary_component_index,
                conclusion.maximum_drift_primary_component_fingerprint,
                conclusion.maximum_drift_half_component_index,
                conclusion.maximum_drift_half_component_fingerprint,
                conclusion.maximum_ood_primary_component_index,
                conclusion.maximum_ood_primary_component_fingerprint,
                conclusion.top_five_drift_features,
                conclusion.drift_component_matches_full_sample,
                conclusion.ood_component_matches_full_sample,
                conclusion.ordered_top5_matches_full_sample,
                conclusion.top5_set_matches_full_sample,
            )
            if actual != expected:
                raise ValueError("offset conclusion fields or flags are forged")


def _aggregate_ood_rows(
    replay: FrozenK4Replay,
    fingerprints: tuple[str, ...],
    indices: tuple[int, ...],
    sample_scope: str,
    spacing: int | None,
    offset: int | None,
) -> tuple[OffsetOODRow, ...]:
    selected = set(indices)
    result = []
    for component, fingerprint in enumerate(fingerprints):
        rows = tuple(
            row
            for index, row in enumerate(replay.primary_ood_rows)
            if index in selected and row.assigned_component_index == component
        )
        numerator = sum(row.exceeds for row in rows)
        denominator = len(rows)
        result.append(
            OffsetOODRow(
                sample_scope,
                spacing,
                offset,
                component,
                fingerprint,
                numerator,
                denominator,
                None if denominator == 0 else numerator / denominator,
            )
        )
    return tuple(result)


def complete_frozen_k4_diagnosis(
    replay: FrozenK4Replay,
    primary_fit: object,
    vectors: tuple[object, ...],
    decomposition: FrozenK4Decomposition,
) -> FrozenK4DiagnosisCompletion:
    """Complete descriptive frozen-K4 diagnostics without fitting or rematching."""
    if not isinstance(decomposition, FrozenK4Decomposition) or decomposition.diagnostic_only is not True:
        raise ValueError("completion requires a frozen diagnostic decomposition")
    if (
        not isinstance(vectors, tuple)
        or len(vectors) != 1641
        or len(replay.primary_assignments) != 1641
        or len(replay.primary_ood_rows) != 1641
    ):
        raise ValueError("frozen completion requires exactly 1,641 vectors, assignments, and OOD rows")
    if (
        tuple(getattr(half.receipt, "half_label", None) for half in replay.half_replays)
        != ("A", "B")
        or tuple(getattr(half.receipt, "anchor_count", None) for half in replay.half_replays)
        != (820, 821)
        or tuple(len(half.assignments) for half in replay.half_replays) != (820, 821)
    ):
        raise ValueError("frozen half receipt counts must be exact A=820 and B=821")
    full_empirical = build_full_sample_empirical_reference(replay, primary_fit, vectors)
    fingerprints = getattr(primary_fit, "fingerprints", None)
    if not isinstance(fingerprints, tuple) or len(fingerprints) != 4:
        raise ValueError("primary fingerprints must identify exact frozen K=4")
    component_zero = summarize_component_zero_ood(
        decomposition,
        retained_feature_names=primary_fit.feature_names,
        registry=THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    )
    if component_zero.primary_component_fingerprint != fingerprints[0]:
        raise ValueError("Component 0 decomposition fingerprint disagrees with primary fit")

    receipts: list[FixedSampleReceipt] = []
    cursor = 0
    for half in replay.half_replays:
        label = half.receipt.half_label
        pairs = {pair.half_component_index: pair for pair in half.matched_pairs}
        half_fingerprints = half.fit.fingerprints
        for local, half_component in enumerate(half.assignments):
            index = cursor + local
            vector = vectors[index]
            primary_component = replay.primary_assignments[index]
            ood = replay.primary_ood_rows[index]
            pair = pairs.get(half_component)
            anchor = _anchor_string(vector.anchor_at)
            if pair is None:
                raise ValueError("half assignment has no fixed matched pair")
            if (
                ood.anchor_at != anchor
                or ood.assigned_component_index != primary_component
                or ood.assigned_component_fingerprint != fingerprints[primary_component]
                or getattr(ood, "comparison_operator", ">") != ">"
                or ood.exceeds is not (ood.squared_mahalanobis > ood.threshold)
                or pair.half_component_fingerprint != half_fingerprints[half_component]
                or pair.primary_component_fingerprint != fingerprints[pair.primary_component_index]
            ):
                raise ValueError("fixed sample assignment, OOD, or fingerprint provenance disagrees")
            receipts.append(
                FixedSampleReceipt(
                    index,
                    anchor,
                    label,
                    half_component,
                    half_fingerprints[half_component],
                    pair.primary_component_index,
                    pair.primary_component_fingerprint,
                    primary_component,
                    fingerprints[primary_component],
                    ood.squared_mahalanobis,
                    ood.threshold,
                    ood.exceeds,
                )
            )
        cursor += len(half.assignments)
    if cursor != len(vectors):
        raise ValueError("fixed half assignments do not cover every global anchor")

    full_ood = _aggregate_ood_rows(
        replay, fingerprints, tuple(range(len(vectors))), _FULL_SAMPLE_SCOPE, None, None
    )
    component_zero_full = full_ood[0]
    if (
        component_zero_full.denominator != component_zero.assigned_sample_count
        or component_zero_full.numerator != component_zero.ood_sample_count
    ):
        raise ValueError("existing replay does not reproduce Component 0 24/409 population")
    replay_component_zero_exceedances = {
        row.anchor_at
        for row in replay.primary_ood_rows
        if row.assigned_component_index == 0 and row.exceeds
    }
    decomposition_component_zero_exceedances = {
        row.anchor_at for row in decomposition.ood_samples if row.component_index == 0
    }
    if replay_component_zero_exceedances != decomposition_component_zero_exceedances:
        raise ValueError("Component 0 OOD samples disagree between replay and decomposition")
    receipt_by_anchor = {receipt.anchor_at: receipt for receipt in receipts}
    if any(
        receipt_by_anchor[row.anchor_at].squared_mahalanobis != row.squared_mahalanobis
        or receipt_by_anchor[row.anchor_at].ood_threshold != row.threshold
        for row in decomposition.ood_samples
        if row.component_index == 0
    ):
        raise ValueError("Component 0 OOD distance or threshold disagrees with existing replay row")
    full_ood_winner = _maximum_ood(full_ood)
    primary_scaled = _primary_scaled_matrix(primary_fit, vectors)
    offset_empirical: list[EmpiricalScopeSummary] = []
    offset_ood: list[OffsetOODRow] = []
    conclusions: list[OffsetConclusion] = []
    for spacing in _OFFSET_SPACINGS:
        for offset in range(spacing):
            indices = _global_offset_indices(len(vectors), spacing, offset)
            scope = _build_empirical_scope(
                replay,
                primary_fit,
                vectors,
                primary_scaled,
                indices,
                "offset_subsample",
                spacing,
                offset,
            )
            ood_rows = _aggregate_ood_rows(
                replay, fingerprints, indices, "offset_subsample", spacing, offset
            )
            ood_winner = _maximum_ood(ood_rows)
            offset_empirical.append(scope)
            offset_ood.extend(ood_rows)
            conclusions.append(
                OffsetConclusion(
                    spacing,
                    offset,
                    scope.maximum_drift_half_label,
                    scope.maximum_drift_primary_component_index,
                    scope.maximum_drift_primary_component_fingerprint,
                    scope.maximum_drift_half_component_index,
                    scope.maximum_drift_half_component_fingerprint,
                    ood_winner.primary_component_index,
                    ood_winner.primary_component_fingerprint,
                    scope.top_five_drift_features,
                    (
                        scope.maximum_drift_primary_component_index,
                        scope.maximum_drift_primary_component_fingerprint,
                    )
                    == (
                        full_empirical.maximum_drift_primary_component_index,
                        full_empirical.maximum_drift_primary_component_fingerprint,
                    ),
                    ood_winner.primary_component_index == full_ood_winner.primary_component_index,
                    scope.top_five_drift_features == full_empirical.top_five_drift_features,
                    set(scope.top_five_drift_features) == set(full_empirical.top_five_drift_features),
                )
            )
    return FrozenK4DiagnosisCompletion(
        _COMPLETION_SCOPE,
        component_zero,
        full_empirical,
        full_ood,
        tuple(offset_empirical),
        tuple(offset_ood),
        tuple(conclusions),
        tuple(receipts),
    )


__all__ = [
    "ComponentZeroOODAnalysis",
    "EmpiricalCentroidRow",
    "EmpiricalFeatureContributionRow",
    "EmpiricalScopeSummary",
    "FixedSampleReceipt",
    "FrozenK4DiagnosisCompletion",
    "OODFamilySummaryRow",
    "OODFeatureSummaryRow",
    "OffsetConclusion",
    "OffsetOODRow",
    "build_full_sample_empirical_reference",
    "complete_frozen_k4_diagnosis",
    "summarize_component_zero_ood",
]
