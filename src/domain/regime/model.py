from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Literal

from src.domain.regime.chart_features import (
    CHART_FEATURE_REGISTRY_V1,
    CHART_FEATURE_SCHEMA_VERSION,
)


REGIME_MODEL_ARTIFACT_VERSION = "regime-model-v1"
_REGISTRY_NAMES = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)


@dataclass(frozen=True)
class RegimeModelConfig:
    model_type: Literal["kmeans", "gmm"]
    cluster_count: int
    random_seed: int = 20260714
    covariance_type: Literal["diag", "tied"] | None = None
    regularization: float = 1e-6

    def __post_init__(self) -> None:
        if self.model_type not in {"kmeans", "gmm"}:
            raise ValueError("model type must be kmeans or gmm")
        if not isinstance(self.cluster_count, int) or isinstance(self.cluster_count, bool):
            raise ValueError("cluster count must be an integer")
        if not 3 <= self.cluster_count <= 8:
            raise ValueError("cluster count must be between 3 and 8")
        if not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool):
            raise ValueError("random seed must be an integer")
        if not 0 <= self.random_seed <= 2**32 - 1:
            raise ValueError("random seed must be between 0 and 2**32 - 1")
        if self.model_type == "kmeans" and self.covariance_type is not None:
            raise ValueError("kmeans covariance type must be None")
        if self.model_type == "gmm" and self.covariance_type not in {"diag", "tied"}:
            raise ValueError("gmm covariance type must be diag or tied")
        if not math.isfinite(self.regularization) or self.regularization <= 0:
            raise ValueError("regularization must be finite and positive")


@dataclass(frozen=True)
class ClusterAssignment:
    fingerprint: str
    dominant_probability: float
    second_probability: float
    distance: float | None

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raise ValueError("assignment fingerprint is required")
        probabilities = (self.dominant_probability, self.second_probability)
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in probabilities
        ):
            raise ValueError("assignment probabilities must be finite and between zero and one")
        if self.second_probability > self.dominant_probability:
            raise ValueError("second probability cannot exceed dominant probability")
        # Permit only representational noise around a mathematically valid sum.
        if math.fsum(probabilities) > 1.0 + 1e-12:
            raise ValueError("top-two assignment probability sum cannot exceed one")
        if self.distance is not None and (
            not isinstance(self.distance, (int, float))
            or isinstance(self.distance, bool)
            or not math.isfinite(self.distance)
            or self.distance < 0
        ):
            raise ValueError("assignment distance must be finite and nonnegative")


@dataclass(frozen=True)
class RegimeModelArtifact:
    artifact_version: str
    symbol: str
    feature_schema_version: str
    config: RegimeModelConfig
    feature_names: tuple[str, ...]
    lower_bounds: tuple[float, ...]
    upper_bounds: tuple[float, ...]
    medians: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    means: tuple[tuple[float, ...], ...]
    covariances: tuple[tuple[float, ...], ...]
    fingerprints: tuple[str, ...]
    training_start_at: datetime
    training_end_at: datetime
    distance_thresholds: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.artifact_version != REGIME_MODEL_ARTIFACT_VERSION:
            raise ValueError("unsupported regime model artifact version")
        if not self.symbol or self.symbol != self.symbol.strip():
            raise ValueError("artifact symbol is required and canonical")
        if self.feature_schema_version != CHART_FEATURE_SCHEMA_VERSION:
            raise ValueError("artifact feature schema version is incompatible")
        if not self.feature_names or any(name not in _REGISTRY_NAMES for name in self.feature_names):
            raise ValueError("artifact contains unknown or empty feature names")
        registry_positions = tuple(_REGISTRY_NAMES.index(name) for name in self.feature_names)
        if len(set(self.feature_names)) != len(self.feature_names) or registry_positions != tuple(sorted(registry_positions)):
            raise ValueError("artifact feature names must be unique and in registry order")

        feature_count = len(self.feature_names)
        cluster_count = self.config.cluster_count
        if any(
            len(values) != feature_count
            for values in (self.lower_bounds, self.upper_bounds, self.medians, self.scales)
        ):
            raise ValueError("artifact preprocessing shape is inconsistent")
        if len(self.weights) != cluster_count or len(self.means) != cluster_count:
            raise ValueError("artifact component shape is inconsistent")
        if any(len(row) != feature_count for row in self.means):
            raise ValueError("artifact mean shape is inconsistent")
        if len(self.fingerprints) != cluster_count or len(set(self.fingerprints)) != cluster_count:
            raise ValueError("artifact fingerprints must be unique per component")
        if tuple(sorted(self.fingerprints)) != self.fingerprints:
            raise ValueError("artifact components must be sorted by fingerprint")
        if any(value <= 0 for value in self.scales):
            raise ValueError("artifact scales must be positive")
        if any(lower >= upper for lower, upper in zip(self.lower_bounds, self.upper_bounds)):
            raise ValueError("artifact clipping bounds must have positive width")
        if any(value <= 0 for value in self.weights) or not math.isclose(sum(self.weights), 1.0, rel_tol=1e-8, abs_tol=1e-8):
            raise ValueError("artifact weights must be positive and sum to one")

        numeric_groups = (
            self.lower_bounds,
            self.upper_bounds,
            self.medians,
            self.scales,
            self.weights,
            *(self.means),
            *(self.covariances),
            self.distance_thresholds,
        )
        if any(not math.isfinite(value) for group in numeric_groups for value in group):
            raise ValueError("artifact numeric parameters must be finite")

        if self.config.model_type == "kmeans":
            if self.covariances:
                raise ValueError("kmeans artifact cannot contain covariances")
            if len(self.distance_thresholds) != cluster_count or any(value < 0 for value in self.distance_thresholds):
                raise ValueError("kmeans artifact requires nonnegative distance thresholds")
        else:
            expected_covariance_width = feature_count if self.config.covariance_type == "diag" else feature_count * feature_count
            if len(self.covariances) != cluster_count or any(len(row) != expected_covariance_width for row in self.covariances):
                raise ValueError("gmm covariance shape is inconsistent")
            if self.config.covariance_type == "diag":
                if any(
                    _below_regularization_floor(value, self.config.regularization)
                    for row in self.covariances
                    for value in row
                ):
                    raise ValueError("gmm covariance is below the configured regularization floor")
            else:
                shared = self.covariances[0]
                if any(
                    any(
                        not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-15)
                        for actual, expected in zip(row, shared)
                    )
                    for row in self.covariances[1:]
                ):
                    raise ValueError("tied gmm artifact must repeat one shared covariance")
                _validate_tied_covariance(shared, feature_count, self.config.regularization)
            if self.distance_thresholds:
                raise ValueError("gmm artifact cannot contain distance thresholds")

        expected_fingerprints = tuple(
            component_fingerprint(
                model_type=self.config.model_type,
                feature_schema_version=self.feature_schema_version,
                feature_names=self.feature_names,
                mean=mean,
                covariance=() if self.config.model_type == "kmeans" else self.covariances[index],
                weight=None if self.config.model_type == "kmeans" else self.weights[index],
            )
            for index, mean in enumerate(self.means)
        )
        if self.fingerprints != expected_fingerprints:
            raise ValueError("artifact component fingerprint does not match persisted parameters")
        if not _canonical_utc(self.training_start_at) or not _canonical_utc(self.training_end_at):
            raise ValueError("artifact training range must use canonical UTC")
        if self.training_end_at < self.training_start_at:
            raise ValueError("artifact training range must be ordered")


def _canonical_utc(value: datetime) -> bool:
    return value.tzinfo is timezone.utc


def component_fingerprint(
    *,
    model_type: str,
    feature_schema_version: str,
    feature_names: tuple[str, ...],
    mean: tuple[float, ...],
    covariance: tuple[float, ...],
    weight: float | None,
) -> str:
    payload = {
        "model_type": model_type,
        "feature_schema_version": feature_schema_version,
        "feature_names": list(feature_names),
        "mean": list(mean),
        "covariance": list(covariance),
        "weight": weight,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _below_regularization_floor(value: float, regularization: float) -> bool:
    tolerance = max(regularization * 1e-12, math.ulp(max(1.0, regularization)))
    return value + tolerance < regularization


def _validate_tied_covariance(
    flattened: tuple[float, ...],
    width: int,
    regularization: float,
) -> None:
    matrix = tuple(
        tuple(flattened[row * width + column] for column in range(width))
        for row in range(width)
    )
    if any(
        not math.isclose(matrix[row][column], matrix[column][row], rel_tol=1e-12, abs_tol=1e-15)
        for row in range(width)
        for column in range(row + 1, width)
    ):
        raise ValueError("tied gmm covariance must be symmetric")

    # Cholesky on A - (floor - tolerance)I proves every eigenvalue is at
    # least the configured floor, while allowing only round-off at equality.
    tolerance = max(regularization * 1e-12, math.ulp(max(1.0, regularization)))
    shifted = [
        [
            matrix[row][column] - (regularization - tolerance if row == column else 0.0)
            for column in range(width)
        ]
        for row in range(width)
    ]
    lower = [[0.0] * width for _ in range(width)]
    for row in range(width):
        for column in range(row + 1):
            residual = shifted[row][column] - sum(
                lower[row][index] * lower[column][index]
                for index in range(column)
            )
            if row == column:
                if residual <= 0 or not math.isfinite(residual):
                    raise ValueError("tied gmm covariance is below the configured regularization floor")
                lower[row][column] = math.sqrt(residual)
            else:
                lower[row][column] = residual / lower[column][column]


__all__ = [
    "REGIME_MODEL_ARTIFACT_VERSION",
    "ClusterAssignment",
    "RegimeModelArtifact",
    "RegimeModelConfig",
    "component_fingerprint",
]
