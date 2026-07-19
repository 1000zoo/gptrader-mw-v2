from decimal import Decimal

from src.application.usecases.research import (
    EvaluateStrategyCommand,
    EvaluateStrategyUseCase,
    ResearchRunMode,
)
from src.domain.lifecycle import StrategyLifecycleStatus


def test_evaluate_strategy_usecase_creates_backtested_evaluation():
    usecase = EvaluateStrategyUseCase()

    result = usecase.execute(
        EvaluateStrategyCommand(
            evaluation_id="eval-1",
            target_id="strategy-1",
            mode=ResearchRunMode.BACKTEST,
            metrics={"sharpe": Decimal("1.2")},
            metadata={"dataset": "may"},
        )
    )

    assert result.evaluation.evaluation_id == "eval-1"
    assert result.evaluation.target_id == "strategy-1"
    assert result.evaluation.status is StrategyLifecycleStatus.BACKTESTED
    assert result.evaluation.metric("sharpe") == Decimal("1.2")
    assert result.evaluation.metadata["dataset"] == "may"


def test_evaluate_strategy_usecase_creates_dry_run_evaluation():
    usecase = EvaluateStrategyUseCase()

    result = usecase.execute(
        EvaluateStrategyCommand(
            evaluation_id="eval-2",
            target_id="generator-1",
            mode=ResearchRunMode.DRY_RUN,
            metrics={"win_rate": Decimal("0.55")},
        )
    )

    assert result.evaluation.status is StrategyLifecycleStatus.DRY_RUN
    assert result.evaluation.metric("win_rate") == Decimal("0.55")
