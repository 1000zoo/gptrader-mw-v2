from collections import UserList
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from sklearn.preprocessing import RobustScaler

from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.model import RegimeModelArtifact, RegimeModelConfig
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
    ThreeDayChartFeatureVector,
)
from src.infrastructure.regime.json_regime_artifact_repository import JsonRegimeArtifactRepository
from src.infrastructure.regime.sklearn_cluster_diagnostic import SklearnClusterDiagnostic
from src.infrastructure.regime.sklearn_regime_model import prune_correlated_features


REGISTRY = THREE_DAY_CHART_FEATURE_REGISTRY_V1
REGISTRY_NAMES = tuple(spec.name for spec in REGISTRY)
RETAINED = ("return_4h", "rv_4h", "atr_ratio_1d", "directional_efficiency_1d")


def _vectors(count: int = 36, *, start_offset: int = 0) -> tuple[ThreeDayChartFeatureVector, ...]:
    origin = datetime(2025, 1, 4, tzinfo=timezone.utc)
    vectors = []
    for index in range(start_offset, start_offset + count):
        cluster = index % 3
        values = {
            name: float(
                cluster * (column + 1) * 0.7
                + np.sin((index + 1) * (column + 2) * 0.113)
                + column * 0.019
            )
            for column, name in enumerate(REGISTRY_NAMES)
        }
        anchor = origin + timedelta(days=index)
        vectors.append(
            ThreeDayChartFeatureVector(
                symbol="BTCUSDT",
                anchor_at=anchor,
                window_start_at=anchor - timedelta(days=3),
                values=values,
            )
        )
    return tuple(vectors)


@pytest.mark.parametrize("seed", [20260714, 20260715, 20260716])
@pytest.mark.parametrize(
    "config_factory",
    [
        lambda seed: RegimeModelConfig("kmeans", 3, random_seed=seed),
        lambda seed: RegimeModelConfig("gmm", 3, random_seed=seed, covariance_type="diag"),
        lambda seed: RegimeModelConfig("gmm", 3, random_seed=seed, covariance_type="tied"),
    ],
)
def test_three_day_fit_supports_seeds_models_and_explicit_retained_names(seed, config_factory):
    fit = SklearnClusterDiagnostic().fit(
        config_factory(seed),
        _vectors(),
        REGISTRY,
        retained_feature_names=RETAINED,
    )

    assert isinstance(fit, ClusterDiagnosticFit)
    assert not isinstance(fit, RegimeModelArtifact)
    assert fit.schema_version == THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
    assert fit.feature_names == RETAINED
    assert fit.fingerprints == tuple(sorted(fit.fingerprints))


def test_refit_uses_block_local_clipping_and_scaling():
    vectors = _vectors(18)
    fit = SklearnClusterDiagnostic().fit(
        RegimeModelConfig("kmeans", 3), vectors, REGISTRY, retained_feature_names=RETAINED
    )
    indices = tuple(REGISTRY_NAMES.index(name) for name in RETAINED)
    raw = np.asarray([tuple(vector.values.values()) for vector in vectors])[:, indices]
    lower = np.quantile(raw, 0.005, axis=0)
    upper = np.quantile(raw, 0.995, axis=0)
    scaler = RobustScaler().fit(np.clip(raw, lower, upper))

    np.testing.assert_allclose(fit.lower_bounds, lower)
    np.testing.assert_allclose(fit.upper_bounds, upper)
    np.testing.assert_allclose(fit.medians, scaler.center_)
    np.testing.assert_allclose(fit.scales, scaler.scale_)


@pytest.mark.parametrize(
    "config",
    [
        RegimeModelConfig("kmeans", 3),
        RegimeModelConfig("gmm", 3, covariance_type="diag"),
        RegimeModelConfig("gmm", 3, covariance_type="tied"),
    ],
)
def test_array_only_assignment_is_reconstructible_and_model_specific(config):
    vectors = _vectors()
    engine = SklearnClusterDiagnostic()
    fit = engine.fit(config, vectors, REGISTRY, retained_feature_names=RETAINED)

    assignments = engine.assign(replace(fit), vectors, REGISTRY)

    assert len(assignments) == len(vectors)
    assert all(0 <= item.second_probability <= item.dominant_probability <= 1 for item in assignments)
    if config.model_type == "kmeans":
        assert all(item.distance is not None and item.distance >= 0 for item in assignments)
    else:
        assert all(item.distance is None for item in assignments)


def test_correlation_pruning_uses_supplied_registry_priority():
    matrix = np.asarray([[1.0, 2.0], [2.0, 4.0], [4.0, 8.0]])
    custom_registry = ("custom_b", "custom_a")

    assert prune_correlated_features(
        matrix, custom_registry, registry_names=custom_registry
    ) == ("custom_b",)
    with pytest.raises(ValueError, match="priority"):
        prune_correlated_features(
            matrix[:, ::-1], tuple(reversed(custom_registry)), registry_names=custom_registry
        )


def test_diagnostic_fails_closed_on_registry_schema_order_and_symbol():
    engine = SklearnClusterDiagnostic()
    config = RegimeModelConfig("kmeans", 3)
    vectors = _vectors()
    with pytest.raises(ValueError, match="registry"):
        engine.fit(config, vectors, tuple(reversed(REGISTRY)), retained_feature_names=RETAINED)
    wrong_symbol = replace(vectors[0], symbol="ETHUSDT")
    with pytest.raises(ValueError, match="symbol"):
        engine.assign(
            engine.fit(config, vectors, REGISTRY, retained_feature_names=RETAINED),
            (wrong_symbol,),
            REGISTRY,
        )
    wrong_schema = replace(vectors[0])
    object.__setattr__(wrong_schema, "schema_version", "other-schema")
    with pytest.raises(ValueError, match="schema"):
        engine.assign(
            engine.fit(config, vectors, REGISTRY, retained_feature_names=RETAINED),
            (wrong_schema,),
            REGISTRY,
        )


@pytest.mark.parametrize(
    "bad_spec",
    [
        SimpleNamespace(
            name=REGISTRY[0].name,
            family=REGISTRY[0].family,
            aggregation_minutes=REGISTRY[0].aggregation_minutes,
            lookback_minutes=REGISTRY[0].lookback_minutes,
            formula=REGISTRY[0].formula,
            null_policy=REGISTRY[0].null_policy,
            clipping_policy=REGISTRY[0].clipping_policy,
            scale_invariant=REGISTRY[0].scale_invariant,
        ),
        replace(REGISTRY[0], family=" returns "),
        replace(REGISTRY[0], name="return-4h"),
        replace(REGISTRY[0], aggregation_minutes=0),
        replace(REGISTRY[0], lookback_minutes=0),
        replace(REGISTRY[0], formula=" formula "),
        replace(REGISTRY[0], null_policy=" reject_window "),
        replace(REGISTRY[0], clipping_policy=" train_quantile_0.005_0.995 "),
        replace(REGISTRY[0], scale_invariant=1),
    ],
)
def test_diagnostic_rejects_malformed_registry_specs(bad_spec):
    registry = (bad_spec, *REGISTRY[1:])

    with pytest.raises(ValueError, match="registry"):
        SklearnClusterDiagnostic().fit(
            RegimeModelConfig("kmeans", 3),
            _vectors(),
            registry,
            retained_feature_names=RETAINED,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("formula", f"{REGISTRY[0].formula} amended"),
        ("family", "alternate_family"),
        ("aggregation_minutes", 30),
        ("lookback_minutes", 480),
        ("null_policy", "alternate_policy"),
        ("clipping_policy", "alternate_clipping"),
        ("scale_invariant", False),
    ],
)
def test_diagnostic_rejects_semantically_altered_three_day_registry(field, value):
    altered = replace(REGISTRY[0], **{field: value})
    registry = (altered, *REGISTRY[1:])

    with pytest.raises(ValueError, match="incompatible three-day registry"):
        SklearnClusterDiagnostic().fit(
            RegimeModelConfig("kmeans", 3),
            _vectors(),
            registry,
            retained_feature_names=RETAINED,
        )


def test_diagnostic_assign_rejects_semantically_altered_three_day_registry():
    engine = SklearnClusterDiagnostic()
    vectors = _vectors()
    fit = engine.fit(
        RegimeModelConfig("kmeans", 3),
        vectors,
        REGISTRY,
        retained_feature_names=RETAINED,
    )
    altered = replace(REGISTRY[0], formula=f"{REGISTRY[0].formula} amended")

    with pytest.raises(ValueError, match="incompatible three-day registry"):
        engine.assign(fit, vectors, (altered, *REGISTRY[1:]))


def test_diagnostic_accepts_non_list_sequence_registry():
    fit = SklearnClusterDiagnostic().fit(
        RegimeModelConfig("kmeans", 3),
        _vectors(),
        UserList(REGISTRY),
        retained_feature_names=RETAINED,
    )

    assert fit.feature_names == RETAINED


def test_diagnostic_fit_rejects_uniformly_tampered_three_day_schema():
    vectors = list(_vectors())
    for vector in vectors:
        object.__setattr__(vector, "schema_version", "other-schema")

    with pytest.raises(ValueError, match="schema"):
        SklearnClusterDiagnostic().fit(
            RegimeModelConfig("kmeans", 3),
            tuple(vectors),
            REGISTRY,
            retained_feature_names=RETAINED,
        )


def test_diagnostic_fit_rejects_duck_typed_feature_vectors():
    vectors = tuple(
        SimpleNamespace(
            symbol=vector.symbol,
            anchor_at=vector.anchor_at,
            schema_version=vector.schema_version,
            values=vector.values,
        )
        for vector in _vectors()
    )

    with pytest.raises(ValueError, match="three-day feature vectors"):
        SklearnClusterDiagnostic().fit(
            RegimeModelConfig("kmeans", 3),
            vectors,
            REGISTRY,
            retained_feature_names=RETAINED,
        )


@pytest.mark.parametrize("field", ["means", "weights", "covariances", "fingerprints"])
def test_diagnostic_fit_rejects_parameter_or_fingerprint_tampering(field):
    fit = SklearnClusterDiagnostic().fit(
        RegimeModelConfig("gmm", 3, covariance_type="diag"),
        _vectors(),
        REGISTRY,
        retained_feature_names=RETAINED,
    )
    if field in {"means", "covariances"}:
        rows = [list(row) for row in getattr(fit, field)]
        rows[0][0] += 0.01
        value = tuple(tuple(row) for row in rows)
    elif field == "weights":
        rows = list(fit.weights)
        rows[0] += 0.01
        rows[1] -= 0.01
        value = tuple(rows)
    else:
        value = ("tampered", *fit.fingerprints[1:])
    with pytest.raises(ValueError, match="fingerprint"):
        replace(fit, **{field: value})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("scales", (1.0,), "shape"),
        ("means", ((float("nan"),),) * 3, "shape|finite"),
        ("schema_version", " three-day ", "schema"),
        ("symbol", "btcusdt", "symbol"),
        ("feature_names", ("return_4h", "return_4h", "atr_ratio_1d", "directional_efficiency_1d"), "feature"),
    ],
)
def test_diagnostic_fit_rejects_invalid_shapes_nonfinite_and_noncanonical_identity(field, value, message):
    fit = SklearnClusterDiagnostic().fit(
        RegimeModelConfig("kmeans", 3), _vectors(), REGISTRY, retained_feature_names=RETAINED
    )
    with pytest.raises(ValueError, match=message):
        replace(fit, **{field: value})


def test_diagnostic_fit_has_no_runtime_repository_serialization(tmp_path):
    fit = SklearnClusterDiagnostic().fit(
        RegimeModelConfig("kmeans", 3), _vectors(), REGISTRY, retained_feature_names=RETAINED
    )
    repository = JsonRegimeArtifactRepository(tmp_path)

    with pytest.raises((TypeError, ValueError), match="artifact"):
        repository.save_model(fit)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["covariances", "distance_thresholds"])
def test_diagnostic_fit_rejects_mutable_numeric_containers(field):
    fit = SklearnClusterDiagnostic().fit(
        RegimeModelConfig("gmm", 3, covariance_type="diag"),
        _vectors(),
        REGISTRY,
        retained_feature_names=RETAINED,
    )
    with pytest.raises(ValueError, match="tuple|shape|distance"):
        replace(fit, **{field: list(getattr(fit, field))})


@pytest.mark.parametrize("covariance_type", ["diag", "tied"])
def test_diagnostic_fit_rejects_covariance_below_regularization_floor(covariance_type):
    fit = SklearnClusterDiagnostic().fit(
        RegimeModelConfig("gmm", 3, covariance_type=covariance_type, regularization=1e-6),
        _vectors(),
        REGISTRY,
        retained_feature_names=RETAINED,
    )
    if covariance_type == "diag":
        rows = [list(row) for row in fit.covariances]
        rows[0][0] = 5e-7
    else:
        matrix = np.eye(len(RETAINED))
        matrix[0, 0] = 5e-7
        rows = [list(matrix.reshape(-1)) for _ in range(fit.config.cluster_count)]
    with pytest.raises(ValueError, match="covariance.*floor"):
        replace(fit, covariances=tuple(tuple(row) for row in rows))
