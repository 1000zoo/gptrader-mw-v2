from dataclasses import dataclass
import math

from src.domain.regime.model import (
    RegimeModelConfig,
    _below_regularization_floor,
    _validate_tied_covariance,
    component_fingerprint,
)


@dataclass(frozen=True)
class ClusterDiagnosticFit:
    """Schema-neutral clustering parameters that cannot be loaded by runtime."""

    schema_version: str
    symbol: str
    config: RegimeModelConfig
    feature_names: tuple[str, ...]
    lower_bounds: tuple[float, ...]
    upper_bounds: tuple[float, ...]
    medians: tuple[float, ...]
    scales: tuple[float, ...]
    fingerprints: tuple[str, ...]
    means: tuple[tuple[float, ...], ...]
    weights: tuple[float, ...]
    covariances: tuple[tuple[float, ...], ...]
    distance_thresholds: tuple[float, ...]
    converged: bool = True
    iterations: int = 1
    lower_bound: float = 0.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, str)
            or not self.schema_version
            or self.schema_version != self.schema_version.strip()
        ):
            raise ValueError("diagnostic schema version must be nonblank and canonical")
        if (
            not isinstance(self.symbol, str)
            or not self.symbol
            or self.symbol != self.symbol.strip()
            or self.symbol != self.symbol.upper()
        ):
            raise ValueError("diagnostic symbol must be nonblank canonical uppercase")
        if not isinstance(self.config, RegimeModelConfig):
            raise ValueError("diagnostic config must be a canonical regime model config")
        if (
            not isinstance(self.feature_names, tuple)
            or not self.feature_names
            or any(not isinstance(name, str) or not name or name != name.strip() for name in self.feature_names)
            or len(set(self.feature_names)) != len(self.feature_names)
        ):
            raise ValueError("diagnostic feature names must be nonempty, unique, and canonical")

        feature_count = len(self.feature_names)
        cluster_count = self.config.cluster_count
        if any(
            not isinstance(values, tuple) or len(values) != feature_count
            for values in (self.lower_bounds, self.upper_bounds, self.medians, self.scales)
        ):
            raise ValueError("diagnostic preprocessing shape is inconsistent")
        if (
            not isinstance(self.means, tuple)
            or len(self.means) != cluster_count
            or any(not isinstance(row, tuple) or len(row) != feature_count for row in self.means)
            or not isinstance(self.weights, tuple)
            or len(self.weights) != cluster_count
        ):
            raise ValueError("diagnostic component shape is inconsistent")
        if (
            not isinstance(self.fingerprints, tuple)
            or len(self.fingerprints) != cluster_count
            or any(not isinstance(value, str) or not value for value in self.fingerprints)
            or len(set(self.fingerprints)) != cluster_count
            or self.fingerprints != tuple(sorted(self.fingerprints))
        ):
            raise ValueError("diagnostic fingerprints must be unique and deterministically ordered")
        if not isinstance(self.covariances, tuple) or not isinstance(self.distance_thresholds, tuple):
            raise ValueError("diagnostic covariance and distance parameters must use immutable tuples")
        if self.converged is not True:
            raise ValueError("diagnostic fit must have converged")
        if not isinstance(self.iterations, int) or isinstance(self.iterations, bool) or self.iterations <= 0:
            raise ValueError("diagnostic iterations must be a positive integer")
        if not isinstance(self.lower_bound, (int, float)) or isinstance(self.lower_bound, bool) or not math.isfinite(self.lower_bound):
            raise ValueError("diagnostic lower bound must be finite")

        numeric_groups = (
            self.lower_bounds,
            self.upper_bounds,
            self.medians,
            self.scales,
            self.weights,
            *self.means,
            *self.covariances,
            self.distance_thresholds,
        )
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for group in numeric_groups
            for value in group
        ):
            raise ValueError("diagnostic numeric parameters must be finite")
        if any(lower >= upper for lower, upper in zip(self.lower_bounds, self.upper_bounds)):
            raise ValueError("diagnostic clipping bounds must have positive width")
        if any(value <= 0 for value in self.scales):
            raise ValueError("diagnostic scales must be positive")
        if any(value <= 0 for value in self.weights) or not math.isclose(
            math.fsum(self.weights), 1.0, rel_tol=1e-8, abs_tol=1e-8
        ):
            raise ValueError("diagnostic weights must be positive and sum to one")

        if self.config.model_type == "kmeans":
            if self.covariances:
                raise ValueError("kmeans diagnostic cannot contain covariances")
            if (
                not isinstance(self.distance_thresholds, tuple)
                or len(self.distance_thresholds) != cluster_count
                or any(value < 0 for value in self.distance_thresholds)
            ):
                raise ValueError("kmeans diagnostic requires nonnegative distance thresholds")
        else:
            width = feature_count if self.config.covariance_type == "diag" else feature_count * feature_count
            if (
                not isinstance(self.covariances, tuple)
                or len(self.covariances) != cluster_count
                or any(not isinstance(row, tuple) or len(row) != width for row in self.covariances)
            ):
                raise ValueError("gmm diagnostic covariance shape is inconsistent")
            if self.distance_thresholds:
                raise ValueError("gmm diagnostic cannot contain distance thresholds")
            if self.config.covariance_type == "diag":
                if any(
                    _below_regularization_floor(value, self.config.regularization)
                    for row in self.covariances
                    for value in row
                ):
                    raise ValueError("gmm diagnostic covariance is below the configured regularization floor")
            else:
                shared = self.covariances[0]
                if any(
                    any(
                        not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-15)
                        for actual, expected in zip(row, shared)
                    )
                    for row in self.covariances[1:]
                ):
                    raise ValueError("tied gmm diagnostic must repeat one shared covariance")
                _validate_tied_covariance(shared, feature_count, self.config.regularization)

        expected_fingerprints = tuple(
            component_fingerprint(
                model_type=self.config.model_type,
                feature_schema_version=self.schema_version,
                feature_names=self.feature_names,
                mean=mean,
                covariance=() if self.config.model_type == "kmeans" else self.covariances[index],
                weight=None if self.config.model_type == "kmeans" else self.weights[index],
            )
            for index, mean in enumerate(self.means)
        )
        if self.fingerprints != expected_fingerprints:
            raise ValueError("diagnostic component fingerprint does not match fitted parameters")


__all__ = ["ClusterDiagnosticFit"]
