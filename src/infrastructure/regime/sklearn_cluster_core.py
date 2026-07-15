from dataclasses import dataclass
import math
import warnings

import numpy as np
from sklearn.cluster import KMeans
from sklearn.exceptions import ConvergenceWarning
from sklearn.mixture import GaussianMixture

from src.domain.regime.model import RegimeModelConfig, component_fingerprint


@dataclass(frozen=True)
class _ClusterArrays:
    fingerprints: tuple[str, ...]
    means: tuple[tuple[float, ...], ...]
    weights: tuple[float, ...]
    covariances: tuple[tuple[float, ...], ...]
    distance_thresholds: tuple[float, ...]


def _fit_components(
    config: RegimeModelConfig,
    scaled: np.ndarray,
    schema_version: str,
    feature_names: tuple[str, ...],
) -> _ClusterArrays:
    values = np.asarray(scaled, dtype=float)
    if (
        values.ndim != 2
        or values.shape[0] < config.cluster_count
        or values.shape[1] != len(feature_names)
        or values.shape[1] == 0
        or not np.isfinite(values).all()
    ):
        raise ValueError("cluster-fit matrix shape and values must be valid")

    if config.model_type == "kmeans":
        fitted_parameters = _fit_kmeans(config, values)
    else:
        fitted_parameters = _fit_gmm(config, values)

    parameters = []
    for mean, weight, covariance, threshold in fitted_parameters:
        mean_tuple = tuple(float(value) for value in mean)
        covariance_tuple = tuple(float(value) for value in covariance)
        fingerprint = component_fingerprint(
            model_type=config.model_type,
            feature_schema_version=schema_version,
            feature_names=feature_names,
            mean=mean_tuple,
            covariance=() if config.model_type == "kmeans" else covariance_tuple,
            weight=None if config.model_type == "kmeans" else float(weight),
        )
        parameters.append((fingerprint, mean_tuple, float(weight), covariance_tuple, float(threshold)))

    records = sorted(parameters, key=lambda item: item[0])
    fingerprints = tuple(item[0] for item in records)
    if len(set(fingerprints)) != config.cluster_count:
        raise ValueError("fitted model produced duplicate component fingerprints")
    return _ClusterArrays(
        fingerprints=fingerprints,
        means=tuple(item[1] for item in records),
        weights=tuple(item[2] for item in records),
        covariances=tuple(item[3] for item in records) if config.model_type == "gmm" else (),
        distance_thresholds=tuple(item[4] for item in records) if config.model_type == "kmeans" else (),
    )


def _fit_kmeans(
    config: RegimeModelConfig,
    scaled: np.ndarray,
) -> list[tuple[np.ndarray, float, tuple[()], float]]:
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
        records.append((centers[component], weight, (), threshold))
    return records


def _fit_gmm(
    config: RegimeModelConfig,
    scaled: np.ndarray,
) -> list[tuple[np.ndarray, float, tuple[float, ...], float]]:
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
        _validate_covariance(covariance, config.covariance_type, regularization=config.regularization)
        flattened = tuple(float(value) for value in covariance.reshape(-1))
        records.append((means[component], float(weights[component]), flattened, 0.0))
    return records


def _validate_covariance(
    covariance: np.ndarray,
    covariance_type: str | None,
    *,
    regularization: float,
) -> None:
    if not np.isfinite(covariance).all():
        raise ValueError("gmm covariance must be finite and positive")
    tolerance = max(regularization * 1e-12, np.finfo(float).eps * max(1.0, regularization))
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


def _assign_probabilities(
    config: RegimeModelConfig,
    scaled: np.ndarray,
    fitted: _ClusterArrays,
) -> tuple[np.ndarray, np.ndarray | None]:
    values = np.asarray(scaled, dtype=float)
    means = np.asarray(fitted.means, dtype=float)
    if (
        values.ndim != 2
        or means.shape != (config.cluster_count, values.shape[1])
        or not np.isfinite(values).all()
    ):
        raise ValueError("cluster-assignment matrix shape and values must be valid")
    if config.model_type == "kmeans":
        return _kmeans_probabilities(values, means)
    return _gmm_probabilities(config, values, fitted), None


def _kmeans_probabilities(scaled: np.ndarray, means: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    distances = np.linalg.norm(scaled[:, None, :] - means[None, :, :], axis=2)
    logits = -distances
    logits -= np.max(logits, axis=1, keepdims=True)
    exponentials = np.exp(logits)
    return exponentials / exponentials.sum(axis=1, keepdims=True), distances


def _gmm_probabilities(
    config: RegimeModelConfig,
    scaled: np.ndarray,
    fitted: _ClusterArrays,
) -> np.ndarray:
    means = np.asarray(fitted.means)
    dimensions = means.shape[1]
    log_probabilities = np.empty((len(scaled), config.cluster_count), dtype=float)
    shared_inverse = shared_log_determinant = None
    if config.covariance_type == "tied":
        shared = np.asarray(fitted.covariances[0]).reshape(dimensions, dimensions)
        shared_inverse = np.linalg.inv(shared)
        sign, shared_log_determinant = np.linalg.slogdet(shared)
        if sign <= 0:
            raise ValueError("fitted tied covariance must be positive definite")
    for component in range(config.cluster_count):
        delta = scaled - means[component]
        if config.covariance_type == "diag":
            covariance = np.asarray(fitted.covariances[component])
            quadratic = np.sum(delta * delta / covariance, axis=1)
            log_determinant = float(np.log(covariance).sum())
        else:
            quadratic = np.einsum("ij,jk,ik->i", delta, shared_inverse, delta)
            log_determinant = float(shared_log_determinant)
        log_probabilities[:, component] = (
            math.log(fitted.weights[component])
            - 0.5 * (dimensions * math.log(2 * math.pi) + log_determinant + quadratic)
        )
    maxima = np.max(log_probabilities, axis=1, keepdims=True)
    exponentials = np.exp(log_probabilities - maxima)
    return exponentials / exponentials.sum(axis=1, keepdims=True)
