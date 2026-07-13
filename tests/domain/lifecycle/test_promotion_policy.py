from decimal import Decimal

import pytest

from src.domain.lifecycle import (
    PromotionPolicy,
    StrategyEvaluation,
    StrategyLifecycleStatus,
)


def make_evaluation(
    status: StrategyLifecycleStatus = StrategyLifecycleStatus.DRY_RUN,
    metrics: dict[str, Decimal] | None = None,
) -> StrategyEvaluation:
    return StrategyEvaluation(
        evaluation_id="eval-1",
        target_id="generator-main",
        status=status,
        metrics={"sharpe": Decimal("1.8"), "win_rate": Decimal("0.55")}
        if metrics is None
        else metrics,
    )


def test_promotion_policy_approves_allowed_status_when_thresholds_pass():
    policy = PromotionPolicy(
        minimum_metrics={"sharpe": Decimal("1.5"), "win_rate": Decimal("0.5")},
        allowed_statuses=(StrategyLifecycleStatus.DRY_RUN,),
    )

    assert policy.can_promote(make_evaluation()) is True


def test_promotion_policy_rejects_disallowed_status():
    policy = PromotionPolicy(
        minimum_metrics={"sharpe": Decimal("1.5")},
        allowed_statuses=(StrategyLifecycleStatus.DRY_RUN,),
    )

    assert (
        policy.can_promote(
            make_evaluation(status=StrategyLifecycleStatus.BACKTESTED)
        )
        is False
    )


def test_promotion_policy_rejects_missing_required_metric():
    policy = PromotionPolicy(
        minimum_metrics={"sharpe": Decimal("1.5"), "win_rate": Decimal("0.5")},
        allowed_statuses=(StrategyLifecycleStatus.DRY_RUN,),
    )

    assert policy.can_promote(make_evaluation(metrics={"sharpe": Decimal("1.8")})) is False


def test_promotion_policy_rejects_metric_below_threshold():
    policy = PromotionPolicy(
        minimum_metrics={"sharpe": Decimal("1.5")},
        allowed_statuses=(StrategyLifecycleStatus.DRY_RUN,),
    )

    assert policy.can_promote(make_evaluation(metrics={"sharpe": Decimal("1.4")})) is False


def test_promotion_policy_rejects_empty_minimum_metrics():
    with pytest.raises(ValueError, match="minimum_metrics"):
        PromotionPolicy(
            minimum_metrics={},
            allowed_statuses=(StrategyLifecycleStatus.DRY_RUN,),
        )
