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


@dataclass(frozen=True)
class RunStrategyBacktestCycleCommand:
    cycle_id: str
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        cycle_id = self.cycle_id.strip()
        if not cycle_id:
            raise ValueError("cycle_id is required")

        object.__setattr__(self, "cycle_id", cycle_id)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata or {})),
        )


@dataclass(frozen=True)
class StrategyBacktestCycleItem:
    strategy_id: str
    evaluation_id: str | None
    succeeded: bool
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        strategy_id = self.strategy_id.strip()
        evaluation_id = self.evaluation_id.strip() if self.evaluation_id else None
        error_type = self.error_type.strip() if self.error_type else None
        error_message = self.error_message.strip() if self.error_message else None
        if not strategy_id:
            raise ValueError("strategy_id is required")
        if evaluation_id == "":
            raise ValueError("evaluation_id is required")

        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "evaluation_id", evaluation_id)
        object.__setattr__(self, "error_type", error_type)
        object.__setattr__(self, "error_message", error_message)


@dataclass(frozen=True)
class RunStrategyBacktestCycleResult:
    items: tuple[StrategyBacktestCycleItem, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))

    @property
    def succeeded_count(self) -> int:
        return sum(1 for item in self.items if item.succeeded)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if not item.succeeded)
