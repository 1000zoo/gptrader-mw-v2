from decimal import Decimal

from src.application.usecases.strategy_lifecycle import (
    RunStrategyLifecycleCommand,
    RunStrategyLifecycleUseCase,
)
from src.domain.lifecycle import (
    PromotionPolicy,
    StrategyEvaluation,
    StrategyLifecycleStatus,
)


class InMemoryStrategyRepository:
    def __init__(self, evaluations: tuple[StrategyEvaluation, ...]) -> None:
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
    evaluation_id: str,
    metrics: dict[str, Decimal] | None = None,
    status: StrategyLifecycleStatus = StrategyLifecycleStatus.DRY_RUN,
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


def test_run_strategy_lifecycle_usecase_promotes_latest_evaluation_by_default():
    repository = InMemoryStrategyRepository(
        (
            make_evaluation("eval-old", {"sharpe": Decimal("1.1")}),
            make_evaluation("eval-new"),
        )
    )

    result = RunStrategyLifecycleUseCase(repository).execute(
        RunStrategyLifecycleCommand(
            target_id="generator-main",
            promoted_evaluation_id="promoted-1",
            policy=make_policy(),
        )
    )

    assert result.promotion.promoted is True
    assert result.promotion.source_evaluation == make_evaluation("eval-new")
    assert repository.evaluations[-1].evaluation_id == "promoted-1"


def test_run_strategy_lifecycle_usecase_skips_promoted_evaluation_by_default():
    repository = InMemoryStrategyRepository(
        (
            make_evaluation("eval-dry-run"),
            make_evaluation("eval-promoted", status=StrategyLifecycleStatus.PROMOTED),
        )
    )

    result = RunStrategyLifecycleUseCase(repository).execute(
        RunStrategyLifecycleCommand(
            target_id="generator-main",
            promoted_evaluation_id="promoted-1",
            policy=make_policy(),
        )
    )

    assert result.promotion.promoted is True
    assert result.promotion.source_evaluation == make_evaluation("eval-dry-run")


def test_run_strategy_lifecycle_usecase_promotes_explicit_evaluation_id():
    repository = InMemoryStrategyRepository(
        (
            make_evaluation("eval-old"),
            make_evaluation("eval-new", {"sharpe": Decimal("1.1")}),
        )
    )

    result = RunStrategyLifecycleUseCase(repository).execute(
        RunStrategyLifecycleCommand(
            target_id="generator-main",
            evaluation_id="eval-old",
            promoted_evaluation_id="promoted-1",
            policy=make_policy(),
        )
    )

    assert result.promotion.promoted is True
    assert result.promotion.source_evaluation == make_evaluation("eval-old")


def test_run_strategy_lifecycle_usecase_reports_missing_target_evaluations():
    repository = InMemoryStrategyRepository(())

    result = RunStrategyLifecycleUseCase(repository).execute(
        RunStrategyLifecycleCommand(
            target_id="generator-main",
            promoted_evaluation_id="promoted-1",
            policy=make_policy(),
        )
    )

    assert result.promotion.promoted is False
    assert result.promotion.reason == "evaluation not found"
