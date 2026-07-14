from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler

from src.domain.regime.chart_features import (
    CHART_FEATURE_REGISTRY_V1,
    CHART_FEATURE_SCHEMA_VERSION,
    ChartFeatureVector,
)
from src.domain.regime.model import RegimeModelConfig
from src.infrastructure.regime.sklearn_regime_model import (
    SklearnRegimeModel,
    _validate_covariance,
    prune_correlated_features,
)


FEATURE_NAMES = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)


def _vectors(count: int = 36, *, start_offset: int = 0) -> tuple[ChartFeatureVector, ...]:
    vectors = []
    origin = datetime(2026, 1, 5, tzinfo=timezone.utc)
    for index in range(start_offset, start_offset + count):
        cluster = index % 3
        values = {
            name: float(cluster * 25 + np.sin((index + 1) * (column + 1) * 0.37) + column * 0.071)
            for column, name in enumerate(FEATURE_NAMES)
        }
        anchor = origin + timedelta(hours=4 * index)
        vectors.append(
            ChartFeatureVector(
                symbol="BTCUSDT",
                anchor_at=anchor,
                window_start_at=anchor - timedelta(days=7),
                schema_version=CHART_FEATURE_SCHEMA_VERSION,
                values=values,
            )
        )
    return tuple(vectors)


def test_gmm_supports_only_diag_and_tied():
    with pytest.raises(ValueError, match="diag or tied"):
        RegimeModelConfig(model_type="gmm", cluster_count=3, covariance_type="full")


def test_correlation_pruning_keeps_registry_priority():
    matrix = np.asarray(
        [
            [1.0, 2.0, 10.0, 20.0],
            [2.0, 4.0, 40.0, 80.0],
            [3.0, 6.0, 20.0, 40.0],
            [4.0, 8.0, 30.0, 60.0],
        ]
    )
    names = ("return_4h", "return_12h", "rv_1d", "rv_7d")

    assert prune_correlated_features(matrix, names, threshold=0.95) == (
        "return_4h",
        "rv_1d",
    )


@pytest.mark.parametrize(
    "config",
    [
        RegimeModelConfig(model_type="kmeans", cluster_count=3),
        RegimeModelConfig(model_type="gmm", cluster_count=3, covariance_type="diag"),
        RegimeModelConfig(model_type="gmm", cluster_count=3, covariance_type="tied"),
    ],
)
def test_fit_and_array_only_assignment_are_deterministic_and_json_auditable(config):
    vectors = _vectors()
    first_engine = SklearnRegimeModel()
    second_engine = SklearnRegimeModel()

    first = first_engine.fit(config, vectors)
    second = second_engine.fit(config, vectors)

    assert first == second
    assert first.feature_names
    assert set(first.feature_names).issubset(FEATURE_NAMES)
    assert len(first.fingerprints) == config.cluster_count
    assert len(set(first.fingerprints)) == config.cluster_count
    assignments = first_engine.assign(first, vectors)
    reconstructed = replace(first)
    array_only_assignments = SklearnRegimeModel().assign(reconstructed, vectors)
    assert assignments == array_only_assignments
    assert len({item.fingerprint for item in assignments}) == 3
    assert all(0.0 <= item.second_probability <= item.dominant_probability <= 1.0 for item in assignments)
    if config.model_type == "kmeans":
        assert all(item.distance is not None for item in assignments)
        assert len(first.distance_thresholds) == 3
    else:
        assert all(item.distance is None for item in assignments)


@pytest.mark.parametrize(
    "config",
    [
        RegimeModelConfig(model_type="kmeans", cluster_count=3),
        RegimeModelConfig(model_type="gmm", cluster_count=3, covariance_type="diag"),
        RegimeModelConfig(model_type="gmm", cluster_count=3, covariance_type="tied"),
    ],
)
def test_array_only_inference_matches_fitted_sklearn_winners(config):
    vectors = _vectors()
    engine = SklearnRegimeModel()
    artifact = engine.fit(config, vectors)
    assignments = engine.assign(artifact, vectors)
    indices = tuple(FEATURE_NAMES.index(name) for name in artifact.feature_names)
    raw = np.asarray([tuple(vector.values.values()) for vector in vectors])[:, indices]
    scaled = RobustScaler().fit_transform(raw)

    if config.model_type == "kmeans":
        estimator = KMeans(n_clusters=3, random_state=config.random_seed, n_init=20).fit(scaled)
        estimator_means = estimator.cluster_centers_
        distances = np.linalg.norm(scaled[:, None, :] - estimator_means[None, :, :], axis=2)
        expected_probabilities = np.exp(-distances - np.max(-distances, axis=1, keepdims=True))
        expected_probabilities /= expected_probabilities.sum(axis=1, keepdims=True)
    else:
        estimator = GaussianMixture(
            n_components=3,
            random_state=config.random_seed,
            n_init=20,
            covariance_type=config.covariance_type,
            reg_covar=config.regularization,
        ).fit(scaled)
        estimator_means = estimator.means_
        expected_probabilities = estimator.predict_proba(scaled)

    estimator_component_by_fingerprint = {}
    for fingerprint, mean in zip(artifact.fingerprints, artifact.means):
        matches = np.flatnonzero(np.all(np.isclose(estimator_means, mean, rtol=1e-9, atol=1e-9), axis=1))
        assert len(matches) == 1
        estimator_component_by_fingerprint[fingerprint] = int(matches[0])
    for row, assignment in zip(expected_probabilities, assignments):
        component = estimator_component_by_fingerprint[assignment.fingerprint]
        sorted_probabilities = np.sort(row)[::-1]
        assert component == int(np.argmax(row))
        assert assignment.dominant_probability == pytest.approx(sorted_probabilities[0], rel=1e-9)
        assert assignment.second_probability == pytest.approx(sorted_probabilities[1], rel=1e-9)


def test_fit_rejects_constant_and_unknown_inputs_and_assign_rejects_schema_mismatch():
    engine = SklearnRegimeModel()
    matrix = np.ones((4, 2))
    with pytest.raises(ValueError, match="constant"):
        prune_correlated_features(matrix, ("return_4h", "rv_1d"))
    with pytest.raises(ValueError, match="unknown"):
        prune_correlated_features(np.arange(8.0).reshape(4, 2), ("return_4h", "made_up"))

    artifact = engine.fit(RegimeModelConfig("kmeans", 3), _vectors())
    wrong_symbol = replace(_vectors(1)[0], symbol="ETHUSDT")
    with pytest.raises(ValueError, match="symbol"):
        engine.assign(artifact, (wrong_symbol,))

    with pytest.raises(ValueError, match="shape"):
        replace(artifact, scales=(1.0,))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"model_type": "other", "cluster_count": 3}, "model type"),
        ({"model_type": "kmeans", "cluster_count": 2}, "between 3 and 8"),
        ({"model_type": "kmeans", "cluster_count": 3, "covariance_type": "diag"}, "None"),
        ({"model_type": "gmm", "cluster_count": 3}, "diag or tied"),
        ({"model_type": "gmm", "cluster_count": 3, "covariance_type": "diag", "regularization": 0.0}, "positive"),
    ],
)
def test_model_config_validation(kwargs, message):
    with pytest.raises(ValueError, match=message):
        RegimeModelConfig(**kwargs)


@pytest.mark.parametrize(
    ("covariance", "covariance_type"),
    [
        (np.asarray([0.05, 0.2]), "diag"),
        (np.asarray([[0.05, 0.0], [0.0, 0.2]]), "tied"),
    ],
)
def test_gmm_covariance_rejects_values_below_regularization_floor(
    covariance,
    covariance_type,
):
    with pytest.raises(ValueError, match="covariance.*regularization floor"):
        _validate_covariance(covariance, covariance_type, regularization=0.1)


def test_tied_gmm_artifact_rejects_contradictory_shared_covariances():
    artifact = SklearnRegimeModel().fit(
        RegimeModelConfig("gmm", 3, covariance_type="tied"),
        _vectors(),
    )
    contradictory = list(artifact.covariances)
    changed = list(contradictory[1])
    changed[0] += 0.1
    contradictory[1] = tuple(changed)

    with pytest.raises(ValueError, match="shared covariance"):
        replace(artifact, covariances=tuple(contradictory))
