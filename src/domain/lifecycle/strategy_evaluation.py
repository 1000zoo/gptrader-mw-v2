from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class StrategyLifecycleStatus(Enum):
    DRAFT = "draft"
    BACKTESTED = "backtested"
    DRY_RUN = "dry_run"
    PROMOTED = "promoted"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class StrategyEvaluation:
    evaluation_id: str
    target_id: str
    status: StrategyLifecycleStatus
    metrics: Mapping[str, Decimal] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        evaluation_id = self.evaluation_id.strip()
        target_id = self.target_id.strip()
        if not evaluation_id:
            raise ValueError("evaluation_id is required")
        if not target_id:
            raise ValueError("target_id is required")

        metrics = {name.strip(): value for name, value in self.metrics.items()}
        if any(not name for name in metrics):
            raise ValueError("metrics must not contain blank names")

        object.__setattr__(self, "evaluation_id", evaluation_id)
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "metrics", MappingProxyType(metrics))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def metric(self, name: str) -> Decimal | None:
        return self.metrics.get(name.strip())
