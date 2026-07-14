from typing import Protocol, runtime_checkable

from src.domain.regime.chart_features import ChartFeatureVector
from src.domain.regime.model import ClusterAssignment, RegimeModelArtifact, RegimeModelConfig


@runtime_checkable
class RegimeModelPort(Protocol):
    def fit(
        self,
        config: RegimeModelConfig,
        vectors: tuple[ChartFeatureVector, ...],
    ) -> RegimeModelArtifact:
        ...

    def assign(
        self,
        artifact: RegimeModelArtifact,
        vectors: tuple[ChartFeatureVector, ...],
    ) -> tuple[ClusterAssignment, ...]:
        ...


__all__ = ["RegimeModelPort"]
