from datetime import datetime, timezone

from scripts.discover_metrics_entry_alpha import (
    Condition,
    ForwardOutcome,
    Observation,
    Rule,
    RuleMonthResult,
    evaluate_rules,
    select_walk_forward,
)


UTC = timezone.utc


def _month(value: str) -> datetime:
    return datetime.fromisoformat(f"{value}-01T00:00:00+00:00").astimezone(UTC)


def test_forward_outcome_subtracts_round_trip_cost() -> None:
    outcome = ForwardOutcome.from_prices(
        direction=1,
        entry_price=100.0,
        future_price=100.3,
        round_trip_cost=0.0012,
    )

    assert round(outcome.gross_return, 6) == 0.003
    assert round(outcome.net_return, 6) == 0.0018
    assert outcome.won is True


def test_walk_forward_selection_uses_only_trailing_train_months() -> None:
    rows = []
    for month in ("2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"):
        rows.extend(
            (
                RuleMonthResult("stable", 15, month, 20, 0.60, 0.001, 0.02),
                RuleMonthResult("future-winner", 15, month, 20, 0.40, -0.001, -0.02),
            )
        )
    rows.extend(
        (
            RuleMonthResult("stable", 15, "2026-01", 20, 0.40, -0.001, -0.02),
            RuleMonthResult("future-winner", 15, "2026-01", 20, 0.90, 0.005, 0.10),
        )
    )

    folds = select_walk_forward(
        rows,
        test_months=("2026-01",),
        train_months=6,
        top_k=1,
        min_train_signals=60,
        min_positive_train_months=4,
    )

    assert folds[0]["selected_rule_ids"] == ["stable@15m"]
    assert folds[0]["oos_average_net_return"] == -0.001


def test_rule_evaluation_purges_labels_crossing_month_boundary() -> None:
    observations = (
        Observation(
            datetime.fromisoformat("2025-12-31T23:55:00+00:00"),
            100.0,
            {"signal": 1.0},
        ),
        Observation(
            datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
            101.0,
            {"signal": 1.0},
        ),
    )
    rule = Rule("cross-month", 1, (Condition("signal", ">=", 1.0),))

    rows = evaluate_rules(
        observations,
        rules=(rule,),
        horizons=(5,),
        round_trip_cost=0.0,
    )

    assert rows == ()
