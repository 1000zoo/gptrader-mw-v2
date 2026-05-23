from decimal import Decimal

import pytest

from src.domain.lifecycle import StrategyEvaluation, StrategyLifecycleStatus


def test_strategy_evaluation_stores_status_metrics_and_metadata():
    evaluation = StrategyEvaluation(
        evaluation_id=" eval-1 ",
        target_id=" generator-main ",
        status=StrategyLifecycleStatus.BACKTESTED,
        metrics={" sharpe ": Decimal("1.8"), "max_drawdown": Decimal("0.08")},
        metadata={"dataset": "2026-q1"},
    )

    assert evaluation.evaluation_id == "eval-1"
    assert evaluation.target_id == "generator-main"
    assert evaluation.status is StrategyLifecycleStatus.BACKTESTED
    assert evaluation.metric(" sharpe ") == Decimal("1.8")
    assert evaluation.metric("missing") is None
    assert evaluation.metadata["dataset"] == "2026-q1"


def test_strategy_evaluation_rejects_blank_ids_and_metric_names():
    with pytest.raises(ValueError, match="evaluation_id"):
        StrategyEvaluation(
            evaluation_id=" ",
            target_id="generator-main",
            status=StrategyLifecycleStatus.BACKTESTED,
        )

    with pytest.raises(ValueError, match="metrics"):
        StrategyEvaluation(
            evaluation_id="eval-1",
            target_id="generator-main",
            status=StrategyLifecycleStatus.BACKTESTED,
            metrics={" ": Decimal("1")},
        )


def test_strategy_evaluation_defensively_copies_metrics_and_metadata():
    metrics = {"sharpe": Decimal("1.8")}
    metadata = {"dataset": "2026-q1"}

    evaluation = StrategyEvaluation(
        evaluation_id="eval-1",
        target_id="generator-main",
        status=StrategyLifecycleStatus.BACKTESTED,
        metrics=metrics,
        metadata=metadata,
    )
    metrics["sharpe"] = Decimal("0")
    metadata["dataset"] = "changed"

    assert evaluation.metric("sharpe") == Decimal("1.8")
    assert evaluation.metadata["dataset"] == "2026-q1"
    with pytest.raises(TypeError):
        evaluation.metrics["sharpe"] = Decimal("2")
    with pytest.raises(TypeError):
        evaluation.metadata["dataset"] = "changed"
