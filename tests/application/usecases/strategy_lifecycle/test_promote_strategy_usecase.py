from decimal import Decimal

from src.application.usecases.strategy_lifecycle import (
    PromoteStrategyCommand,
    PromoteStrategyUseCase,
)
from src.domain.lifecycle import (
    PromotionPolicy,
    StrategyEvaluation,
    StrategyLifecycleStatus,
)


class InMemoryStrategyRepository:
    def __init__(self, evaluations: tuple[StrategyEvaluation, ...] = ()) -> None:
        self.evaluations: list[StrategyEvaluation] = list(evaluations)

    def save_strategy_evaluation(self, evaluation: StrategyEvaluation) -> None:
        self.evaluations.append(evaluation)

    def list_strategy_evaluations(self, target_id: str) -> tuple[StrategyEvaluation, ...]:
        return tuple(
            evaluation
            for evaluation in self.evaluations
            if evaluation.target_id == target_id
        )


def make_evaluation(
    evaluation_id: str = "eval-1",
    status: StrategyLifecycleStatus = StrategyLifecycleStatus.DRY_RUN,
    metrics: dict[str, Decimal] | None = None,
) -> StrategyEvaluation:
    return StrategyEvaluation(
        evaluation_id=evaluation_id,
        target_id="generator-main",
        status=status,
        metrics=metrics or {"sharpe": Decimal("1.8")},
    )


def make_policy() -> PromotionPolicy:
    return PromotionPolicy(
        minimum_metrics={"sharpe": Decimal("1.5")},
        allowed_statuses=(StrategyLifecycleStatus.DRY_RUN,),
    )


def test_promote_strategy_usecase_saves_promoted_evaluation_when_policy_passes():
    repository = InMemoryStrategyRepository((make_evaluation(),))

    result = PromoteStrategyUseCase(repository).execute(
        PromoteStrategyCommand(
            target_id="generator-main",
            evaluation_id="eval-1",
            promoted_evaluation_id="promoted-1",
            policy=make_policy(),
        )
    )

    assert result.promoted is True
    assert result.source_evaluation == make_evaluation()
    assert result.promoted_evaluation is not None
    assert result.promoted_evaluation.evaluation_id == "promoted-1"
    assert result.promoted_evaluation.target_id == "generator-main"
    assert result.promoted_evaluation.status is StrategyLifecycleStatus.PROMOTED
    assert repository.evaluations[-1] == result.promoted_evaluation


def test_promote_strategy_usecase_rejects_when_policy_fails():
    repository = InMemoryStrategyRepository(
        (make_evaluation(metrics={"sharpe": Decimal("1.2")}),)
    )

    result = PromoteStrategyUseCase(repository).execute(
        PromoteStrategyCommand(
            target_id="generator-main",
            evaluation_id="eval-1",
            promoted_evaluation_id="promoted-1",
            policy=make_policy(),
        )
    )

    assert result.promoted is False
    assert result.reason == "promotion policy rejected evaluation"
    assert result.promoted_evaluation is None
    assert len(repository.evaluations) == 1


def test_promote_strategy_usecase_reports_missing_evaluation():
    repository = InMemoryStrategyRepository()

    result = PromoteStrategyUseCase(repository).execute(
        PromoteStrategyCommand(
            target_id="generator-main",
            evaluation_id="eval-missing",
            promoted_evaluation_id="promoted-1",
            policy=make_policy(),
        )
    )

    assert result.promoted is False
    assert result.reason == "evaluation not found"
    assert result.source_evaluation is None
    assert result.promoted_evaluation is None
