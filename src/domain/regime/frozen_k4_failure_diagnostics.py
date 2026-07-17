"""Immutable contracts for the frozen K4 failure diagnosis.

These payloads describe diagnostic evidence only.  They deliberately contain
no runtime model object and provide no path for replacing the frozen primary
model, scaler, clipping bounds, or feature registry.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
import struct
from types import MappingProxyType
from typing import Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPONENT_FINGERPRINT = re.compile(r"^[0-9a-f]{24}$")
_HALF_LABELS = ("A", "B")
_ASSIGNMENT_SOURCE = "frozen_reproduced_half_assignment"
_FROZEN_HALF_RANGES = MappingProxyType(
    {
        "A": ("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
        "B": ("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z"),
    }
)
_FROZEN_HALF_ANCHOR_COUNTS = MappingProxyType({"A": 820, "B": 821})
_SUCCESS_ARTIFACT_FILENAMES = frozenset(
    {
        "frozen_k4_failure_reproduction.json",
        "frozen_k4_cluster_diagnostics.csv",
        "frozen_k4_feature_contributions.csv",
        "frozen_k4_ood_samples.csv",
        "frozen_k4_distance_comparison.csv",
        "frozen_k4_failure_diagnosis.md",
    }
)
_MISMATCH_ARTIFACT_FILENAMES = frozenset(
    {
        "frozen_k4_failure_reproduction.json",
        "frozen_k4_failure_diagnosis.md",
    }
)
_MISMATCH_CLASSIFICATIONS = (
    "input-data-mismatch",
    "split-boundary-mismatch",
    "preprocessing-mismatch",
    "dependency-version-nondeterminism",
    "gmm-fitting-nondeterminism",
    "projection-mismatch",
    "matching-mismatch",
    "original-metric-provenance-incomplete",
)


def _canonical_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical SHA-256")
    return value


def _canonical_timestamp(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field_name} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{field_name} must be a canonical UTC timestamp") from error
    if (
        parsed.tzinfo != timezone.utc
        or parsed.microsecond != 0
        or parsed.isoformat(timespec="seconds").replace("+00:00", "Z") != value
    ):
        raise ValueError(f"{field_name} must be a canonical UTC timestamp")
    return value


def _half_label(value: object) -> str:
    if value not in _HALF_LABELS:
        raise ValueError("half label must be A or B")
    return value


def _finite(value: object, field_name: str, *, nonnegative: bool = False) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{field_name} must be finite") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    if nonnegative and number < 0:
        raise ValueError(f"{field_name} must be nonnegative")
    return number


def _nonnegative_integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} values must be nonnegative integers")
    return value


def _component_fingerprint(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _COMPONENT_FINGERPRINT.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be exactly 24 lowercase hexadecimal characters"
        )
    return value


def _component_index(value: object, field_name: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= 3
    ):
        raise ValueError(f"{field_name} must be an integer from 0 through 3")
    return value


@dataclass(frozen=True)
class MetricReproduction:
    expected_value: float
    reproduced_value: float
    exact_bit_match: bool
    numeric_tolerance_match: bool
    absolute_error: float
    relative_error: float

    def __post_init__(self) -> None:
        expected = _finite(self.expected_value, "expected value")
        reproduced = _finite(self.reproduced_value, "reproduced value")
        absolute = _finite(self.absolute_error, "absolute error", nonnegative=True)
        relative = _finite(self.relative_error, "relative error", nonnegative=True)
        if not isinstance(self.exact_bit_match, bool) or not isinstance(
            self.numeric_tolerance_match, bool
        ):
            raise ValueError("reproduction match indicators must be booleans")

        computed_absolute = abs(reproduced - expected)
        computed_relative = computed_absolute / abs(expected) if expected else computed_absolute
        computed_exact = struct.pack(">d", expected) == struct.pack(">d", reproduced)
        computed_tolerance = math.isclose(
            reproduced,
            expected,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        if (
            absolute != computed_absolute
            or relative != computed_relative
            or self.exact_bit_match is not computed_exact
            or self.numeric_tolerance_match is not computed_tolerance
        ):
            raise ValueError("reproduction fields do not match the compared values")
        object.__setattr__(self, "expected_value", expected)
        object.__setattr__(self, "reproduced_value", reproduced)
        object.__setattr__(self, "absolute_error", absolute)
        object.__setattr__(self, "relative_error", relative)

    @classmethod
    def compare(cls, expected: float, reproduced: float) -> "MetricReproduction":
        expected_number = _finite(expected, "expected value")
        reproduced_number = _finite(reproduced, "reproduced value")
        exact = struct.pack(">d", expected_number) == struct.pack(">d", reproduced_number)
        absolute = abs(reproduced_number - expected_number)
        relative = absolute / abs(expected_number) if expected_number else absolute
        return cls(
            expected_number,
            reproduced_number,
            exact,
            math.isclose(
                reproduced_number,
                expected_number,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ),
            absolute,
            relative,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "expected_value": self.expected_value,
            "reproduced_value": self.reproduced_value,
            "exact_bit_match": self.exact_bit_match,
            "numeric_tolerance_match": self.numeric_tolerance_match,
            "absolute_error": self.absolute_error,
            "relative_error": self.relative_error,
        }


@dataclass(frozen=True)
class FrozenK4InputIdentity:
    failed_model_attempt_sha256: str
    model_file_sha256: str
    primary_parameters_sha256: str
    scaler_sha256: str
    clipping_bounds_sha256: str
    feature_schema_sha256: str
    source_provenance_sha256: str
    source_anchor_manifest_sha256: str
    feature_vectors_sha256: str
    dependency_metadata_sha256: str
    split_at: str
    half_a_range: tuple[str, str]
    half_b_range: tuple[str, str]

    def __post_init__(self) -> None:
        for field_name in (
            "failed_model_attempt_sha256",
            "model_file_sha256",
            "primary_parameters_sha256",
            "scaler_sha256",
            "clipping_bounds_sha256",
            "feature_schema_sha256",
            "source_provenance_sha256",
            "source_anchor_manifest_sha256",
            "feature_vectors_sha256",
            "dependency_metadata_sha256",
        ):
            _canonical_sha256(getattr(self, field_name), field_name)
        split_at = _canonical_timestamp(self.split_at, "split_at")
        for field_name in ("half_a_range", "half_b_range"):
            interval = getattr(self, field_name)
            if not isinstance(interval, tuple) or len(interval) != 2:
                raise ValueError(f"{field_name} must be an immutable half-open range")
            start = _canonical_timestamp(interval[0], f"{field_name} start")
            end = _canonical_timestamp(interval[1], f"{field_name} end")
            if start >= end:
                raise ValueError(f"{field_name} must have positive width")
        if self.half_a_range[1] != split_at or self.half_b_range[0] != split_at:
            raise ValueError("half ranges must meet exactly at split_at")
        if self.half_a_range[0] >= self.half_b_range[1]:
            raise ValueError("half ranges must be chronologically ordered")
        if (
            self.half_a_range != _FROZEN_HALF_RANGES["A"]
            or self.half_b_range != _FROZEN_HALF_RANGES["B"]
        ):
            raise ValueError("identity must use the exact frozen half ranges")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "failed_model_attempt_sha256": self.failed_model_attempt_sha256,
            "model_file_sha256": self.model_file_sha256,
            "primary_parameters_sha256": self.primary_parameters_sha256,
            "scaler_sha256": self.scaler_sha256,
            "clipping_bounds_sha256": self.clipping_bounds_sha256,
            "feature_schema_sha256": self.feature_schema_sha256,
            "source_provenance_sha256": self.source_provenance_sha256,
            "source_anchor_manifest_sha256": self.source_anchor_manifest_sha256,
            "feature_vectors_sha256": self.feature_vectors_sha256,
            "dependency_metadata_sha256": self.dependency_metadata_sha256,
            "split_at": self.split_at,
            "half_a_range": tuple(self.half_a_range),
            "half_b_range": tuple(self.half_b_range),
        }


@dataclass(frozen=True)
class HalfFitReceipt:
    half_label: str
    anchor_count: int
    fit_sha256: str
    anchor_range: tuple[str, str] | None = None
    diagnostic_only: bool = True
    primary_replacement_allowed: bool = False

    def __post_init__(self) -> None:
        half_label = _half_label(self.half_label)
        _nonnegative_integer(self.anchor_count, "anchor count")
        _canonical_sha256(self.fit_sha256, "fit_sha256")
        expected_range = _FROZEN_HALF_RANGES[half_label]
        anchor_range = expected_range if self.anchor_range is None else self.anchor_range
        if not isinstance(anchor_range, tuple) or len(anchor_range) != 2:
            raise ValueError("half fit receipt requires an immutable frozen half range")
        for index, boundary in enumerate(anchor_range):
            _canonical_timestamp(boundary, f"anchor_range[{index}]")
        if (
            self.anchor_count != _FROZEN_HALF_ANCHOR_COUNTS[half_label]
            or anchor_range != expected_range
        ):
            raise ValueError("half fit receipt count and range must match its frozen half")
        if self.diagnostic_only is not True:
            raise ValueError("half fit receipt must be diagnostic-only")
        if self.primary_replacement_allowed is not False:
            raise ValueError("diagnostic half fit cannot replace the primary model")
        object.__setattr__(self, "anchor_range", tuple(anchor_range))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "half_label": self.half_label,
            "anchor_count": self.anchor_count,
            "fit_sha256": self.fit_sha256,
            "anchor_range": tuple(self.anchor_range),
            "diagnostic_only": self.diagnostic_only,
            "primary_replacement_allowed": self.primary_replacement_allowed,
        }


@dataclass(frozen=True)
class MatchedPair:
    half_label: str
    primary_component_fingerprint: str
    half_component_fingerprint: str
    primary_component_index: int
    half_component_index: int
    matching_cost: float
    euclidean_distance: float

    def __post_init__(self) -> None:
        _half_label(self.half_label)
        _component_fingerprint(
            self.primary_component_fingerprint, "primary component fingerprint"
        )
        _component_fingerprint(
            self.half_component_fingerprint, "half component fingerprint"
        )
        _component_index(self.primary_component_index, "primary component index")
        _component_index(self.half_component_index, "half component index")
        matching_cost = _finite(self.matching_cost, "matching cost", nonnegative=True)
        euclidean_distance = _finite(
            self.euclidean_distance, "euclidean distance", nonnegative=True
        )
        object.__setattr__(self, "matching_cost", matching_cost)
        object.__setattr__(self, "euclidean_distance", euclidean_distance)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "half_label": self.half_label,
            "primary_component_fingerprint": self.primary_component_fingerprint,
            "half_component_fingerprint": self.half_component_fingerprint,
            "primary_component_index": self.primary_component_index,
            "half_component_index": self.half_component_index,
            "matching_cost": self.matching_cost,
            "euclidean_distance": self.euclidean_distance,
        }


@dataclass(frozen=True)
class OODRow:
    anchor_at: str
    assigned_component_index: int
    assigned_component_fingerprint: str
    squared_mahalanobis: float
    threshold: float
    exceeds: bool
    comparison_operator: str = ">"

    def __post_init__(self) -> None:
        _canonical_timestamp(self.anchor_at, "anchor_at")
        _component_index(self.assigned_component_index, "assigned component index")
        _component_fingerprint(
            self.assigned_component_fingerprint, "assigned component fingerprint"
        )
        distance = _finite(
            self.squared_mahalanobis, "squared Mahalanobis distance", nonnegative=True
        )
        threshold = _finite(self.threshold, "OOD threshold", nonnegative=True)
        if self.comparison_operator != ">":
            raise ValueError("OOD comparison operator must be strict >")
        if not isinstance(self.exceeds, bool) or self.exceeds is not (distance > threshold):
            raise ValueError("OOD exceeds flag must use the strict > comparison")
        object.__setattr__(self, "squared_mahalanobis", distance)
        object.__setattr__(self, "threshold", threshold)

    @classmethod
    def classify(
        cls,
        *,
        anchor_at: str,
        assigned_component_index: int,
        assigned_component_fingerprint: str,
        squared_mahalanobis: float,
        threshold: float,
    ) -> "OODRow":
        distance = _finite(
            squared_mahalanobis, "squared Mahalanobis distance", nonnegative=True
        )
        threshold_number = _finite(threshold, "OOD threshold", nonnegative=True)
        return cls(
            anchor_at=anchor_at,
            assigned_component_index=assigned_component_index,
            assigned_component_fingerprint=assigned_component_fingerprint,
            squared_mahalanobis=distance,
            threshold=threshold_number,
            exceeds=distance > threshold_number,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "anchor_at": self.anchor_at,
            "assigned_component_index": self.assigned_component_index,
            "assigned_component_fingerprint": self.assigned_component_fingerprint,
            "squared_mahalanobis": self.squared_mahalanobis,
            "threshold": self.threshold,
            "comparison_operator": self.comparison_operator,
            "exceeds": self.exceeds,
        }


@dataclass(frozen=True)
class SensitivityRow:
    half_label: str
    component_fingerprint: str
    statistic: str
    excluded_count: int
    centroid_distance: float
    assignment_source: str = _ASSIGNMENT_SOURCE
    refit_after_exclusion: bool = False
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        _half_label(self.half_label)
        _component_fingerprint(self.component_fingerprint, "component fingerprint")
        if (
            not isinstance(self.statistic, str)
            or not self.statistic
            or self.statistic != self.statistic.strip()
        ):
            raise ValueError("sensitivity statistic must be nonblank and canonical")
        _nonnegative_integer(self.excluded_count, "excluded count")
        centroid_distance = _finite(
            self.centroid_distance, "centroid distance", nonnegative=True
        )
        if self.assignment_source != _ASSIGNMENT_SOURCE:
            raise ValueError("sensitivity assignment source must remain frozen")
        if self.refit_after_exclusion is not False:
            raise ValueError("sensitivity row cannot claim a refit")
        if self.diagnostic_only is not True:
            raise ValueError("sensitivity row must be diagnostic-only")
        object.__setattr__(self, "centroid_distance", centroid_distance)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "half_label": self.half_label,
            "component_fingerprint": self.component_fingerprint,
            "statistic": self.statistic,
            "excluded_count": self.excluded_count,
            "centroid_distance": self.centroid_distance,
            "assignment_source": self.assignment_source,
            "refit_after_exclusion": self.refit_after_exclusion,
            "diagnostic_only": self.diagnostic_only,
        }


@dataclass(frozen=True)
class DiagnosisStatus:
    status: str
    temporal_half_refit_stability_reproduction: MetricReproduction
    primary_model_ood_reproduction: MetricReproduction
    ood_exceedance_numerator: int
    ood_denominator: int
    decomposition_allowed: bool
    mismatch_classification: str | None = None
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        if self.status not in ("reproduced", "reproduction_mismatch"):
            raise ValueError("diagnosis status is unsupported")
        if not isinstance(
            self.temporal_half_refit_stability_reproduction, MetricReproduction
        ) or not isinstance(self.primary_model_ood_reproduction, MetricReproduction):
            raise ValueError("diagnosis status requires both reproduction receipts")
        numerator = _nonnegative_integer(
            self.ood_exceedance_numerator, "OOD numerator"
        )
        denominator = _nonnegative_integer(self.ood_denominator, "OOD denominator")
        if denominator == 0 or numerator > denominator:
            raise ValueError("OOD numerator/denominator must form a valid fraction")
        if not math.isclose(
            numerator / denominator,
            self.primary_model_ood_reproduction.reproduced_value,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("OOD numerator/denominator must reproduce the OOD rate")
        both_match = (
            self.temporal_half_refit_stability_reproduction.numeric_tolerance_match
            and self.primary_model_ood_reproduction.numeric_tolerance_match
        )
        if self.status == "reproduced":
            if not both_match or self.decomposition_allowed is not True:
                raise ValueError("decomposition requires both reproductions to match")
            if self.mismatch_classification is not None:
                raise ValueError("a reproduced diagnosis cannot have a mismatch classification")
        else:
            if both_match or self.decomposition_allowed is not False:
                raise ValueError("a reproduction mismatch must keep decomposition closed")
            if self.mismatch_classification not in _MISMATCH_CLASSIFICATIONS:
                raise ValueError("reproduction mismatch classification is unsupported")
        if self.diagnostic_only is not True:
            raise ValueError("diagnosis status must be diagnostic-only")

    @classmethod
    def reproduced(
        cls,
        temporal: MetricReproduction,
        primary_ood: MetricReproduction,
        ood_exceedance_numerator: int,
        ood_denominator: int,
    ) -> "DiagnosisStatus":
        return cls(
            status="reproduced",
            temporal_half_refit_stability_reproduction=temporal,
            primary_model_ood_reproduction=primary_ood,
            ood_exceedance_numerator=ood_exceedance_numerator,
            ood_denominator=ood_denominator,
            decomposition_allowed=True,
        )

    @classmethod
    def mismatch(
        cls,
        temporal: MetricReproduction,
        primary_ood: MetricReproduction,
        ood_exceedance_numerator: int,
        ood_denominator: int,
        mismatch_classification: str,
    ) -> "DiagnosisStatus":
        return cls(
            status="reproduction_mismatch",
            temporal_half_refit_stability_reproduction=temporal,
            primary_model_ood_reproduction=primary_ood,
            ood_exceedance_numerator=ood_exceedance_numerator,
            ood_denominator=ood_denominator,
            decomposition_allowed=False,
            mismatch_classification=mismatch_classification,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "temporal_half_refit_stability_reproduction": (
                self.temporal_half_refit_stability_reproduction.canonical_payload()
            ),
            "primary_model_ood_reproduction": (
                self.primary_model_ood_reproduction.canonical_payload()
            ),
            "ood_exceedance_numerator": self.ood_exceedance_numerator,
            "ood_denominator": self.ood_denominator,
            "decomposition_allowed": self.decomposition_allowed,
            "mismatch_classification": self.mismatch_classification,
            "diagnostic_only": self.diagnostic_only,
        }


@dataclass(frozen=True)
class FrozenK4DiagnosisManifest:
    run_id: str
    input_identity_sha256: str
    status: str
    file_sha256: Mapping[str, str] = field(default_factory=dict)
    diagnostic_only: bool = True
    primary_replacement_allowed: bool = False

    def __post_init__(self) -> None:
        _canonical_sha256(self.run_id, "run_id")
        _canonical_sha256(self.input_identity_sha256, "input_identity_sha256")
        if self.status not in ("reproduced", "reproduction_mismatch"):
            raise ValueError("manifest status is unsupported")
        if not isinstance(self.file_sha256, Mapping):
            raise ValueError("manifest file hashes must be a mapping")
        copied: dict[str, str] = {}
        for name, value in self.file_sha256.items():
            if (
                not isinstance(name, str)
                or not name
                or name != name.strip()
                or "/" in name
                or "\\" in name
                or name in (".", "..")
            ):
                raise ValueError("manifest file names must be canonical basenames")
            copied[name] = _canonical_sha256(value, f"file_sha256[{name}]")
        expected_filenames = (
            _SUCCESS_ARTIFACT_FILENAMES
            if self.status == "reproduced"
            else _MISMATCH_ARTIFACT_FILENAMES
        )
        if set(copied) != expected_filenames:
            raise ValueError(
                "manifest artifact filename set must exactly match diagnosis status"
            )
        if self.diagnostic_only is not True:
            raise ValueError("diagnosis manifest must be diagnostic-only")
        if self.primary_replacement_allowed is not False:
            raise ValueError("diagnosis manifest cannot replace the primary model")
        object.__setattr__(
            self,
            "file_sha256",
            MappingProxyType(dict(sorted(copied.items()))),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "input_identity_sha256": self.input_identity_sha256,
            "status": self.status,
            "file_sha256": dict(self.file_sha256),
            "diagnostic_only": self.diagnostic_only,
            "primary_replacement_allowed": self.primary_replacement_allowed,
        }


__all__ = [
    "DiagnosisStatus",
    "FrozenK4DiagnosisManifest",
    "FrozenK4InputIdentity",
    "HalfFitReceipt",
    "MatchedPair",
    "MetricReproduction",
    "OODRow",
    "SensitivityRow",
]
