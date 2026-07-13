from src.application.usecases.strategy_lifecycle.dto import (
    RegisterStrategyCommand,
    RegisterStrategyResult,
)
from src.domain.ports import StrategyRepositoryPort


class RegisterStrategyUseCase:
    def __init__(self, strategy_repository: StrategyRepositoryPort) -> None:
        self._strategy_repository = strategy_repository

    def execute(self, command: RegisterStrategyCommand) -> RegisterStrategyResult:
        if command.strategy_definition is not None:
            self._strategy_repository.save_strategy_definition(
                command.strategy_definition
            )

        if command.signal_generator_definition is not None:
            self._strategy_repository.save_signal_generator_definition(
                command.signal_generator_definition
            )

        return RegisterStrategyResult(
            strategy_definition=command.strategy_definition,
            signal_generator_definition=command.signal_generator_definition,
        )
