from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from src.domain.lifecycle import (
    PromotionPolicy,
    SignalGeneratorDefinition,
    StrategyDefinition,
    StrategyEvaluation,
)


@dataclass(frozen=True)
class RegisterStrategyCommand:
    strategy_definition: StrategyDefinition | None = None
    signal_generator_definition: SignalGeneratorDefinition | None = None

    def __post_init__(self) -> None:
        if (
            self.strategy_definition is None
            and self.signal_generator_definition is None
        ):
            raise ValueError("definition is required")


@dataclass(frozen=True)
class RegisterStrategyResult:
    strategy_definition: StrategyDefinition | None = None
    signal_generator_definition: SignalGeneratorDefinition | None = None


@dataclass(frozen=True)
class PromoteStrategyCommand:
    target_id: str
    evaluation_id: str
    promoted_evaluation_id: str
    policy: PromotionPolicy
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        target_id = self.target_id.strip()
        evaluation_id = self.evaluation_id.strip()
        promoted_evaluation_id = self.promoted_evaluation_id.strip()
        if not target_id:
            raise ValueError("target_id is required")
        if not evaluation_id:
            raise ValueError("evaluation_id is required")
        if not promoted_evaluation_id:
            raise ValueError("promoted_evaluation_id is required")

        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "evaluation_id", evaluation_id)
        object.__setattr__(self, "promoted_evaluation_id", promoted_evaluation_id)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata or {})),
        )


@dataclass(frozen=True)
class PromoteStrategyResult:
    promoted: bool
    reason: str
    source_evaluation: StrategyEvaluation | None = None
    promoted_evaluation: StrategyEvaluation | None = None


@dataclass(frozen=True)
class RunStrategyLifecycleCommand:
    target_id: str
    promoted_evaluation_id: str
    policy: PromotionPolicy
    evaluation_id: str | None = None
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        target_id = self.target_id.strip()
        promoted_evaluation_id = self.promoted_evaluation_id.strip()
        evaluation_id = self.evaluation_id.strip() if self.evaluation_id else None
        if not target_id:
            raise ValueError("target_id is required")
        if not promoted_evaluation_id:
            raise ValueError("promoted_evaluation_id is required")
        if evaluation_id == "":
            raise ValueError("evaluation_id is required")

        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "promoted_evaluation_id", promoted_evaluation_id)
        object.__setattr__(self, "evaluation_id", evaluation_id)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata or {})),
        )


@dataclass(frozen=True)
class RunStrategyLifecycleResult:
    promotion: PromoteStrategyResult
