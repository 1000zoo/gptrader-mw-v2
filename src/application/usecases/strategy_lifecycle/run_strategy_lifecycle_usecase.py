from src.application.usecases.strategy_lifecycle.dto import (
    PromoteStrategyCommand,
    PromoteStrategyResult,
    RunStrategyLifecycleCommand,
    RunStrategyLifecycleResult,
)
from src.application.usecases.strategy_lifecycle.promote_strategy_usecase import (
    PromoteStrategyUseCase,
)
from src.domain.ports import StrategyRepositoryPort


class RunStrategyLifecycleUseCase:
    def __init__(self, strategy_repository: StrategyRepositoryPort) -> None:
        self._strategy_repository = strategy_repository
        self._promote_strategy = PromoteStrategyUseCase(strategy_repository)

    def execute(
        self,
        command: RunStrategyLifecycleCommand,
    ) -> RunStrategyLifecycleResult:
        evaluation_id = command.evaluation_id or self._latest_promotable_evaluation_id(
            target_id=command.target_id,
            command=command,
        )
        if evaluation_id is None:
            return RunStrategyLifecycleResult(
                promotion=PromoteStrategyResult(
                    promoted=False,
                    reason="evaluation not found",
                )
            )

        return RunStrategyLifecycleResult(
            promotion=self._promote_strategy.execute(
                PromoteStrategyCommand(
                    target_id=command.target_id,
                    evaluation_id=evaluation_id,
                    promoted_evaluation_id=command.promoted_evaluation_id,
                    policy=command.policy,
                    metadata=command.metadata,
                )
            )
        )

    def _latest_promotable_evaluation_id(
        self,
        target_id: str,
        command: RunStrategyLifecycleCommand,
    ) -> str | None:
        evaluations = self._strategy_repository.list_strategy_evaluations(target_id)
        for evaluation in reversed(evaluations):
            if command.policy.can_promote(evaluation):
                return evaluation.evaluation_id
        return None
