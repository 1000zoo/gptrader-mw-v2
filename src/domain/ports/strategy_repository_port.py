from typing import Protocol, runtime_checkable

from src.domain.lifecycle import (
    SignalGeneratorDefinition,
    StrategyDefinition,
    StrategyEvaluation,
)


@runtime_checkable
class StrategyRepositoryPort(Protocol):
    def save_strategy_definition(self, definition: StrategyDefinition) -> None:
        ...

    def load_strategy_definition(self, strategy_id: str) -> StrategyDefinition | None:
        ...

    def save_signal_generator_definition(
        self,
        definition: SignalGeneratorDefinition,
    ) -> None:
        ...

    def load_signal_generator_definition(
        self,
        generator_id: str,
    ) -> SignalGeneratorDefinition | None:
        ...

    def save_strategy_evaluation(self, evaluation: StrategyEvaluation) -> None:
        ...

    def list_strategy_evaluations(self, target_id: str) -> tuple[StrategyEvaluation, ...]:
        ...
