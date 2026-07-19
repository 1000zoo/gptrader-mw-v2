from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Sequence

from src.domain.lifecycle.strategy_evaluation import (
    StrategyEvaluation,
    StrategyLifecycleStatus,
)


@dataclass(frozen=True)
class PromotionPolicy:
    minimum_metrics: Mapping[str, Decimal]
    allowed_statuses: Sequence[StrategyLifecycleStatus]

    def __post_init__(self) -> None:
        minimum_metrics = {
            name.strip(): threshold for name, threshold in self.minimum_metrics.items()
        }
        if not minimum_metrics:
            raise ValueError("minimum_metrics are required")
        if any(not name for name in minimum_metrics):
            raise ValueError("minimum_metrics must not contain blank names")

        allowed_statuses = tuple(self.allowed_statuses)
        if not allowed_statuses:
            raise ValueError("allowed_statuses are required")

        object.__setattr__(
            self,
            "minimum_metrics",
            MappingProxyType(minimum_metrics),
        )
        object.__setattr__(self, "allowed_statuses", allowed_statuses)

    def can_promote(self, evaluation: StrategyEvaluation) -> bool:
        if evaluation.status not in self.allowed_statuses:
            return False

        for name, threshold in self.minimum_metrics.items():
            value = evaluation.metric(name)
            if value is None or value < threshold:
                return False

        return True
