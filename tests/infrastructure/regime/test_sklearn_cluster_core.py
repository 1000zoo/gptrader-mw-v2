import numpy as np
import pytest

from src.domain.regime.model import RegimeModelConfig
from src.infrastructure.regime.sklearn_cluster_core import (
    _assign_probabilities,
    _fit_components,
    _validate_covariance,
)


FEATURE_NAMES = ("return_4h", "rv_1d", "atr_ratio_1d")


def _matrix() -> np.ndarray:
    rows = []
    for index in range(36):
        cluster = index % 3
        rows.append(
            [
                cluster * 8.0 + np.sin(index * 0.31),
                cluster * -5.0 + np.cos(index * 0.23),
                cluster * 3.0 + np.sin(index * 0.17 + 0.4),
            ]
        )
    return np.asarray(rows, dtype=float)


@pytest.mark.parametrize("seed", [20260714, 20260715, 20260716])
@pytest.mark.parametrize(
    "config_factory",
    [
        lambda seed: RegimeModelConfig("kmeans", 3, random_seed=seed),
        lambda seed: RegimeModelConfig("gmm", 3, random_seed=seed, covariance_type="diag"),
        lambda seed: RegimeModelConfig("gmm", 3, random_seed=seed, covariance_type="tied"),
    ],
)
def test_component_fit_is_deterministic_and_fingerprint_ordered(seed, config_factory):
    config = config_factory(seed)
    first = _fit_components(config, _matrix(), "schema-v1", FEATURE_NAMES)
    second = _fit_components(config, _matrix(), "schema-v1", FEATURE_NAMES)

    assert first == second
    assert first.fingerprints == tuple(sorted(first.fingerprints))
    assert len(set(first.fingerprints)) == config.cluster_count


@pytest.mark.parametrize(
    "config",
    [
        RegimeModelConfig("kmeans", 3),
        RegimeModelConfig("gmm", 3, covariance_type="diag"),
        RegimeModelConfig("gmm", 3, covariance_type="tied"),
    ],
)
def test_array_assignment_returns_probabilities_and_model_specific_distances(config):
    matrix = _matrix()
    fitted = _fit_components(config, matrix, "schema-v1", FEATURE_NAMES)
    probabilities, distances = _assign_probabilities(config, matrix, fitted)

    assert probabilities.shape == (len(matrix), config.cluster_count)
    np.testing.assert_allclose(probabilities.sum(axis=1), 1.0)
    assert np.isfinite(probabilities).all()
    if config.model_type == "kmeans":
        assert distances is not None
        assert distances.shape == probabilities.shape
        np.testing.assert_allclose(
            distances,
            np.linalg.norm(matrix[:, None, :] - np.asarray(fitted.means)[None, :, :], axis=2),
        )
    else:
        assert distances is None


@pytest.mark.parametrize(
    ("covariance", "covariance_type"),
    [
        (np.asarray([0.05, 0.2]), "diag"),
        (np.asarray([[0.05, 0.0], [0.0, 0.2]]), "tied"),
    ],
)
def test_covariance_floor_is_enforced(covariance, covariance_type):
    with pytest.raises(ValueError, match="covariance.*regularization floor"):
        _validate_covariance(covariance, covariance_type, regularization=0.1)


@pytest.mark.parametrize(
    "matrix",
    [
        np.ones(6),
        np.asarray([[0.0, 1.0], [np.nan, 2.0], [3.0, 4.0]]),
    ],
)
def test_component_fit_rejects_invalid_arrays(matrix):
    with pytest.raises(ValueError, match="matrix"):
        _fit_components(RegimeModelConfig("kmeans", 3), matrix, "schema-v1", ("a", "b"))
