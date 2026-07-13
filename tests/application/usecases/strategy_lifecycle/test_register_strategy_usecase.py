import pytest

from src.application.usecases.strategy_lifecycle import (
    RegisterStrategyCommand,
    RegisterStrategyUseCase,
)
from src.domain.lifecycle import SignalGeneratorDefinition, StrategyDefinition


class InMemoryStrategyRepository:
    def __init__(self) -> None:
        self.strategies: dict[str, StrategyDefinition] = {}
        self.generators: dict[str, SignalGeneratorDefinition] = {}

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


def test_register_strategy_usecase_saves_strategy_definition():
    repository = InMemoryStrategyRepository()
    definition = StrategyDefinition(
        strategy_id="mean-reversion",
        name="Mean Reversion",
        implementation="src.domain.strategy.implementations.mean_reversion",
        version="1",
    )

    result = RegisterStrategyUseCase(repository).execute(
        RegisterStrategyCommand(strategy_definition=definition)
    )

    assert result.strategy_definition == definition
    assert repository.load_strategy_definition("mean-reversion") == definition


def test_register_strategy_usecase_saves_signal_generator_definition():
    repository = InMemoryStrategyRepository()
    definition = SignalGeneratorDefinition(
        generator_id="generator-main",
        name="Main Generator",
        strategy_ids=("mean-reversion",),
    )

    result = RegisterStrategyUseCase(repository).execute(
        RegisterStrategyCommand(signal_generator_definition=definition)
    )

    assert result.signal_generator_definition == definition
    assert repository.load_signal_generator_definition("generator-main") == definition


def test_register_strategy_command_requires_a_definition():
    with pytest.raises(ValueError, match="definition is required"):
        RegisterStrategyCommand()
