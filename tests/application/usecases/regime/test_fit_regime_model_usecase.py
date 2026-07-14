from datetime import datetime, timedelta, timezone

import pytest

from src.application.usecases.regime.fit_regime_model_usecase import (
    FitRegimeModelCommand,
    FitRegimeModelUseCase,
)
from src.domain.regime.chart_features import (
    CHART_FEATURE_REGISTRY_V1,
    CHART_FEATURE_SCHEMA_VERSION,
    ChartFeatureVector,
)
from src.domain.regime.model import (
    ClusterAssignment,
    RegimeModelArtifact,
    RegimeModelConfig,
    component_fingerprint,
)


def _vector(index: int, *, symbol: str = "BTCUSDT") -> ChartFeatureVector:
    anchor = datetime(2026, 1, 5, tzinfo=timezone.utc) + timedelta(hours=index * 4)
    return ChartFeatureVector(
        symbol=symbol,
        anchor_at=anchor,
        window_start_at=anchor - timedelta(days=7),
        schema_version=CHART_FEATURE_SCHEMA_VERSION,
        values={spec.name: float(index + column) for column, spec in enumerate(CHART_FEATURE_REGISTRY_V1)},
    )


class RecordingEngine:
    def __init__(self):
        self.fitted_anchors = ()
        self.assigned_anchors = ()

    def fit(self, config, vectors):
        self.fitted_anchors = tuple(vector.anchor_at for vector in vectors)
        feature_names = ("return_4h", "rv_1d")
        components = []
        for mean in ((0.0, 0.0), (1.0, 1.0), (2.0, 2.0)):
            fingerprint = component_fingerprint(
                model_type="kmeans",
                feature_schema_version=CHART_FEATURE_SCHEMA_VERSION,
                feature_names=feature_names,
                mean=mean,
                covariance=(),
                weight=None,
            )
            components.append((fingerprint, mean))
        components.sort()
        return RegimeModelArtifact(
            artifact_version="regime-model-v1",
            symbol="BTCUSDT",
            feature_schema_version=CHART_FEATURE_SCHEMA_VERSION,
            config=config,
            feature_names=feature_names,
            lower_bounds=(-1.0, -1.0),
            upper_bounds=(3.0, 3.0),
            medians=(0.0, 0.0),
            scales=(1.0, 1.0),
            weights=(1 / 3, 1 / 3, 1 / 3),
            means=tuple(mean for _, mean in components),
            covariances=(),
            fingerprints=tuple(fingerprint for fingerprint, _ in components),
            training_start_at=vectors[0].anchor_at,
            training_end_at=vectors[-1].anchor_at,
            distance_thresholds=(1.0, 1.0, 1.0),
        )

    def assign(self, artifact, vectors):
        self.assigned_anchors = tuple(vector.anchor_at for vector in vectors)
        return tuple(ClusterAssignment(artifact.fingerprints[0], 0.8, 0.2, 0.1) for _ in vectors)


def test_fit_uses_only_cluster_fit_vectors_and_validation_only_for_inference():
    train = tuple(_vector(index) for index in range(6))
    validation = tuple(_vector(index) for index in range(6, 9))
    engine = RecordingEngine()

    result = FitRegimeModelUseCase(engine).execute(
        FitRegimeModelCommand(
            config=RegimeModelConfig("kmeans", 3),
            cluster_fit_vectors=train,
            validation_vectors=validation,
        )
    )

    assert engine.fitted_anchors == tuple(vector.anchor_at for vector in train)
    assert engine.assigned_anchors == tuple(vector.anchor_at for vector in validation)
    assert result.artifact.training_end_at == train[-1].anchor_at
    assert len(result.validation_assignments) == len(validation)


@pytest.mark.parametrize("bad_case", ["empty_train", "unordered", "symbol", "schema", "overlap"])
def test_command_rejects_invalid_vector_contracts(bad_case):
    train = tuple(_vector(index) for index in range(4))
    validation = (_vector(4),)
    if bad_case == "empty_train":
        train = ()
    elif bad_case == "unordered":
        train = (train[1], train[0], *train[2:])
    elif bad_case == "symbol":
        validation = (_vector(4, symbol="ETHUSDT"),)
    elif bad_case == "schema":
        object.__setattr__(validation[0], "schema_version", "bad")
    elif bad_case == "overlap":
        validation = (_vector(3),)

    with pytest.raises(ValueError):
        FitRegimeModelCommand(RegimeModelConfig("kmeans", 3), train, validation)
