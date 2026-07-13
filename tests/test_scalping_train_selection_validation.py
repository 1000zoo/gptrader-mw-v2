from decimal import Decimal

from scripts.validate_scalping_train_selection import (
    select_train_candidates,
    train_candidate_score,
)


def test_train_candidate_score_does_not_use_test_metrics() -> None:
    first = _result(
        "first",
        train_return="1.0",
        train_win_rate="0.90",
        train_roe="0.006",
        train_trades_per_day="20",
        test_return="-1.0",
    )
    second = {
        **first,
        "combo_id": "second",
        "test_return_ratio": "999",
        "test_gross_win_rate": "1",
    }

    assert train_candidate_score(first) == train_candidate_score(second)


def test_select_train_candidates_filters_by_train_only_thresholds() -> None:
    strong_train = _result(
        "strong-train",
        train_return="1.0",
        train_win_rate="0.90",
        train_roe="0.006",
        train_trades_per_day="20",
        test_return="-0.5",
    )
    weak_train_good_test = _result(
        "weak-train-good-test",
        train_return="-0.1",
        train_win_rate="0.99",
        train_roe="0.009",
        train_trades_per_day="30",
        test_return="10",
    )

    selected = select_train_candidates(
        [weak_train_good_test, strong_train],
        min_train_trades_per_day=Decimal("10"),
        min_train_gross_win_rate=Decimal("0.80"),
        min_train_average_gross_trade_roe=Decimal("0.003"),
        min_train_return_ratio=Decimal("0"),
        limit=10,
    )

    assert [result["combo_id"] for result in selected] == ["strong-train"]


def _result(
    combo_id: str,
    *,
    train_return: str,
    train_win_rate: str,
    train_roe: str,
    train_trades_per_day: str,
    test_return: str,
) -> dict[str, object]:
    return {
        "combo_id": combo_id,
        "train_return_ratio": train_return,
        "train_gross_win_rate": train_win_rate,
        "train_average_gross_trade_roe": train_roe,
        "train_trades_per_day": train_trades_per_day,
        "train_max_drawdown_ratio": "0.05",
        "test_return_ratio": test_return,
        "test_gross_win_rate": "0.1",
        "test_average_gross_trade_roe": "0.001",
        "test_trades_per_day": "1",
    }
