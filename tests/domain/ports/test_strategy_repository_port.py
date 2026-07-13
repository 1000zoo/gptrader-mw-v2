from decimal import Decimal
from typing import Protocol

from src.domain.lifecycle import (
    SignalGeneratorDefinition,
    StrategyDefinition,
    StrategyEvaluation,
    StrategyLifecycleStatus,
)
from src.domain.ports import StrategyRepositoryPort


class InMemoryStrategyRepositoryPort:
    def __init__(self) -> None:
        self.strategies: dict[str, StrategyDefinition] = {}
        self.generators: dict[str, SignalGeneratorDefinition] = {}
        self.evaluations: list[StrategyEvaluation] = []

    def save_strategy_definition(self, definition: StrategyDefinition) -> None:
        self.strategies[definition.strategy_id] = definition

    def load_strategy_definition(self, strategy_id: str) -> StrategyDefinition | None:
        return self.strategies.get(strategy_id)

    def save_signal_generator_definition(
        self,
        definition: SignalGeneratorDefinition,
    ) -> None:
        self.generators[definition.generator_id] = definition

    def load_signal_generator_definition(
        self,
        generator_id: str,
    ) -> SignalGeneratorDefinition | None:
        return self.generators.get(generator_id)

    def save_strategy_evaluation(self, evaluation: StrategyEvaluation) -> None:
        self.evaluations.append(evaluation)

    def list_strategy_evaluations(self, target_id: str) -> tuple[StrategyEvaluation, ...]:
        return tuple(
            evaluation
            for evaluation in self.evaluations
            if evaluation.target_id == target_id
        )


def test_strategy_repository_port_is_protocol_contract():
    assert issubclass(StrategyRepositoryPort, Protocol)


def test_strategy_repository_port_saves_lifecycle_models():
    strategy = StrategyDefinition(
        strategy_id="mean-reversion",
        name="Mean Reversion",
        implementation="src.domain.strategy.implementations.mean_reversion",
        version="1",
    )
    generator = SignalGeneratorDefinition(
        generator_id="generator-1",
        name="Main Generator",
        strategy_ids=("mean-reversion",),
    )
    evaluation = StrategyEvaluation(
        evaluation_id="eval-1",
        target_id="generator-1",
        status=StrategyLifecycleStatus.BACKTESTED,
        metrics={"sharpe": Decimal("1.5")},
    )
    repository = InMemoryStrategyRepositoryPort()

    repository.save_strategy_definition(strategy)
    repository.save_signal_generator_definition(generator)
    repository.save_strategy_evaluation(evaluation)

    assert isinstance(repository, StrategyRepositoryPort)
    assert repository.load_strategy_definition("mean-reversion") == strategy
    assert repository.load_signal_generator_definition("generator-1") == generator
    assert repository.list_strategy_evaluations("generator-1") == (evaluation,)
