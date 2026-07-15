from collections import Counter

import numpy as np
from scipy.stats import rankdata
from sklearn.preprocessing import RobustScaler

from src.domain.regime.chart_features import (
    CHART_FEATURE_REGISTRY_V1,
    CHART_FEATURE_SCHEMA_VERSION,
    ChartFeatureVector,
)
from src.domain.regime.model import (
    REGIME_MODEL_ARTIFACT_VERSION,
    ClusterAssignment,
    RegimeModelArtifact,
    RegimeModelConfig,
)
from src.infrastructure.regime.sklearn_cluster_core import (
    _ClusterArrays,
    _assign_probabilities,
    _fit_components,
    _validate_covariance,
)


_REGISTRY_NAMES = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)
_FAMILIES = {spec.name: spec.family for spec in CHART_FEATURE_REGISTRY_V1}


def prune_correlated_features(
    matrix: np.ndarray,
    feature_names: tuple[str, ...],
    registry_names: tuple[str, ...] = _REGISTRY_NAMES,
    threshold: float = 0.95,
) -> tuple[str, ...]:
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(feature_names) or values.shape[0] < 2:
        raise ValueError("feature matrix shape is inconsistent")
    if not 0 < threshold <= 1:
        raise ValueError("correlation threshold must be between zero and one")
    if (
        not registry_names
        or len(set(registry_names)) != len(registry_names)
        or any(not name for name in registry_names)
    ):
        raise ValueError("registry names must be nonempty and unique")
    if len(set(feature_names)) != len(feature_names) or any(name not in registry_names for name in feature_names):
        raise ValueError("feature names contain duplicates or unknown registry features")
    positions = tuple(registry_names.index(name) for name in feature_names)
    if positions != tuple(sorted(positions)):
        raise ValueError("feature names must follow registry priority order")
    if not np.isfinite(values).all():
        raise ValueError("feature matrix values must be finite")
    if np.any(np.ptp(values, axis=0) == 0):
        raise ValueError("feature matrix contains a constant column")

    ranks = np.column_stack(tuple(rankdata(values[:, column]) for column in range(values.shape[1])))
    correlations = np.corrcoef(ranks, rowvar=False)
    retained_indices: list[int] = []
    for candidate in range(values.shape[1]):
        if all(abs(float(correlations[candidate, retained])) < threshold for retained in retained_indices):
            retained_indices.append(candidate)
    return tuple(feature_names[index] for index in retained_indices)


class SklearnRegimeModel:
    def fit(
        self,
        config: RegimeModelConfig,
        vectors: tuple[ChartFeatureVector, ...],
        *,
        retained_feature_names: tuple[str, ...] | None = None,
    ) -> RegimeModelArtifact:
        _validate_vector_sequence(vectors, require_nonempty=True)
        if len(vectors) < config.cluster_count:
            raise ValueError("cluster-fit vectors must be at least the cluster count")

        all_values = np.asarray([tuple(vector.values.values()) for vector in vectors], dtype=float)
        if retained_feature_names is None:
            selected_names = prune_correlated_features(all_values, _REGISTRY_NAMES)
        else:
            selected_names = tuple(retained_feature_names)
            if not selected_names or len(set(selected_names)) != len(selected_names):
                raise ValueError("retained feature names must be nonempty and unique")
            if any(name not in _REGISTRY_NAMES for name in selected_names):
                raise ValueError("retained feature names contain unknown registry features")
            positions = tuple(_REGISTRY_NAMES.index(name) for name in selected_names)
            if positions != tuple(sorted(positions)):
                raise ValueError("retained feature names must follow registry priority order")
        _validate_family_cap(selected_names)
        selected_indices = tuple(_REGISTRY_NAMES.index(name) for name in selected_names)
        matrix = all_values[:, selected_indices]
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

        return RegimeModelArtifact(
            artifact_version=REGIME_MODEL_ARTIFACT_VERSION,
            symbol=vectors[0].symbol,
            feature_schema_version=vectors[0].schema_version,
            config=config,
            feature_names=selected_names,
            lower_bounds=tuple(float(value) for value in lower_bounds),
            upper_bounds=tuple(float(value) for value in upper_bounds),
            medians=tuple(float(value) for value in medians),
            scales=tuple(float(value) for value in scales),
            weights=fitted.weights,
            means=fitted.means,
            covariances=fitted.covariances,
            fingerprints=fitted.fingerprints,
            training_start_at=vectors[0].anchor_at,
            training_end_at=vectors[-1].anchor_at,
            distance_thresholds=fitted.distance_thresholds,
        )

    def assign(
        self,
        artifact: RegimeModelArtifact,
        vectors: tuple[ChartFeatureVector, ...],
    ) -> tuple[ClusterAssignment, ...]:
        if not vectors:
            return ()
        _validate_vector_sequence(vectors, require_nonempty=True)
        if any(vector.symbol != artifact.symbol for vector in vectors):
            raise ValueError("assignment vector symbol does not match artifact")
        if any(vector.schema_version != artifact.feature_schema_version for vector in vectors):
            raise ValueError("assignment vector schema does not match artifact")
        indices = tuple(_REGISTRY_NAMES.index(name) for name in artifact.feature_names)
        matrix = np.asarray([tuple(vector.values.values()) for vector in vectors], dtype=float)[:, indices]
        clipped = np.clip(matrix, artifact.lower_bounds, artifact.upper_bounds)
        scaled = (clipped - np.asarray(artifact.medians)) / np.asarray(artifact.scales)
        fitted = _ClusterArrays(
            fingerprints=artifact.fingerprints,
            means=artifact.means,
            weights=artifact.weights,
            covariances=artifact.covariances,
            distance_thresholds=artifact.distance_thresholds,
        )
        probabilities, distances = _assign_probabilities(artifact.config, scaled, fitted)

        assignments = []
        for row_index, row in enumerate(probabilities):
            order = np.argsort(-row, kind="stable")
            winner, runner_up = int(order[0]), int(order[1])
            assignments.append(
                ClusterAssignment(
                    fingerprint=artifact.fingerprints[winner],
                    dominant_probability=float(row[winner]),
                    second_probability=float(row[runner_up]),
                    distance=None if distances is None else float(distances[row_index, winner]),
                )
            )
        return tuple(assignments)

def _validate_vector_sequence(vectors: tuple[ChartFeatureVector, ...], *, require_nonempty: bool) -> None:
    if require_nonempty and not vectors:
        raise ValueError("feature vectors cannot be empty")
    if not vectors:
        return
    first = vectors[0]
    if any(vector.schema_version != CHART_FEATURE_SCHEMA_VERSION for vector in vectors):
        raise ValueError("feature vectors must use the V1 feature schema")
    if any(tuple(vector.values) != _REGISTRY_NAMES for vector in vectors):
        raise ValueError("feature vectors must use ordered V1 features")
    if any(vector.symbol != first.symbol for vector in vectors):
        raise ValueError("feature vector symbols must be consistent")
    if any(vector.schema_version != first.schema_version for vector in vectors):
        raise ValueError("feature vector schemas must be consistent")
    anchors = tuple(vector.anchor_at for vector in vectors)
    if any(current <= previous for previous, current in zip(anchors, anchors[1:])):
        raise ValueError("feature vector anchors must be chronological and unique")


def _validate_family_cap(feature_names: tuple[str, ...]) -> None:
    counts = Counter(_FAMILIES[name] for name in feature_names)
    if any(count > len(feature_names) / 2 for count in counts.values()):
        raise ValueError("a feature family cannot exceed half of retained inputs")


__all__ = ["SklearnRegimeModel", "prune_correlated_features"]
