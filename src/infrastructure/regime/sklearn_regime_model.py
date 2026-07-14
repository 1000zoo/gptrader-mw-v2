from collections import Counter
import hashlib
import json
import math
import warnings

import numpy as np
from scipy.stats import rankdata
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler
from sklearn.exceptions import ConvergenceWarning

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


_REGISTRY_NAMES = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)
_FAMILIES = {spec.name: spec.family for spec in CHART_FEATURE_REGISTRY_V1}


def prune_correlated_features(
    matrix: np.ndarray,
    feature_names: tuple[str, ...],
    threshold: float = 0.95,
) -> tuple[str, ...]:
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(feature_names) or values.shape[0] < 2:
        raise ValueError("feature matrix shape is inconsistent")
    if not 0 < threshold <= 1:
        raise ValueError("correlation threshold must be between zero and one")
    if len(set(feature_names)) != len(feature_names) or any(name not in _REGISTRY_NAMES for name in feature_names):
        raise ValueError("feature names contain duplicates or unknown registry features")
    positions = tuple(_REGISTRY_NAMES.index(name) for name in feature_names)
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
    ) -> RegimeModelArtifact:
        _validate_vector_sequence(vectors, require_nonempty=True)
        if len(vectors) < config.cluster_count:
            raise ValueError("cluster-fit vectors must be at least the cluster count")

        all_values = np.asarray([tuple(vector.values.values()) for vector in vectors], dtype=float)
        selected_names = prune_correlated_features(all_values, _REGISTRY_NAMES)
        _validate_family_cap(selected_names)
        selected_indices = tuple(_REGISTRY_NAMES.index(name) for name in selected_names)
        matrix = all_values[:, selected_indices]
        scaler = RobustScaler().fit(matrix)
        medians = np.asarray(scaler.center_, dtype=float)
        scales = np.asarray(scaler.scale_, dtype=float)
        if not np.isfinite(medians).all() or not np.isfinite(scales).all() or np.any(scales <= 0):
            raise ValueError("fitted robust scaler has invalid parameters")
        scaled = (matrix - medians) / scales

        if config.model_type == "kmeans":
            parameters = self._fit_kmeans(config, scaled)
        else:
            parameters = self._fit_gmm(config, scaled)

        records = sorted(parameters, key=lambda item: item[0])
        fingerprints = tuple(item[0] for item in records)
        if len(set(fingerprints)) != config.cluster_count:
            raise ValueError("fitted model produced duplicate component fingerprints")
        means = tuple(tuple(float(value) for value in item[1]) for item in records)
        weights = tuple(float(item[2]) for item in records)
        covariances = tuple(tuple(float(value) for value in item[3]) for item in records) if config.model_type == "gmm" else ()
        thresholds = tuple(float(item[4]) for item in records) if config.model_type == "kmeans" else ()

        return RegimeModelArtifact(
            artifact_version=REGIME_MODEL_ARTIFACT_VERSION,
            symbol=vectors[0].symbol,
            feature_schema_version=vectors[0].schema_version,
            config=config,
            feature_names=selected_names,
            medians=tuple(float(value) for value in medians),
            scales=tuple(float(value) for value in scales),
            weights=weights,
            means=means,
            covariances=covariances,
            fingerprints=fingerprints,
            training_start_at=vectors[0].anchor_at,
            training_end_at=vectors[-1].anchor_at,
            distance_thresholds=thresholds,
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
        scaled = (matrix - np.asarray(artifact.medians)) / np.asarray(artifact.scales)
        if artifact.config.model_type == "kmeans":
            probabilities, distances = _kmeans_probabilities(scaled, np.asarray(artifact.means))
        else:
            probabilities = _gmm_probabilities(artifact, scaled)
            distances = None

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

    @staticmethod
    def _fit_kmeans(config: RegimeModelConfig, scaled: np.ndarray) -> list[tuple[str, np.ndarray, float, tuple[()], float]]:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            try:
                estimator = KMeans(
                    n_clusters=config.cluster_count,
                    random_state=config.random_seed,
                    n_init=20,
                ).fit(scaled)
            except ConvergenceWarning as exc:
                raise ValueError("kmeans did not converge to nondegenerate clusters") from exc
        centers = np.asarray(estimator.cluster_centers_, dtype=float)
        labels = np.asarray(estimator.labels_, dtype=int)
        if not np.isfinite(centers).all() or len(set(labels.tolist())) != config.cluster_count:
            raise ValueError("kmeans did not produce the requested nondegenerate clusters")
        distances = np.linalg.norm(scaled[:, None, :] - centers[None, :, :], axis=2)
        counts = np.bincount(labels, minlength=config.cluster_count)
        records = []
        for component in range(config.cluster_count):
            threshold = float(np.quantile(distances[labels == component, component], 0.99))
            weight = float(counts[component] / len(labels))
            fingerprint = _fingerprint("kmeans", centers[component], (), weight)
            records.append((fingerprint, centers[component], weight, (), threshold))
        return records

    @staticmethod
    def _fit_gmm(config: RegimeModelConfig, scaled: np.ndarray) -> list[tuple[str, np.ndarray, float, tuple[float, ...], float]]:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            try:
                estimator = GaussianMixture(
                    n_components=config.cluster_count,
                    random_state=config.random_seed,
                    n_init=20,
                    covariance_type=config.covariance_type,
                    reg_covar=config.regularization,
                ).fit(scaled)
            except ConvergenceWarning as exc:
                raise ValueError("gmm did not converge") from exc
        if not estimator.converged_:
            raise ValueError("gmm did not converge")
        means = np.asarray(estimator.means_, dtype=float)
        weights = np.asarray(estimator.weights_, dtype=float)
        raw_covariances = np.asarray(estimator.covariances_, dtype=float)
        if not np.isfinite(means).all() or not np.isfinite(weights).all() or np.any(weights <= 0):
            raise ValueError("gmm produced invalid or zero-weight components")
        records = []
        for component in range(config.cluster_count):
            covariance = raw_covariances[component] if config.covariance_type == "diag" else raw_covariances
            _validate_covariance(
                covariance,
                config.covariance_type,
                regularization=config.regularization,
            )
            flattened = tuple(float(value) for value in covariance.reshape(-1))
            fingerprint = _fingerprint("gmm", means[component], flattened, float(weights[component]))
            records.append((fingerprint, means[component], float(weights[component]), flattened, 0.0))
        return records


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


def _validate_covariance(
    covariance: np.ndarray,
    covariance_type: str | None,
    *,
    regularization: float,
) -> None:
    if not np.isfinite(covariance).all():
        raise ValueError("gmm covariance must be finite and positive")
    tolerance = max(
        regularization * 1e-12,
        np.finfo(float).eps * max(1.0, regularization),
    )
    if covariance_type == "diag" and float(np.min(covariance)) + tolerance < regularization:
        raise ValueError("gmm covariance is below the configured regularization floor")
    if covariance_type == "tied":
        if covariance.ndim != 2 or not np.allclose(covariance, covariance.T):
            raise ValueError("gmm tied covariance must be symmetric")
        eigenvalues = np.linalg.eigvalsh(covariance)
        if not np.isfinite(eigenvalues).all():
            raise ValueError("gmm tied covariance must have finite eigenvalues")
        if float(np.min(eigenvalues)) + tolerance < regularization:
            raise ValueError("gmm covariance is below the configured regularization floor")


def _fingerprint(model_type: str, mean: np.ndarray, covariance: tuple[float, ...], weight: float) -> str:
    payload = {
        "model_type": model_type,
        "mean": [_quantized(value) for value in mean],
        "covariance": [_quantized(value) for value in covariance],
        "weight": _quantized(weight),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]


def _quantized(value: float) -> str:
    return format(float(value), ".12g")


def _kmeans_probabilities(scaled: np.ndarray, means: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    distances = np.linalg.norm(scaled[:, None, :] - means[None, :, :], axis=2)
    logits = -distances
    logits -= np.max(logits, axis=1, keepdims=True)
    exponentials = np.exp(logits)
    return exponentials / exponentials.sum(axis=1, keepdims=True), distances


def _gmm_probabilities(artifact: RegimeModelArtifact, scaled: np.ndarray) -> np.ndarray:
    means = np.asarray(artifact.means)
    dimensions = means.shape[1]
    log_probabilities = np.empty((len(scaled), artifact.config.cluster_count), dtype=float)
    shared_inverse = shared_log_determinant = None
    if artifact.config.covariance_type == "tied":
        # The artifact contract requires every component row to repeat this
        # shared matrix, so inference has one unambiguous covariance source.
        shared = np.asarray(artifact.covariances[0]).reshape(dimensions, dimensions)
        shared_inverse = np.linalg.inv(shared)
        sign, shared_log_determinant = np.linalg.slogdet(shared)
        if sign <= 0:
            raise ValueError("artifact tied covariance must be positive definite")
    for component in range(artifact.config.cluster_count):
        delta = scaled - means[component]
        if artifact.config.covariance_type == "diag":
            covariance = np.asarray(artifact.covariances[component])
            quadratic = np.sum(delta * delta / covariance, axis=1)
            log_determinant = float(np.log(covariance).sum())
        else:
            quadratic = np.einsum("ij,jk,ik->i", delta, shared_inverse, delta)
            log_determinant = float(shared_log_determinant)
        log_probabilities[:, component] = (
            math.log(artifact.weights[component])
            - 0.5 * (dimensions * math.log(2 * math.pi) + log_determinant + quadratic)
        )
    maxima = np.max(log_probabilities, axis=1, keepdims=True)
    exponentials = np.exp(log_probabilities - maxima)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


__all__ = ["SklearnRegimeModel", "prune_correlated_features"]
