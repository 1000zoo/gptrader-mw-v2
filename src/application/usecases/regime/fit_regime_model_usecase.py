from dataclasses import dataclass

from src.domain.ports.regime_model_port import RegimeModelPort
from src.domain.regime.chart_features import (
    CHART_FEATURE_REGISTRY_V1,
    CHART_FEATURE_SCHEMA_VERSION,
    ChartFeatureVector,
)
from src.domain.regime.model import ClusterAssignment, RegimeModelArtifact, RegimeModelConfig


@dataclass(frozen=True)
class FitRegimeModelCommand:
    config: RegimeModelConfig
    cluster_fit_vectors: tuple[ChartFeatureVector, ...]
    validation_vectors: tuple[ChartFeatureVector, ...]

    def __post_init__(self) -> None:
        if not self.cluster_fit_vectors:
            raise ValueError("cluster-fit vectors cannot be empty")
        _validate_vectors(self.cluster_fit_vectors, "cluster-fit")
        if self.validation_vectors:
            _validate_vectors(self.validation_vectors, "validation")
            first = self.cluster_fit_vectors[0]
            if any(vector.symbol != first.symbol for vector in self.validation_vectors):
                raise ValueError("validation vector symbol must match cluster-fit symbol")
            if any(vector.schema_version != first.schema_version for vector in self.validation_vectors):
                raise ValueError("validation vector schema must match cluster-fit schema")
            if self.validation_vectors[0].anchor_at <= self.cluster_fit_vectors[-1].anchor_at:
                raise ValueError("validation vectors must follow cluster-fit vectors")


@dataclass(frozen=True)
class FitRegimeModelResult:
    artifact: RegimeModelArtifact
    validation_assignments: tuple[ClusterAssignment, ...]


class FitRegimeModelUseCase:
    def __init__(self, engine: RegimeModelPort) -> None:
        self._engine = engine

    def execute(self, command: FitRegimeModelCommand) -> FitRegimeModelResult:
        artifact = self._engine.fit(command.config, command.cluster_fit_vectors)
        assignments = self._engine.assign(artifact, command.validation_vectors) if command.validation_vectors else ()
        return FitRegimeModelResult(artifact=artifact, validation_assignments=assignments)


def _validate_vectors(vectors: tuple[ChartFeatureVector, ...], label: str) -> None:
    first = vectors[0]
    expected_names = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)
    if any(vector.schema_version != CHART_FEATURE_SCHEMA_VERSION for vector in vectors):
        raise ValueError(f"{label} vectors must use the V1 feature schema")
    if any(tuple(vector.values) != expected_names for vector in vectors):
        raise ValueError(f"{label} vectors must use ordered V1 features")
    if any(vector.symbol != first.symbol for vector in vectors):
        raise ValueError(f"{label} vector symbols must be consistent")
    if any(vector.schema_version != first.schema_version for vector in vectors):
        raise ValueError(f"{label} vector schemas must be consistent")
    anchors = tuple(vector.anchor_at for vector in vectors)
    if any(current <= previous for previous, current in zip(anchors, anchors[1:])):
        raise ValueError(f"{label} vector anchors must be chronological and unique")


__all__ = ["FitRegimeModelCommand", "FitRegimeModelResult", "FitRegimeModelUseCase"]
