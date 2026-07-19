from collections import Counter
from collections.abc import Sequence

import numpy as np
from sklearn.preprocessing import RobustScaler

from src.domain.regime.chart_features import ChartFeatureSpec
from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.model import ClusterAssignment, RegimeModelConfig
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
    ThreeDayChartFeatureVector,
)
from src.infrastructure.regime.sklearn_cluster_core import (
    _ClusterArrays,
    _assign_probabilities,
    _fit_components,
)
from src.infrastructure.regime.sklearn_regime_model import prune_correlated_features


class SklearnClusterDiagnostic:
    def fit(
        self,
        config: RegimeModelConfig,
        vectors: tuple[ThreeDayChartFeatureVector, ...],
        registry: Sequence[ChartFeatureSpec],
        *,
        retained_feature_names: tuple[str, ...] | None = None,
    ) -> ClusterDiagnosticFit:
        registry_names, families = _validate_registry(registry)
        _validate_vectors(vectors, registry_names, require_nonempty=True)
        if len(vectors) < config.cluster_count:
            raise ValueError("cluster-fit vectors must be at least the cluster count")

        all_values = np.asarray([tuple(vector.values.values()) for vector in vectors], dtype=float)
        if retained_feature_names is None:
            selected_names = prune_correlated_features(
                all_values,
                registry_names,
                registry_names=registry_names,
            )
        else:
            selected_names = _validate_retained_names(retained_feature_names, registry_names)
        _validate_family_cap(selected_names, families)

        indices = tuple(registry_names.index(name) for name in selected_names)
        matrix = all_values[:, indices]
        lower_bounds = np.quantile(matrix, 0.005, axis=0)
        upper_bounds = np.quantile(matrix, 0.995, axis=0)
        if (
            not np.isfinite(lower_bounds).all()
            or not np.isfinite(upper_bounds).all()
            or np.any(lower_bounds >= upper_bounds)
        ):
            raise ValueError("training clipping bounds must be finite with positive width")
        clipped = np.clip(matrix, lower_bounds, upper_bounds)
        scaler = RobustScaler().fit(clipped)
        medians = np.asarray(scaler.center_, dtype=float)
        scales = np.asarray(scaler.scale_, dtype=float)
        if not np.isfinite(medians).all() or not np.isfinite(scales).all() or np.any(scales <= 0):
            raise ValueError("fitted robust scaler has invalid parameters")
        scaled = (clipped - medians) / scales
        fitted = _fit_components(
            config,
            scaled,
            vectors[0].schema_version,
            selected_names,
        )

        return ClusterDiagnosticFit(
            schema_version=vectors[0].schema_version,
            symbol=vectors[0].symbol,
            config=config,
            feature_names=selected_names,
            lower_bounds=tuple(float(value) for value in lower_bounds),
            upper_bounds=tuple(float(value) for value in upper_bounds),
            medians=tuple(float(value) for value in medians),
            scales=tuple(float(value) for value in scales),
            fingerprints=fitted.fingerprints,
            means=fitted.means,
            weights=fitted.weights,
            covariances=fitted.covariances,
            distance_thresholds=fitted.distance_thresholds,
            converged=fitted.converged,
            iterations=fitted.iterations,
            lower_bound=fitted.lower_bound,
            precisions=fitted.precisions,
            precisions_cholesky=fitted.precisions_cholesky,
        )

    def assign(
        self,
        fit: ClusterDiagnosticFit,
        vectors: tuple[ThreeDayChartFeatureVector, ...],
        registry: Sequence[ChartFeatureSpec],
    ) -> tuple[ClusterAssignment, ...]:
        if not isinstance(fit, ClusterDiagnosticFit):
            raise ValueError("assignment fit must be a diagnostic cluster fit")
        registry_names, _ = _validate_registry(registry)
        if not vectors:
            return ()
        _validate_vectors(vectors, registry_names, require_nonempty=True)
        if any(vector.symbol != fit.symbol for vector in vectors):
            raise ValueError("assignment vector symbol does not match diagnostic fit")
        if any(vector.schema_version != fit.schema_version for vector in vectors):
            raise ValueError("assignment vector schema does not match diagnostic fit")
        selected_names = _validate_retained_names(fit.feature_names, registry_names)
        indices = tuple(registry_names.index(name) for name in selected_names)
        matrix = np.asarray([tuple(vector.values.values()) for vector in vectors], dtype=float)[:, indices]
        clipped = np.clip(matrix, fit.lower_bounds, fit.upper_bounds)
        scaled = (clipped - np.asarray(fit.medians)) / np.asarray(fit.scales)
        fitted = _ClusterArrays(
            fingerprints=fit.fingerprints,
            means=fit.means,
            weights=fit.weights,
            covariances=fit.covariances,
            distance_thresholds=fit.distance_thresholds,
        )
        probabilities, distances = _assign_probabilities(fit.config, scaled, fitted)
        if fit.config.model_type == "gmm" and fit.config.covariance_type == "diag":
            delta = scaled[:, None, :] - np.asarray(fit.means)[None, :, :]
            distances = np.sum(
                delta * delta / np.asarray(fit.covariances)[None, :, :], axis=2
            )

        assignments = []
        for row_index, row in enumerate(probabilities):
            order = np.argsort(-row, kind="stable")
            winner, runner_up = int(order[0]), int(order[1])
            assignments.append(
                ClusterAssignment(
                    fingerprint=fit.fingerprints[winner],
                    dominant_probability=float(row[winner]),
                    second_probability=float(row[runner_up]),
                    distance=None if distances is None else float(distances[row_index, winner]),
                )
            )
        return tuple(assignments)


def _validate_registry(
    registry: Sequence[ChartFeatureSpec],
) -> tuple[tuple[str, ...], dict[str, str]]:
    if (
        isinstance(registry, (str, bytes))
        or not isinstance(registry, Sequence)
        or not registry
    ):
        raise ValueError("diagnostic registry must be nonempty")
    specs = tuple(registry)
    if any(not isinstance(spec, ChartFeatureSpec) for spec in specs):
        raise ValueError("diagnostic registry entries must be chart feature specs")
    names = tuple(spec.name for spec in specs)
    families = tuple(spec.family for spec in specs)
    if len(set(names)) != len(names) or any(
        not _canonical_identifier(name) for name in names
    ):
        raise ValueError("diagnostic registry names must be canonical and unique")
    if any(not _canonical_identifier(family) for family in families):
        raise ValueError("diagnostic registry families must be canonical identifiers")
    for spec in specs:
        if (
            not isinstance(spec.aggregation_minutes, int)
            or isinstance(spec.aggregation_minutes, bool)
            or spec.aggregation_minutes <= 0
            or not isinstance(spec.lookback_minutes, int)
            or isinstance(spec.lookback_minutes, bool)
            or spec.lookback_minutes < spec.aggregation_minutes
            or spec.lookback_minutes % spec.aggregation_minutes != 0
        ):
            raise ValueError("diagnostic registry intervals must be positive aligned integers")
        if not _canonical_text(spec.formula):
            raise ValueError("diagnostic registry formulas must be nonblank and canonical")
        if not _canonical_text(spec.null_policy) or not _canonical_text(spec.clipping_policy):
            raise ValueError("diagnostic registry policies must be nonblank and canonical")
        if not isinstance(spec.scale_invariant, bool):
            raise ValueError("diagnostic registry scale-invariant flags must be boolean")
    if specs != THREE_DAY_CHART_FEATURE_REGISTRY_V1:
        raise ValueError("incompatible three-day registry")
    return names, dict(zip(names, families))


def _canonical_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and value == value.lower()
        and value.isidentifier()
    )


def _canonical_text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _validate_vectors(
    vectors: tuple[ThreeDayChartFeatureVector, ...],
    registry_names: tuple[str, ...],
    *,
    require_nonempty: bool,
) -> None:
    if require_nonempty and not vectors:
        raise ValueError("feature vectors cannot be empty")
    if not vectors:
        return
    if any(not isinstance(vector, ThreeDayChartFeatureVector) for vector in vectors):
        raise ValueError("diagnostic inputs must be actual three-day feature vectors")
    if any(
        vector.schema_version != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
        for vector in vectors
    ):
        raise ValueError("feature vectors must use the three-day feature schema")
    first = vectors[0]
    if any(tuple(vector.values) != registry_names for vector in vectors):
        raise ValueError("feature vectors must use ordered diagnostic registry features")
    if any(vector.symbol != first.symbol for vector in vectors):
        raise ValueError("feature vector symbols must be consistent")
    if any(vector.schema_version != first.schema_version for vector in vectors):
        raise ValueError("feature vector schemas must be consistent")
    anchors = tuple(vector.anchor_at for vector in vectors)
    if any(current <= previous for previous, current in zip(anchors, anchors[1:])):
        raise ValueError("feature vector anchors must be chronological and unique")


def _validate_retained_names(
    retained_feature_names: tuple[str, ...],
    registry_names: tuple[str, ...],
) -> tuple[str, ...]:
    selected = tuple(retained_feature_names)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("retained feature names must be nonempty and unique")
    if any(name not in registry_names for name in selected):
        raise ValueError("retained feature names contain unknown registry features")
    positions = tuple(registry_names.index(name) for name in selected)
    if positions != tuple(sorted(positions)):
        raise ValueError("retained feature names must follow registry priority order")
    return selected


def _validate_family_cap(feature_names: tuple[str, ...], families: dict[str, str]) -> None:
    counts = Counter(families[name] for name in feature_names)
    if any(count > 5 for count in counts.values()):
        raise ValueError("a feature family cannot exceed five retained inputs")
    if any(count > len(feature_names) / 2 for count in counts.values()):
        raise ValueError("a feature family cannot exceed half of retained inputs")


__all__ = ["SklearnClusterDiagnostic"]
