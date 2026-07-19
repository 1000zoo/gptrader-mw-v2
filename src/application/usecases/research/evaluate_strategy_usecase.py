from src.application.usecases.research.dto import (
    EvaluateStrategyCommand,
    EvaluateStrategyResult,
    ResearchRunMode,
)
from src.domain.lifecycle import StrategyEvaluation, StrategyLifecycleStatus


class EvaluateStrategyUseCase:
    def execute(self, command: EvaluateStrategyCommand) -> EvaluateStrategyResult:
        status = self._status_for_mode(command.mode)
        return EvaluateStrategyResult(
            evaluation=StrategyEvaluation(
                evaluation_id=command.evaluation_id,
                target_id=command.target_id,
                status=status,
                metrics=command.metrics,
                metadata=command.metadata,
            )
        )

    def _status_for_mode(self, mode: ResearchRunMode) -> StrategyLifecycleStatus:
        if mode is ResearchRunMode.BACKTEST:
            return StrategyLifecycleStatus.BACKTESTED
        if mode is ResearchRunMode.DRY_RUN:
            return StrategyLifecycleStatus.DRY_RUN
        raise ValueError("unsupported research run mode")
