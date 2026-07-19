import hashlib
import json
from pathlib import Path
from typing import Optional

import pytest

from scripts.evaluate_train_selected_walk_forward import (
    evaluate_rows,
    load_jsonl_rows,
    main,
    render_markdown,
)


def _row(
    candidate_id: str,
    month: str,
    return_ratio: str,
    *,
    trades: int = 10,
    expectancy: str = "0.01",
    drawdown: str = "0.02",
    symbol: str = "BTCUSDT",
) -> dict[str, object]:
    year, month_number = (int(part) for part in month.split("-"))
    if month_number == 12:
        end = f"{year + 1:04d}-01-01T00:00:00+00:00"
    else:
        end = f"{year:04d}-{month_number + 1:02d}-01T00:00:00+00:00"
    return {
        "symbol": symbol,
        "candidate_id": candidate_id,
        "test_start_at": f"{month}-01T00:00:00+00:00",
        "test_end_at": end,
        "return_ratio": return_ratio,
        "trade_count": trades,
        "average_net_trade_expectancy_ratio": expectancy,
        "max_drawdown_ratio": drawdown,
        "net_win_rate": "0.5",
    }


def test_load_jsonl_rows_accepts_utf8_bom(tmp_path: Path) -> None:
    rows_path = tmp_path / "rows.jsonl"
    row = _row("candidate", "2024-01", "0.10")
    rows_path.write_text(json.dumps(row) + "\n", encoding="utf-8-sig")

    assert load_jsonl_rows(rows_path) == [row]


def test_selection_uses_only_prior_train_months_not_the_current_test_result() -> None:
    rows = [
        _row("steady", "2024-01", "0.10", expectancy="0.02", drawdown="0.01"),
        _row("steady", "2024-02", "0.08", expectancy="0.02", drawdown="0.01"),
        _row("lottery", "2024-01", "0.01", expectancy="0.001", drawdown="0.20"),
        _row("lottery", "2024-02", "0.01", expectancy="0.001", drawdown="0.20"),
        _row("steady", "2024-03", "0.02"),
        _row("lottery", "2024-03", "9.00"),
    ]

    payload = evaluate_rows(
        rows,
        symbol="BTCUSDT",
        train_months=2,
        top_k=1,
        start="2024-03",
        end="2024-04",
    )

    fold = payload["folds"][0]
    assert fold["test_month"] == "2024-03"
    assert fold["train_months"] == ["2024-01", "2024-02"]
    assert [selection["candidate_id"] for selection in fold["selections"]] == ["steady"]
    assert fold["selections"][0]["train_evidence"]["compounded_return"] == "0.1880"
    assert fold["selections"][0]["oos_test_result"]["return_ratio"] == "0.02"
    assert payload["top_1_oos_series"] == [
        {"month": "2024-03", "candidate_id": "steady", "return_ratio": "0.02"}
    ]


def test_train_winner_remains_selected_when_current_test_row_is_unavailable() -> None:
    rows = [
        _row("winner", "2024-01", "0.20", expectancy="0.03", drawdown="0.01"),
        _row("runner-up", "2024-01", "0.05", expectancy="0.01", drawdown="0.10"),
        _row("runner-up", "2024-02", "0.40"),
    ]

    payload = evaluate_rows(
        rows,
        symbol="BTCUSDT",
        train_months=1,
        top_k=2,
        start="2024-02",
        end="2024-03",
    )

    selection = payload["folds"][0]["selections"][0]
    assert selection["candidate_id"] == "winner"
    assert selection["oos_status"] == "unavailable"
    assert selection["oos_test_result"] is None
    assert payload["top_1_oos_series"] == [
        {
            "month": "2024-02",
            "candidate_id": "winner",
            "available": False,
            "return_ratio": "0",
        }
    ]
    assert [
        item["candidate_id"] for item in payload["folds"][0]["selections"]
    ] == ["winner", "runner-up"]
    assert payload["equal_weight_top_k_oos_series"] == [
        {"month": "2024-02", "available": False, "return_ratio": "0.20"}
    ]
    assert payload["folds"][0]["status"] == "partial_unavailable"
    assert selection["availability"] is False
    assert payload["top_1_oos_summary"]["unavailable_month_count"] == 1
    assert payload["equal_weight_top_k_oos_summary"]["unavailable_month_count"] == 1
    markdown = render_markdown(payload)
    assert "| 2024-02 | 1 | winner |" in markdown
    assert "| 0 (unavailable) |" in markdown
    assert "Unavailable months" in markdown


def test_numeric_duplicate_rows_are_deduplicated_but_conflicts_raise() -> None:
    original = _row("steady", "2024-01", "0.10", expectancy="0.010", drawdown="0.020")
    numerically_identical = {
        **original,
        "return_ratio": 0.1,
        "trade_count": "10.0",
        "average_net_trade_expectancy_ratio": ".01",
        "max_drawdown_ratio": "0.02",
        "net_win_rate": ".50",
    }
    rows = [
        original,
        numerically_identical,
        _row("steady", "2024-02", "0.05"),
    ]

    payload = evaluate_rows(rows, symbol="BTCUSDT", train_months=1, top_k=1)

    assert payload["input_row_count"] == 3
    assert payload["deduplicated_row_count"] == 2

    conflicting = {**numerically_identical, "return_ratio": "0.11"}
    with pytest.raises(ValueError, match="conflicting duplicate.*steady.*2024-01"):
        evaluate_rows([original, conflicting], symbol="BTCUSDT", train_months=1, top_k=1)


def test_duplicate_rows_canonicalize_nested_numeric_json_values() -> None:
    original = {
        **_row("steady", "2024-01", "0.10"),
        "cost_model": {
            "venue": "binance",
            "fee_rate": "0.0004",
            "details": [True, None, {"tier": 2}],
        },
    }
    equivalent = {
        **original,
        "return_ratio": 0.1,
        "cost_model": {
            "details": [True, None, {"tier": "2.0"}],
            "fee_rate": 0.0004,
            "venue": "binance",
        },
    }

    payload = evaluate_rows(
        [original, equivalent, _row("steady", "2024-02", "0.05")],
        symbol="BTCUSDT",
        train_months=1,
        top_k=1,
    )

    assert payload["deduplicated_row_count"] == 2


def test_duplicate_rows_conflict_when_nested_nonnumeric_value_differs() -> None:
    original = {
        **_row("steady", "2024-01", "0.10"),
        "cost_model": {"venue": "binance", "funding": "excluded"},
    }
    conflicting = {
        **original,
        "cost_model": {"venue": "other", "funding": "excluded"},
    }

    with pytest.raises(ValueError, match="conflicting duplicate.*steady.*2024-01"):
        evaluate_rows([original, conflicting], symbol="BTCUSDT", train_months=1, top_k=1)


def test_missing_calendar_train_month_or_failed_threshold_produces_cash_fold() -> None:
    rows = [
        _row("gapped", "2024-01", "0.10", trades=20),
        _row("gapped", "2024-03", "5.00", trades=20),
        _row("low-trades", "2024-02", "0.10", trades=1),
        _row("low-trades", "2024-03", "4.00", trades=1),
    ]

    payload = evaluate_rows(
        rows,
        symbol="BTCUSDT",
        train_months=2,
        top_k=2,
        min_train_trades=10,
        start="2024-03",
        end="2024-04",
    )

    assert payload["folds"] == [
        {
            "test_month": "2024-03",
            "test_start_at": "2024-03-01T00:00:00+00:00",
            "test_end_at": "2024-04-01T00:00:00+00:00",
            "train_months": ["2024-01", "2024-02"],
            "status": "cash",
            "selections": [],
            "top_1_oos_return_ratio": "0",
            "equal_weight_top_k_oos_return_ratio": "0",
        }
    ]
    assert payload["top_1_oos_summary"] == {
        "month_count": 1,
        "unavailable_month_count": 0,
        "positive_month_ratio": "0",
        "compounded_return": "0",
        "average_monthly_return": "0",
        "worst_monthly_result": "0",
    }


def test_globally_missing_prior_calendar_month_still_emits_cash_fold() -> None:
    rows = [_row("candidate", "2024-03", "0.50")]

    payload = evaluate_rows(
        rows,
        symbol="BTCUSDT",
        train_months=2,
        top_k=1,
        start="2024-03",
        end="2024-04",
    )

    fold = payload["folds"][0]
    assert fold["test_month"] == "2024-03"
    assert fold["train_months"] == ["2024-01", "2024-02"]
    assert fold["status"] == "cash"
    assert fold["selections"] == []


def test_explicit_range_emits_entirely_missing_oos_month_as_unavailable() -> None:
    rows = [
        _row("candidate", "2024-01", "0.10"),
        _row("candidate", "2024-02", "0.20"),
    ]

    payload = evaluate_rows(
        rows,
        symbol="BTCUSDT",
        train_months=1,
        top_k=1,
        start="2024-02",
        end="2024-04",
    )

    assert [fold["test_month"] for fold in payload["folds"]] == ["2024-02", "2024-03"]
    missing_fold = payload["folds"][1]
    assert missing_fold["status"] == "unavailable"
    assert missing_fold["test_start_at"] == "2024-03-01T00:00:00+00:00"
    assert missing_fold["test_end_at"] == "2024-04-01T00:00:00+00:00"
    assert missing_fold["selections"][0]["candidate_id"] == "candidate"
    assert missing_fold["selections"][0]["availability"] is False
    assert payload["top_1_oos_series"][1] == {
        "month": "2024-03",
        "candidate_id": "candidate",
        "available": False,
        "return_ratio": "0",
    }
    assert payload["top_1_oos_summary"]["unavailable_month_count"] == 1


def test_top_k_series_is_equal_weighted_and_summaries_are_compounded() -> None:
    rows = [
        _row("a", "2024-01", "0.10", expectancy="0.02", drawdown="0.01"),
        _row("b", "2024-01", "0.05", expectancy="0.01", drawdown="0.02"),
        _row("a", "2024-02", "0.20", expectancy="-0.01"),
        _row("b", "2024-02", "-0.10", expectancy="-0.01"),
    ]

    payload = evaluate_rows(
        rows,
        symbol="BTCUSDT",
        train_months=1,
        top_k=2,
        start="2024-02",
        end="2024-03",
    )

    assert payload["equal_weight_top_k_oos_series"] == [
        {"month": "2024-02", "return_ratio": "0.05"}
    ]
    assert payload["top_1_oos_summary"]["compounded_return"] == "0.20"
    assert payload["equal_weight_top_k_oos_summary"]["average_monthly_return"] == "0.05"


def test_candidate_eligibility_gate_boundaries() -> None:
    train_months = ["2024-01", "2024-02", "2024-03", "2024-04"]
    rows: list[dict[str, object]] = []

    def add_candidate(
        candidate_id: str,
        returns: list[str],
        *,
        trades: Optional[list[int]] = None,
        expectancy: str = "0.001",
    ) -> None:
        monthly_trades = trades or [10, 10, 10, 10]
        rows.extend(
            _row(
                candidate_id,
                month,
                return_ratio,
                trades=trade_count,
                expectancy=expectancy,
            )
            for month, return_ratio, trade_count in zip(
                train_months, returns, monthly_trades
            )
        )
        rows.append(_row(candidate_id, "2024-05", "0"))

    add_candidate("eligible", ["0.01", "0.01", "0", "0"])
    add_candidate("zero-return", ["0.25", "0.25", "-0.20", "-0.20"])
    add_candidate("too-few-positive", ["1.0", "-0.10", "-0.10", "-0.10"])
    add_candidate("zero-expectancy", ["0.01", "0.01", "0", "0"], expectancy="0")
    add_candidate(
        "too-few-trades",
        ["0.01", "0.01", "0", "0"],
        trades=[10, 10, 10, 9],
    )
    rows.extend(
        [
            _row("missing-month", "2024-01", "0.01"),
            _row("missing-month", "2024-02", "0.01"),
            _row("missing-month", "2024-03", "0.01"),
            _row("missing-month", "2024-05", "0"),
        ]
    )

    payload = evaluate_rows(
        rows,
        symbol="BTCUSDT",
        train_months=4,
        top_k=10,
        min_train_trades=40,
        start="2024-05",
        end="2024-06",
    )

    selections = payload["folds"][0]["selections"]
    assert [selection["candidate_id"] for selection in selections] == ["eligible"]
    evidence = selections[0]["train_evidence"]
    assert evidence["positive_month_count"] == 2
    assert evidence["total_trade_count"] == 40


def test_risk_score_and_exact_ties_have_deterministic_ranking() -> None:
    rows = [
        _row("zeta", "2024-01", "0.10", expectancy="0.01", drawdown="0.10"),
        _row("low-risk", "2024-01", "0.10", expectancy="0.01", drawdown="0.01"),
        _row("alpha", "2024-01", "0.10", expectancy="0.01", drawdown="0.10"),
        _row("alpha", "2024-02", "0.01"),
        _row("zeta", "2024-02", "0.02"),
        _row("low-risk", "2024-02", "0.03"),
    ]

    payload = evaluate_rows(
        rows,
        symbol="BTCUSDT",
        train_months=1,
        top_k=3,
        start="2024-02",
        end="2024-03",
    )

    assert [
        selection["candidate_id"] for selection in payload["folds"][0]["selections"]
    ] == ["low-risk", "alpha", "zeta"]
    assert payload["folds"][0]["selections"][1]["train_score"] == (
        payload["folds"][0]["selections"][2]["train_score"]
    )


def test_payload_reports_sorted_candidate_universe() -> None:
    rows = [
        _row("zeta", "2024-01", "0.10"),
        _row("alpha", "2024-01", "0.10"),
    ]

    payload = evaluate_rows(rows, symbol="BTCUSDT", train_months=1, top_k=1)

    assert payload["candidate_universe"] == ["alpha", "zeta"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trade_count", "-1"),
        ("trade_count", "1.5"),
        ("return_ratio", "-1"),
        ("return_ratio", "NaN"),
        ("max_drawdown_ratio", "-0.01"),
        ("average_net_trade_expectancy_ratio", "Infinity"),
    ],
)
def test_numeric_domains_are_validated(field: str, value: str) -> None:
    row = _row("candidate", "2024-01", "0.10")
    row[field] = value

    with pytest.raises(ValueError, match=field):
        evaluate_rows([row], symbol="BTCUSDT", train_months=1, top_k=1)


@pytest.mark.parametrize(
    "test_start_at",
    [
        "2024-01-02T00:00:00+00:00",
        "2024-01-01T00:01:00+00:00",
        "2024-01-01T00:00:00+09:00",
        "2024-01-01T00:00:00",
    ],
)
def test_test_start_must_be_exact_utc_month_boundary(test_start_at: str) -> None:
    row = _row("candidate", "2024-01", "0.10")
    row["test_start_at"] = test_start_at

    with pytest.raises(ValueError, match="test_start_at.*UTC month boundary"):
        evaluate_rows([row], symbol="BTCUSDT", train_months=1, top_k=1)


def test_test_end_must_be_exact_next_utc_month_boundary() -> None:
    row = _row("candidate", "2024-01", "0.10")
    row["test_end_at"] = "2024-01-31T23:59:59+00:00"

    with pytest.raises(ValueError, match="test_end_at.*next UTC month boundary"):
        evaluate_rows([row], symbol="BTCUSDT", train_months=1, top_k=1)


def test_symbol_is_required_on_every_row() -> None:
    row = _row("candidate", "2024-01", "0.10")
    del row["symbol"]

    with pytest.raises(ValueError, match="missing required fields: symbol"):
        evaluate_rows([row], symbol="BTCUSDT", train_months=1, top_k=1)


def test_symbol_filter_is_exact() -> None:
    rows = [
        _row("upper", "2024-01", "0.10", symbol="BTCUSDT"),
        _row("lower", "2024-01", "0.10", symbol="btcusdt"),
    ]

    payload = evaluate_rows(rows, symbol="BTCUSDT", train_months=1, top_k=1)

    assert payload["input_row_count"] == 1
    assert payload["candidate_universe"] == ["upper"]


def test_multi_fold_oos_summary_compounds_monthly_results() -> None:
    rows = [
        _row("candidate", "2024-01", "0.10"),
        _row("candidate", "2024-02", "0.10"),
        _row("candidate", "2024-03", "-0.05"),
    ]

    payload = evaluate_rows(
        rows,
        symbol="BTCUSDT",
        train_months=1,
        top_k=1,
        start="2024-02",
        end="2024-04",
    )

    assert payload["top_1_oos_series"] == [
        {"month": "2024-02", "candidate_id": "candidate", "return_ratio": "0.10"},
        {"month": "2024-03", "candidate_id": "candidate", "return_ratio": "-0.05"},
    ]
    assert payload["top_1_oos_summary"] == {
        "month_count": 2,
        "unavailable_month_count": 0,
        "positive_month_ratio": "0.5",
        "compounded_return": "0.0450",
        "average_monthly_return": "0.025",
        "worst_monthly_result": "-0.05",
    }


def test_cli_writes_concise_json_and_markdown(tmp_path: Path) -> None:
    rows_path = tmp_path / "rows.jsonl"
    payload_path = tmp_path / "evaluation.json"
    summary_path = tmp_path / "evaluation.md"
    rows = [
        _row("a", "2024-01", "0.10"),
        _row("a", "2024-02", "0.03"),
    ]
    rows_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    main(
        [
            "--rows-path",
            str(rows_path),
            "--symbol",
            "BTCUSDT",
            "--train-months",
            "1",
            "--top-k",
            "1",
            "--min-train-trades",
            "0",
            "--start",
            "2024-02",
            "--end",
            "2024-03",
            "--payload-path",
            str(payload_path),
            "--summary-path",
            str(summary_path),
        ]
    )

    written = json.loads(payload_path.read_text(encoding="utf-8"))
    markdown = summary_path.read_text(encoding="utf-8")
    assert written["fold_count"] == 1
    assert written["source_rows_path"] == str(rows_path)
    assert written["source_rows_sha256"] == hashlib.sha256(rows_path.read_bytes()).hexdigest()
    assert written["folds"][0]["selections"][0]["candidate_id"] == "a"
    assert "# Train-Selected Walk-Forward Evaluation" in markdown
    assert "| 2024-02 | selected | a | 0.03 | 0.03 |" in markdown
    assert "## Selection Evidence" in markdown
    assert "| 2024-02 | 1 | a | 0.10 | 1/1 | 0.01 | 10 | 0.02 | 0.03 |" in markdown
