from src.application.usecases.strategy_lifecycle.dto import (
    PromoteStrategyCommand,
    PromoteStrategyResult,
)
from src.domain.lifecycle import StrategyEvaluation, StrategyLifecycleStatus
from src.domain.ports import StrategyRepositoryPort


class PromoteStrategyUseCase:
    def __init__(self, strategy_repository: StrategyRepositoryPort) -> None:
        self._strategy_repository = strategy_repository

    def execute(self, command: PromoteStrategyCommand) -> PromoteStrategyResult:
        source_evaluation = self._find_evaluation(
            target_id=command.target_id,
            evaluation_id=command.evaluation_id,
        )
        if source_evaluation is None:
            return PromoteStrategyResult(
                promoted=False,
                reason="evaluation not found",
            )

        if not command.policy.can_promote(source_evaluation):
            return PromoteStrategyResult(
                promoted=False,
                reason="promotion policy rejected evaluation",
                source_evaluation=source_evaluation,
            )

        promoted_evaluation = StrategyEvaluation(
            evaluation_id=command.promoted_evaluation_id,
            target_id=source_evaluation.target_id,
            status=StrategyLifecycleStatus.PROMOTED,
            metrics=source_evaluation.metrics,
            metadata={
                **dict(source_evaluation.metadata),
                **dict(command.metadata),
                "source_evaluation_id": source_evaluation.evaluation_id,
            },
        )
        self._strategy_repository.save_strategy_evaluation(promoted_evaluation)

        return PromoteStrategyResult(
            promoted=True,
            reason="promoted",
            source_evaluation=source_evaluation,
            promoted_evaluation=promoted_evaluation,
        )

    def _find_evaluation(
        self,
        target_id: str,
        evaluation_id: str,
    ) -> StrategyEvaluation | None:
        for evaluation in self._strategy_repository.list_strategy_evaluations(target_id):
            if evaluation.evaluation_id == evaluation_id:
                return evaluation
        return None
