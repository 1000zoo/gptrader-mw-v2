from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler

from src.application.usecases.regime.fit_regime_model_usecase import (
    FitRegimeModelCommand,
    FitRegimeModelUseCase,
)

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
from src.infrastructure.regime.json_regime_artifact_repository import model_artifact_hash


FEATURE_NAMES = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)


@pytest.mark.parametrize(
    ("config", "expected_hash"),
    [
        (RegimeModelConfig("kmeans", 3), "39318ca6c32e2db67a5019e8b114d2f725d4d5731428f2239f046bcff66363a9"),
        (
            RegimeModelConfig("gmm", 3, covariance_type="diag"),
            "543c933069e97db124a5d9d0a4153da32fb2b0840f272ce272b6830ff0bd0e56",
        ),
        (
            RegimeModelConfig("gmm", 3, covariance_type="tied"),
            "d5dfda332fb3723afb9fa34965fb1440624e20ef53dcd45e1f17af30baf31e29",
        ),
    ],
)
def test_seven_day_fit_bytes_remain_frozen(config, expected_hash):
    assert model_artifact_hash(SklearnRegimeModel().fit(config, _vectors())) == expected_hash


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (
            RegimeModelConfig("kmeans", 3),
            (
                ("16250fdd086799bf7fea0c7a", 0.8787796089627629, 0.10821701730901495, 0.01557455266489679),
                ("f5fa608d6e9b3420d5d07d8b", 0.7977904847505851, 0.10113640494281649, 0.054126467498397376),
                ("daefcd478dbcc8e6d951e7bf", 0.8750541560708589, 0.11153793687480866, 0.06037618901274106),
            ),
        ),
        (
            RegimeModelConfig("gmm", 3, covariance_type="diag"),
            (
                ("c36916cea88476fd6b61f382", 1.0, 0.0, None),
                ("4ff659f678bedac2bc816210", 1.0, 0.0, None),
                ("c13ed8afec0513bbb9fa75d9", 1.0, 0.0, None),
            ),
        ),
        (
            RegimeModelConfig("gmm", 3, covariance_type="tied"),
            (
                ("0bc95608dc9d7a060bda60f6", 1.0, 0.0, None),
                ("6e084c699c6eda67c4a91cf6", 1.0, 0.0, None),
                ("9b0e2d8ee784ef5c6ef564a6", 1.0, 0.0, None),
            ),
        ),
    ],
)
def test_seven_day_assignment_values_remain_frozen(config, expected):
    engine = SklearnRegimeModel()
    vectors = _vectors()
    artifact = engine.fit(config, vectors)
    actual = tuple(
        (item.fingerprint, item.dominant_probability, item.second_probability, item.distance)
        for item in engine.assign(artifact, vectors[-3:])
    )

    assert actual == expected


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


def test_fit_can_freeze_primary_retained_features_without_reselection(monkeypatch):
    import src.infrastructure.regime.sklearn_regime_model as module

    vectors = _vectors()
    primary = SklearnRegimeModel().fit(RegimeModelConfig("kmeans", 3), vectors)
    monkeypatch.setattr(
        module, "prune_correlated_features",
        lambda *_args, **_kwargs: pytest.fail("fixed-feature refit must not re-prune"),
    )
    refit = SklearnRegimeModel().fit(
        RegimeModelConfig("kmeans", 3),
        vectors[: len(vectors) // 2],
        retained_feature_names=primary.feature_names,
    )
    assert refit.feature_names == primary.feature_names


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
    clipped = np.clip(raw, artifact.lower_bounds, artifact.upper_bounds)
    scaled = RobustScaler().fit_transform(clipped)

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
        ({"model_type": "kmeans", "cluster_count": True}, "cluster count.*integer"),
        ({"model_type": "kmeans", "cluster_count": 3, "random_seed": True}, "random seed.*integer"),
        ({"model_type": "kmeans", "cluster_count": 3, "random_seed": -1}, "random seed.*between"),
        ({"model_type": "kmeans", "cluster_count": 3, "random_seed": 2**32}, "random seed.*between"),
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


def test_fit_persists_train_quantile_clipping_before_robust_scaling():
    vectors = _vectors()
    artifact = SklearnRegimeModel().fit(RegimeModelConfig("kmeans", 3), vectors)
    indices = tuple(FEATURE_NAMES.index(name) for name in artifact.feature_names)
    raw = np.asarray([tuple(vector.values.values()) for vector in vectors])[:, indices]
    expected_lower = np.quantile(raw, 0.005, axis=0)
    expected_upper = np.quantile(raw, 0.995, axis=0)
    clipped = np.clip(raw, expected_lower, expected_upper)
    scaler = RobustScaler().fit(clipped)

    np.testing.assert_allclose(artifact.lower_bounds, expected_lower)
    np.testing.assert_allclose(artifact.upper_bounds, expected_upper)
    np.testing.assert_allclose(artifact.medians, scaler.center_)
    np.testing.assert_allclose(artifact.scales, scaler.scale_)


def test_validation_outlier_cannot_change_train_only_clipping_or_scaler():
    train = _vectors()
    config = RegimeModelConfig("kmeans", 3)
    expected = SklearnRegimeModel().fit(config, train)
    validation = _vectors(1, start_offset=len(train))[0]
    outlier_values = {name: 1e15 for name in FEATURE_NAMES}
    validation = replace(validation, values=outlier_values)

    actual = FitRegimeModelUseCase(SklearnRegimeModel()).execute(
        FitRegimeModelCommand(config, train, (validation,))
    ).artifact

    assert actual.lower_bounds == expected.lower_bounds
    assert actual.upper_bounds == expected.upper_bounds
    assert actual.medians == expected.medians
    assert actual.scales == expected.scales


@pytest.mark.parametrize("field", ["lower_bounds", "upper_bounds"])
def test_artifact_rejects_zero_width_clipping_bounds(field):
    artifact = SklearnRegimeModel().fit(RegimeModelConfig("kmeans", 3), _vectors())
    changes = {field: artifact.upper_bounds if field == "lower_bounds" else artifact.lower_bounds}
    with pytest.raises(ValueError, match="clipping bounds.*positive width"):
        replace(artifact, **changes)


@pytest.mark.parametrize("config", [
    RegimeModelConfig("kmeans", 3),
    RegimeModelConfig("gmm", 3, covariance_type="diag"),
])
def test_assignment_clips_outlier_with_persisted_train_bounds(config):
    vectors = _vectors()
    engine = SklearnRegimeModel()
    artifact = engine.fit(config, vectors)
    outlier = _vectors(1, start_offset=len(vectors))[0]
    outlier_values = dict(outlier.values)
    outlier_values.update({name: 1e12 for name in artifact.feature_names})
    outlier = replace(outlier, values=outlier_values)
    assignments = engine.assign(artifact, (outlier,))

    capped_values = dict(outlier.values)
    capped_values.update(dict(zip(artifact.feature_names, artifact.upper_bounds)))
    capped = replace(outlier, values=capped_values)
    assert assignments == engine.assign(artifact, (capped,))


@pytest.mark.parametrize("bad_value", [-1.0, 0.0, 5e-7])
def test_diag_gmm_artifact_rejects_invalid_covariance_on_load(bad_value):
    artifact = SklearnRegimeModel().fit(
        RegimeModelConfig("gmm", 3, covariance_type="diag", regularization=1e-6),
        _vectors(),
    )
    covariances = [list(row) for row in artifact.covariances]
    covariances[0][0] = bad_value
    with pytest.raises(ValueError, match="covariance.*regularization floor"):
        replace(artifact, covariances=tuple(tuple(row) for row in covariances))


@pytest.mark.parametrize("kind", ["asymmetric", "indefinite", "below_floor"])
def test_tied_gmm_artifact_rejects_invalid_covariance_on_load(kind):
    artifact = SklearnRegimeModel().fit(
        RegimeModelConfig("gmm", 3, covariance_type="tied", regularization=1e-6),
        _vectors(),
    )
    width = len(artifact.feature_names)
    matrix = np.eye(width)
    if kind == "asymmetric":
        matrix[0, 1] = 0.5
    elif kind == "indefinite":
        matrix[0, 0] = -1.0
    else:
        matrix[0, 0] = 5e-7
    repeated = tuple(tuple(matrix.reshape(-1)) for _ in range(artifact.config.cluster_count))
    with pytest.raises(ValueError, match="covariance"):
        replace(artifact, covariances=repeated)


@pytest.mark.parametrize("field", ["means", "covariances", "weights"])
def test_artifact_fingerprint_rejects_component_parameter_tampering(field):
    config = RegimeModelConfig("gmm", 3, covariance_type="diag")
    artifact = SklearnRegimeModel().fit(config, _vectors())
    if field == "means":
        rows = [list(row) for row in artifact.means]
        rows[0][0] += 0.01
        changes = {field: tuple(tuple(row) for row in rows)}
    elif field == "covariances":
        rows = [list(row) for row in artifact.covariances]
        rows[0][0] += 0.01
        changes = {field: tuple(tuple(row) for row in rows)}
    else:
        weights = list(artifact.weights)
        weights[0] += 0.01
        weights[1] -= 0.01
        changes = {field: tuple(weights)}
    with pytest.raises(ValueError, match="fingerprint"):
        replace(artifact, **changes)
